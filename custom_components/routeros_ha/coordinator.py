"""DataUpdateCoordinator: 1 router = 1 coordinator, mọi entity đọc chung một snapshot."""

from __future__ import annotations

import asyncio
import logging
import re
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
from .const import DOMAIN, KILL_CONCURRENCY, UPDATE_CHECK_INTERVAL

_LOGGER = logging.getLogger(__name__)

_UPTIME_RE = re.compile(r"(\d+)([wdhms])")
_UPTIME_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
# Uptime chỉ chính xác tới giây và mỗi lần poll lệch vài giây → giữ nguyên mốc khởi
# động cũ nếu lệch ít hơn ngưỡng này, tránh sensor timestamp đổi state liên tục.
_BOOT_JITTER = timedelta(seconds=60)


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

    async def _async_setup(self) -> None:
        try:
            ident = await self.api.get_dict("system/identity")
        except RouterOSAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RouterOSApiError as err:
            raise UpdateFailed(str(err)) from err
        self.identity = ident.get("name") or self.api.host

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
