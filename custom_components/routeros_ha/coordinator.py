"""DataUpdateCoordinator: 1 router = 1 coordinator, mọi entity đọc chung một snapshot."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .api import RouterOSApi, RouterOSApiError, RouterOSAuthError, as_bool
from .const import DOMAIN, KILL_CONCURRENCY, PORT_RATE_REFRESH, UPDATE_CHECK_INTERVAL

_LOGGER = logging.getLogger(__name__)

_UPTIME_RE = re.compile(r"(\d+)([wdhms])")
_UPTIME_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
# Uptime chỉ chính xác tới giây và mỗi lần poll lệch vài giây → giữ nguyên mốc khởi
# động cũ nếu lệch ít hơn ngưỡng này, tránh sensor timestamp đổi state liên tục.
_BOOT_JITTER = timedelta(seconds=60)
# Refresh sớm (vd. ngay sau khi bấm chặn) cách lần đọc trước quá ngắn → tốc độ tính
# từ bộ đếm byte nhiễu, nên giữ số cũ.
_MIN_RATE_WINDOW = 5.0
_LINK_RATE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([GM])bps", re.IGNORECASE)
_PORT_PROPS = (
    "name,default-name,running,disabled,rx-byte,tx-byte,comment,link-downs,mac-address"
)


def parse_uptime(value: str | None) -> int | None:
    """ "3w6d11h27m20s" → giây."""
    if not value:
        return None
    parts = _UPTIME_RE.findall(value)
    if not parts:
        return None
    return sum(int(n) * _UPTIME_UNITS[u] for n, u in parts)


@dataclass(frozen=True)
class BlockRule:
    key: str  # slug ổn định từ comment (không dùng .id — đổi khi tạo lại rule)
    rule_id: str  # .id hiện tại, vd "*2F"
    comment: str
    label: str  # comment đã bỏ tiền tố, vd "Tivi 1"
    src_address: str | None
    enabled: bool  # rule đang bật = thiết bị ĐANG BỊ CHẶN


def parse_link_rate(value: str | None) -> int | None:
    """ "2.5Gbps" → 2500, "100Mbps" → 100 (Mbit/s). Không có link → None."""
    m = _LINK_RATE_RE.match(value or "")
    if not m:
        return None
    return round(float(m.group(1)) * (1000 if m.group(2).upper() == "G" else 1))


def throughput(prev: int | None, cur: int | None, seconds: float) -> int | None:
    """Tốc độ trung bình (bit/s) giữa 2 lần đọc bộ đếm byte của cổng."""
    if prev is None or cur is None or seconds <= 0:
        return None
    delta = cur - prev
    if delta < 0:  # bộ đếm về 0: router khởi động lại / reset-counters
        return None
    return round(delta * 8 / seconds)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PortData:
    key: str  # slug của default-name → ổn định khi đổi tên cổng
    name: str  # tên hiện tại, vd "ether1", "sfp-sfpplus1"
    default_name: str | None
    comment: str | None
    mac_address: str | None
    disabled: bool
    running: bool  # có link
    link_downs: int | None
    rate: str | None  # "1Gbps"; None khi không có link
    speed_mbps: int | None
    rx_bps: int | None  # router NHẬN vào từ cổng này
    tx_bps: int | None  # router GỬI ra cổng này


@dataclass(frozen=True)
class HealthItem:
    name: str  # vd "cpu-temperature"
    value: str
    unit: str  # "C", "RPM", "V", "W", "A" hoặc "" (dạng trạng thái ok/fail)


@dataclass
class RouterData:
    resource: dict[str, Any]
    health: dict[str, HealthItem] = field(default_factory=dict)
    rules: dict[str, BlockRule] = field(default_factory=dict)
    dhcp_bound: int | None = None
    boot_time: datetime | None = None
    package_update: dict[str, Any] | None = None
    routerboard: dict[str, Any] | None = None
    # None = không theo dõi cổng, hoặc lần đọc này lỗi.
    ports: dict[str, PortData] | None = None


def parse_rules(filters: list[dict[str, Any]], prefix: str) -> dict[str, BlockRule]:
    rules: dict[str, BlockRule] = {}
    for item in filters:
        comment = str(item.get("comment") or "")
        if not prefix or not comment.startswith(prefix) or ".id" not in item:
            continue
        label = comment[len(prefix) :].strip() or comment
        base = slugify(label) or slugify(item[".id"])
        key, n = base, 2
        while key in rules:  # 2 rule trùng comment → thêm hậu tố
            key, n = f"{base}_{n}", n + 1
        rules[key] = BlockRule(
            key=key,
            rule_id=item[".id"],
            comment=comment,
            label=label,
            src_address=item.get("src-address"),
            enabled=not as_bool(item.get("disabled")),
        )
    return rules


def parse_health(items: list[dict[str, Any]]) -> dict[str, HealthItem]:
    return {
        str(i["name"]): HealthItem(
            name=str(i["name"]),
            value=str(i.get("value", "")),
            unit=str(i.get("type") or ""),
        )
        for i in items
        if i.get("name")
    }


class RouterOSCoordinator(DataUpdateCoordinator[RouterData]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: RouterOSApi,
        entry: ConfigEntry,
        update_interval: int,
        block_prefix: str,
        kill_connections: bool,
        monitor_ports: bool = True,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.block_prefix = block_prefix
        self.kill_connections = kill_connections
        self.identity: str = api.host
        self.serial: str = entry.unique_id or api.host
        self._next_update_check: datetime | None = None
        self._package_update: dict[str, Any] | None = None
        self._routerboard: dict[str, Any] | None = None
        self.monitor_ports = monitor_ports
        # Switch thuần (CRS) không chạy DHCP server → không tạo sensor số thiết bị DHCP.
        self.has_dhcp = True
        self._counters: dict[str, tuple[int | None, int | None, float]] = {}
        self._link_rates: dict[str, str | None] = {}
        self._last_running: dict[str, bool] | None = None
        self._next_rate_check = 0.0

    async def _async_setup(self) -> None:
        try:
            ident = await self.api.get_dict("system/identity")
        except RouterOSAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RouterOSApiError as err:
            raise UpdateFailed(str(err)) from err
        self.identity = ident.get("name") or self.api.host
        servers = await self._safe(
            self.api.get_list("ip/dhcp-server", proplist=".id"), "dhcp-server"
        )
        self.has_dhcp = servers is None or bool(servers)

    async def _safe(self, coro: Any, what: str) -> Any:
        """Endpoint phụ (health, lease, update): lỗi thì bỏ qua, không làm hỏng cả lần poll."""
        try:
            return await coro
        except RouterOSAuthError:
            raise
        except RouterOSApiError as err:
            _LOGGER.debug("routeros: đọc %s lỗi: %s", what, err)
            return None

    async def _check_updates(self) -> None:
        now = dt_util.utcnow()
        if self._next_update_check and now < self._next_update_check:
            return
        self._next_update_check = now + UPDATE_CHECK_INTERVAL
        # Lệnh này cần router ra được internet; lỗi (kể cả thiếu quyền) thì vẫn đọc
        # kết quả lần kiểm tra trước ở GET bên dưới.
        await self._safe(
            self.api.post("system/package/update/check-for-updates"),
            "check-for-updates",
        )
        self._package_update = await self._safe(
            self.api.get_dict("system/package/update"), "package/update"
        )
        self._routerboard = await self._safe(
            self.api.get_dict("system/routerboard"), "routerboard"
        )

    async def _read_link_rates(self, running: dict[str, bool], now: float) -> None:
        """Đọc tốc độ link khi có cổng đổi trạng thái hoặc tới hạn PORT_RATE_REFRESH."""
        if running == self._last_running and now < self._next_rate_check:
            return
        mon = await self._safe(
            self.api.post(
                "interface/ethernet/monitor",
                {
                    "numbers": ",".join(running),
                    "once": True,
                    ".proplist": "name,status,rate",
                },
            ),
            "ethernet monitor",
        )
        rows = [mon] if isinstance(mon, dict) else mon
        if not isinstance(rows, list):
            return  # lỗi → thử lại ở lần poll sau
        self._link_rates = {
            str(m["name"]): (m.get("rate") if m.get("status") == "link-ok" else None)
            for m in rows
            if isinstance(m, dict) and m.get("name")
        }
        self._last_running = running
        self._next_rate_check = now + PORT_RATE_REFRESH.total_seconds()

    async def _read_ports(self) -> dict[str, PortData] | None:
        """Cổng ethernet vật lý (kể cả SFP): link, tốc độ link, lưu lượng RX/TX."""
        rows = await self._safe(
            self.api.get_list("interface", proplist=_PORT_PROPS, type="ether"),
            "interface",
        )
        if rows is None:
            return None
        now = time.monotonic()
        rows = [r for r in rows if r.get("name")]
        running = {str(r["name"]): as_bool(r.get("running")) for r in rows}
        if running:
            await self._read_link_rates(running, now)

        old = self.data.ports if self.data and self.data.ports else {}
        ports: dict[str, PortData] = {}
        for r in rows:
            name = str(r["name"])
            key = slugify(str(r.get("default-name") or name))
            rx, tx = _int(r.get("rx-byte")), _int(r.get("tx-byte"))
            last = self._counters.get(key)
            if last and now - last[2] < _MIN_RATE_WINDOW and key in old:
                rx_bps, tx_bps = old[key].rx_bps, old[key].tx_bps
            else:
                rx_bps = throughput(last[0], rx, now - last[2]) if last else None
                tx_bps = throughput(last[1], tx, now - last[2]) if last else None
                self._counters[key] = (rx, tx, now)
            rate = self._link_rates.get(name) if running[name] else None
            ports[key] = PortData(
                key=key,
                name=name,
                default_name=r.get("default-name"),
                comment=r.get("comment") or None,
                mac_address=r.get("mac-address"),
                disabled=as_bool(r.get("disabled")),
                running=running[name],
                link_downs=_int(r.get("link-downs")),
                rate=rate,
                speed_mbps=parse_link_rate(rate),
                rx_bps=rx_bps,
                tx_bps=tx_bps,
            )
        return ports

    async def _async_update_data(self) -> RouterData:
        try:
            resource, filters, health, leases = await asyncio.gather(
                self.api.get_dict("system/resource"),
                self.api.get_list(
                    "ip/firewall/filter",
                    proplist=".id,comment,disabled,src-address",
                ),
                self._safe(self.api.get_list("system/health"), "health"),
                self._safe(
                    self.api.get_list(
                        "ip/dhcp-server/lease", proplist=".id", status="bound"
                    ),
                    "dhcp lease",
                ),
            )
            await self._check_updates()
            ports = await self._read_ports() if self.monitor_ports else None
        except RouterOSAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RouterOSApiError as err:
            raise UpdateFailed(str(err)) from err

        boot_time = None
        if (secs := parse_uptime(resource.get("uptime"))) is not None:
            boot_time = (dt_util.utcnow() - timedelta(seconds=secs)).replace(
                microsecond=0
            )
            old = self.data.boot_time if self.data else None
            if old and abs(boot_time - old) < _BOOT_JITTER:
                boot_time = old

        return RouterData(
            resource=resource,
            health=parse_health(health or []),
            rules=parse_rules(filters, self.block_prefix),
            dhcp_bound=len(leases) if leases is not None else None,
            boot_time=boot_time,
            package_update=self._package_update,
            routerboard=self._routerboard,
            ports=ports,
        )

    async def async_set_blocked(self, key: str, blocked: bool) -> None:
        rule = self.data.rules.get(key) if self.data else None
        if rule is None:
            raise HomeAssistantError(f"Không còn rule chặn '{key}' trên router")
        try:
            await self.api.set_filter_disabled(rule.rule_id, disabled=not blocked)
        except RouterOSApiError as err:
            raise HomeAssistantError(
                f"Không đổi được rule {rule.comment}: {err}"
            ) from err

        # Cập nhật ngay trên snapshot hiện có để UI phản hồi tức thì; lần poll sau xác nhận.
        self.data.rules[key] = replace(rule, enabled=blocked)
        self.async_update_listeners()

        if blocked and self.kill_connections and rule.src_address:
            ip = rule.src_address
            if "/" in ip or "-" in ip:
                _LOGGER.debug("routeros: %s là dải địa chỉ, bỏ qua cắt kết nối", ip)
            else:
                try:
                    n = await self.api.remove_connections_from(ip, KILL_CONCURRENCY)
                    _LOGGER.debug("routeros: đã cắt %d kết nối của %s", n, ip)
                except RouterOSApiError as err:
                    # Rule đã bật là chính; kết nối cũ sẽ tự hết khi đóng.
                    _LOGGER.warning(
                        "routeros: không cắt được kết nối của %s: %s", ip, err
                    )

        await self.async_request_refresh()
