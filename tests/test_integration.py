"""API, config flow, setup và entity — HTTP được mock bằng aioclient_mock."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.routeros_ha.config_flow import normalize_host
from custom_components.routeros_ha.const import DOMAIN
from custom_components.routeros_ha.coordinator import (
    parse_link_rate,
    parse_rules,
    parse_uptime,
    throughput,
)

from .conftest import FILTERS, HOST, INTERFACES, REST, SERIAL, USER_INPUT, mock_router


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="CCR2004", unique_id=SERIAL, data=dict(USER_INPUT)
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert eid, f"thiếu entity {platform} {key}"
    return eid


def _calls(mock, method: str, suffix: str) -> list:
    return [
        c
        for c in mock.mock_calls
        if c[0].upper() == method and str(c[1]).split("?")[0].endswith(suffix)
    ]


# --- hàm thuần ------------------------------------------------------------


def test_parse_uptime():
    assert (
        parse_uptime("3w6d11h27m20s")
        == 3 * 604800 + 6 * 86400 + 11 * 3600 + 27 * 60 + 20
    )
    assert parse_uptime("45s") == 45
    assert parse_uptime("") is None
    assert parse_uptime("garbage") is None


def test_parse_rules_prefix_and_bool_strings():
    rules = parse_rules(FILTERS, "Block IP - ")
    assert set(rules) == {"tivi_1", "ipad_air"}
    assert rules["tivi_1"].enabled is False  # disabled="true" (chuỗi) → không chặn
    assert rules["ipad_air"].enabled is True
    assert rules["tivi_1"].label == "Tivi 1"
    assert rules["tivi_1"].rule_id == "*2F"


def test_parse_rules_duplicate_comment():
    rows = [
        {".id": "*1", "comment": "Block IP - TV", "disabled": "true"},
        {".id": "*2", "comment": "Block IP - TV", "disabled": "true"},
    ]
    assert set(parse_rules(rows, "Block IP - ")) == {"tv", "tv_2"}


@pytest.mark.parametrize(
    "value,mbps",
    [
        ("1Gbps", 1000),
        ("2.5Gbps", 2500),
        ("10Gbps", 10000),
        ("100Mbps", 100),
        ("10Mbps", 10),
        (None, None),
        ("", None),
    ],
)
def test_parse_link_rate(value, mbps):
    assert parse_link_rate(value) == mbps


def test_throughput():
    assert throughput(1000, 4750, 30) == 1000  # 3750 B * 8 / 30 s
    assert throughput(None, 10, 30) is None
    assert throughput(10, 5, 30) is None  # bộ đếm về 0 sau khi reboot
    assert throughput(10, 20, 0) is None


@pytest.mark.parametrize(
    "value,host",
    [
        ("192.168.88.1", "192.168.88.1"),
        ("  router.lan ", "router.lan"),
        ("http://192.168.88.1/", "192.168.88.1"),
        ("https://192.168.88.1:8443/webfig/", "192.168.88.1"),
        ("[fe80::1]", "[fe80::1]"),
        ("http://[fe80::1]:8080/", "[fe80::1]"),
    ],
)
def test_normalize_host(value, host):
    assert normalize_host(value) == host


# --- config flow ----------------------------------------------------------


async def test_config_flow_strips_url_from_host(hass: HomeAssistant, router):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "host": f"http://{HOST}/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == HOST


async def test_config_flow_creates_entry(hass: HomeAssistant, router):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CCR2004"
    assert result["result"].unique_id == SERIAL


async def test_config_flow_invalid_auth(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(REST + "system/identity", status=401, text="")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_config_flow_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(
        REST + "system/identity",
        status=500,
        json={"error": 500, "message": "Internal Server Error"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    assert result["errors"] == {"base": "cannot_connect"}


# --- setup + entity -------------------------------------------------------


async def test_setup_creates_entities(hass: HomeAssistant, router):
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get(_entity_id(hass, "sensor", "cpu_load")).state == "6.0"
    assert hass.states.get(_entity_id(hass, "sensor", "memory_usage")).state == "11"
    assert hass.states.get(_entity_id(hass, "sensor", "hdd_usage")).state == "19"
    assert hass.states.get(_entity_id(hass, "sensor", "dhcp_clients")).state == "2"
    assert hass.states.get(_entity_id(hass, "sensor", "uptime")).state not in (
        "unknown",
        "unavailable",
    )

    temp = hass.states.get(_entity_id(hass, "sensor", "health_cpu-temperature"))
    assert temp.state == "58.0" and temp.attributes["unit_of_measurement"] == "°C"
    assert (
        hass.states.get(_entity_id(hass, "sensor", "health_fan1-speed")).state
        == "3870.0"
    )

    assert (
        hass.states.get(_entity_id(hass, "binary_sensor", "health_psu2-state")).state
        == "on"
    )
    assert (
        hass.states.get(_entity_id(hass, "binary_sensor", "health_psu1-state")).state
        == "off"
    )
    assert (
        hass.states.get(_entity_id(hass, "binary_sensor", "health_fan-state")).state
        == "off"
    )

    tivi = hass.states.get(_entity_id(hass, "switch", "block_tivi_1"))
    assert tivi.state == "off"
    assert tivi.attributes["src_address"] == "192.168.10.20"
    assert hass.states.get(_entity_id(hass, "switch", "block_ipad_air")).state == "on"
    # rule không có tiền tố → không có switch
    assert len(hass.states.async_entity_ids("switch")) == 2

    upd = hass.states.get(_entity_id(hass, "update", "routeros_update"))
    assert upd.state == "on"
    assert upd.attributes["installed_version"] == "7.24.4"
    assert upd.attributes["latest_version"] == "7.24.5"
    fw = hass.states.get(_entity_id(hass, "update", "firmware_update"))
    assert fw.state == "off"

    device_id = er.async_get(hass).async_get(upd.entity_id).device_id
    device = dr.async_get(hass).async_get(device_id)
    assert device.configuration_url == f"http://{HOST}"
    assert device.model == "CCR2004-16G-2S+"


async def test_block_patches_rule_and_kills_connections(hass: HomeAssistant, router):
    await _setup(hass)
    router.patch(REST + "ip/firewall/filter/*2F", json=[])
    router.delete(REST + "ip/firewall/connection/*A1", status=204, text="")
    router.delete(REST + "ip/firewall/connection/*A2", status=204, text="")
    switch = _entity_id(hass, "switch", "block_tivi_1")

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )

    patch = _calls(router, "PATCH", "ip/firewall/filter/*2F")
    assert len(patch) == 1 and patch[0][2] == {"disabled": "false"}
    deleted = {str(c[1]).rsplit("/", 1)[1] for c in _calls(router, "DELETE", "")}
    # chỉ connection của đúng 192.168.10.20 (không dính .200 hay .21)
    assert deleted == {"*A1", "*A2"}


async def test_unblock_does_not_kill(hass: HomeAssistant, router):
    await _setup(hass)
    router.patch(REST + "ip/firewall/filter/*33", json=[])
    switch = _entity_id(hass, "switch", "block_ipad_air")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )

    patch = _calls(router, "PATCH", "ip/firewall/filter/*33")
    assert patch[0][2] == {"disabled": "true"}
    assert not _calls(router, "DELETE", "")


async def test_kill_disabled_by_option(hass: HomeAssistant, router):
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"kill_connections": False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    router.patch(REST + "ip/firewall/filter/*2F", json=[])

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": _entity_id(hass, "switch", "block_tivi_1")},
        blocking=True,
    )
    assert _calls(router, "PATCH", "ip/firewall/filter/*2F")
    assert not _calls(router, "GET", "ip/firewall/connection")


async def test_kill_failure_still_blocks(hass: HomeAssistant, aioclient_mock):
    mock_router(
        aioclient_mock,
        {
            ("get", "ip/firewall/connection"): {
                "status": 403,
                "json": {"error": 403, "message": "Forbidden"},
            }
        },
    )
    await _setup(hass)
    aioclient_mock.patch(REST + "ip/firewall/filter/*2F", json=[])
    switch = _entity_id(hass, "switch", "block_tivi_1")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    # lỗi cắt kết nối chỉ là warning: rule vẫn được bật, service không ném lỗi
    assert _calls(aioclient_mock, "PATCH", "ip/firewall/filter/*2F")


async def test_setup_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(REST + "system/identity", status=401, text="")
    entry = _entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_health_endpoint_error_is_tolerated(hass: HomeAssistant, aioclient_mock):
    """CHR / x86 không có /system/health → vẫn setup được, chỉ thiếu sensor health."""
    mock_router(
        aioclient_mock,
        {
            ("get", "system/identity"): {"json": {"name": "CHR"}},
            ("get", "system/health"): {
                "status": 400,
                "json": {"error": 400, "message": "Bad Request"},
            },
            ("get", "system/routerboard"): {"json": {"routerboard": "false"}},
            ("get", "system/package/update"): {"json": {"installed-version": "7.24.4"}},
            ("post", "system/package/update/check-for-updates"): {
                "status": 400,
                "json": {},
            },
        },
    )
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert not hass.states.async_entity_ids("binary_sensor")
    upd = hass.states.get(_entity_id(hass, "update", "routeros_update"))
    assert upd.state == "off"  # chưa có latest-version → coi như mới nhất
    # không có RouterBOARD firmware
    assert len(hass.states.async_entity_ids("update")) == 1


@pytest.mark.parametrize(
    "prefix,count", [("Block IP - ", 2), ("Cho phep", 1), ("Không có", 0)]
)
async def test_block_prefix_option(hass: HomeAssistant, router, prefix, count):
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"block_prefix": prefix})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("switch")) == count


async def test_options_flow(hass: HomeAssistant, router):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 60, "block_prefix": "Chan - ", "kill_connections": False},
    )
    await hass.async_block_till_done()  # đổi options → entry tự reload
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["block_prefix"] == "Chan - "
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_updates_password(hass: HomeAssistant, router):
    entry = await _setup(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "ha", "password": "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"


# --- cổng ethernet ---------------------------------------------------------


async def test_port_entities(hass: HomeAssistant, router):
    await _setup(hass)

    link = hass.states.get(_entity_id(hass, "binary_sensor", "port_ether1_link"))
    assert link.state == "on"
    assert link.attributes["port"] == "ether1"
    assert link.attributes["rate"] == "1Gbps"
    assert link.attributes["speed_mbps"] == 1000
    assert link.attributes["device_class"] == "connectivity"

    sfp = hass.states.get(_entity_id(hass, "binary_sensor", "port_sfp_sfpplus1_link"))
    assert sfp.attributes["speed_mbps"] == 10000

    # cổng đổi tên: unique_id theo default-name, thuộc tính `port` theo tên hiện tại
    wan = hass.states.get(_entity_id(hass, "binary_sensor", "port_ether2_link"))
    assert wan.state == "off"
    assert wan.attributes["port"] == "wan-viettel"
    assert wan.attributes["comment"] == "Modem"
    assert wan.attributes["disabled"] is True
    assert wan.attributes["speed_mbps"] is None

    rx = hass.states.get(_entity_id(hass, "sensor", "port_ether1_rx"))
    assert rx.attributes["port"] == "ether1"
    assert rx.attributes["direction"] == "rx"
    assert rx.attributes["device_class"] == "data_rate"
    # lần đọc đầu chưa có mốc để tính tốc độ
    assert rx.state == "unknown"
    assert (
        hass.states.get(_entity_id(hass, "sensor", "port_ether1_tx")).state == "unknown"
    )


async def test_port_rate_from_counters(hass: HomeAssistant, router, monkeypatch):
    import custom_components.routeros_ha.coordinator as coord

    clock = [1000.0]
    monkeypatch.setattr(coord.time, "monotonic", lambda: clock[0])
    entry = await _setup(hass)

    rows = [dict(r) for r in INTERFACES]
    rows[0]["rx-byte"] = str(1000000 + 3750000)  # +3,75 MB trong 30 s = 1 Mbit/s
    rows[0]["tx-byte"] = str(2000000 + 375000)
    mock_interfaces(router, rows)
    clock[0] += 30
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    rx = hass.states.get(_entity_id(hass, "sensor", "port_ether1_rx"))
    assert rx.attributes["unit_of_measurement"] == "Mbit/s"
    assert float(rx.state) == pytest.approx(1.0)
    tx = hass.states.get(_entity_id(hass, "sensor", "port_ether1_tx"))
    assert float(tx.state) == pytest.approx(0.1)
    # running không đổi + chưa tới hạn → không đọc lại tốc độ link
    assert not _calls(router, "POST", "interface/ethernet/monitor")


async def test_ports_disabled_by_option(hass: HomeAssistant, router):
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"monitor_ports": False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not _calls(router, "GET", "interface")
    assert not [
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if "_port_" in e.unique_id
    ]


async def test_switch_without_dhcp_server(hass: HomeAssistant, aioclient_mock):
    """CRS chỉ làm switch: không có DHCP server → không tạo sensor DHCP."""
    mock_router(aioclient_mock, {("get", "ip/dhcp-server"): {"json": []}})
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_dhcp_clients") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_port_ether1_rx")


def mock_interfaces(mock, rows: list[dict]) -> None:
    """Thay response GET /interface (aioclient_mock khớp route đăng ký trước)."""
    mock.mock_calls.clear()
    mock._mocks = [m for m in mock._mocks if not str(m._url).endswith("/interface")]
    mock.get(REST + "interface", json=rows)
