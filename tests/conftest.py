"""Fixture chung. Payload mô phỏng ĐÚNG hình dạng REST RouterOS 7.24.4 (CCR2004, đo 2026-10-14):
mọi giá trị là chuỗi, menu singleton trả dict. Serial / IP là giả.
"""

from __future__ import annotations

import sys

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    # PHACC chặn socket trước mỗi test; Windows không có AF_UNIX nên event loop
    # dựng self-pipe bằng AF_INET → bị chặn. Test ở đây mock HTTP, không gọi mạng.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

HOST = "192.168.88.1"
REST = f"http://{HOST}:80/rest/"
SERIAL = "HJ0000TEST"
USER_INPUT = {
    "host": HOST,
    "port": 80,
    "ssl": False,
    "verify_ssl": False,
    "username": "ha",
    "password": "pw",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


RESOURCE = {
    "board-name": "CCR2004-16G-2S+",
    "cpu-load": "6",
    "free-hdd-space": "108707840",
    "free-memory": "3835666432",
    "total-hdd-space": "134217728",
    "total-memory": "4294967296",
    "uptime": "3w6d11h27m20s",
    "version": "7.24.4 (stable)",
}
HEALTH = [
    {".id": "*11", "name": "cpu-temperature", "type": "C", "value": "58"},
    {".id": "*36", "name": "fan-state", "type": "", "value": "ok"},
    {".id": "*1B59", "name": "fan1-speed", "type": "RPM", "value": "3870"},
    {".id": "*1BBD", "name": "board-temperature1", "type": "C", "value": "42"},
    {".id": "*1CE9", "name": "psu1-state", "type": "", "value": "ok"},
    {".id": "*1CEA", "name": "psu2-state", "type": "", "value": "fail"},
]
FILTERS = [
    {".id": "*21", "comment": "Cho phep du lieu phan hoi", "disabled": "false"},
    {
        ".id": "*2F",
        "comment": "Block IP - Tivi 1",
        "disabled": "true",
        "src-address": "192.168.10.20",
    },
    {
        ".id": "*33",
        "comment": "Block IP - Ipad air",
        "disabled": "false",
        "src-address": "192.168.10.24",
    },
]
PACKAGE_UPDATE = {
    "channel": "stable",
    "installed-version": "7.24.4",
    "latest-version": "7.24.5",
    "status": "New version is available",
}
ROUTERBOARD = {
    "current-firmware": "7.24.4",
    "model": "CCR2004-16G-2S+",
    "revision": "r3",
    "routerboard": "true",
    "serial-number": SERIAL,
    "upgrade-firmware": "7.24.4",
}
CONNECTIONS = [
    {".id": "*A1", "src-address": "192.168.10.20:51000"},
    {".id": "*A2", "src-address": "192.168.10.20"},
    {".id": "*A3", "src-address": "192.168.10.200:443"},
    {".id": "*A4", "src-address": "192.168.10.21:5353"},
]
# GET /interface?type=ether: chỉ cổng vật lý; mọi số là chuỗi.
INTERFACES = [
    {
        ".id": "*2",
        "name": "ether1",
        "default-name": "ether1",
        "running": "true",
        "disabled": "false",
        "rx-byte": "1000000",
        "tx-byte": "2000000",
        "link-downs": "1",
        "mac-address": "F4:1E:57:00:00:01",
    },
    {
        ".id": "*3",
        "name": "wan-viettel",  # đã đổi tên → key vẫn theo default-name
        "default-name": "ether2",
        "comment": "Modem",
        "running": "false",
        "disabled": "true",
        "rx-byte": "0",
        "tx-byte": "0",
        "link-downs": "0",
        "mac-address": "F4:1E:57:00:00:02",
    },
    {
        ".id": "*12",
        "name": "sfp-sfpplus1",
        "default-name": "sfp-sfpplus1",
        "running": "true",
        "disabled": "false",
        "rx-byte": "5000000",
        "tx-byte": "6000000",
        "link-downs": "2",
        "mac-address": "F4:1E:57:00:00:12",
    },
]
# POST /interface/ethernet/monitor once=true
ETHERNET_MONITOR = [
    {"name": "ether1", "status": "link-ok", "rate": "1Gbps"},
    {"name": "wan-viettel", "status": "no-link"},
    {"name": "sfp-sfpplus1", "status": "link-ok", "rate": "10Gbps"},
]

LEASES = [
    {
        "mac-address": "AA:00:00:00:00:01",
        "address": "192.168.88.12",
        "comment": "NAS",
        "host-name": "nas",
        "status": "bound",
    },
    {
        "mac-address": "AA:00:00:00:00:02",
        "address": "192.168.88.50",
        "host-name": "vm-1",
        "status": "bound",
    },
    {
        "mac-address": "AA:00:00:00:00:03",
        "address": "192.168.88.51",
        "host-name": "vm-2",
        "status": "waiting",
    },
]
# GET /interface/bridge/host?local=false: MAC học được trên từng cổng
BRIDGE_HOSTS = [
    {"mac-address": "aa:00:00:00:00:01", "on-interface": "ether1"},
    {"mac-address": "AA:00:00:00:00:02", "on-interface": "ether1"},
]
# GET /ip/neighbor: LLDP/MNDP — `interface` = "cổng,bridge"
NEIGHBORS = [
    {
        "interface": "sfp-sfpplus1,bridge",
        "identity": "CRS326",
        "address": "192.168.88.2",
    }
]


DEFAULT_ROUTES: dict[tuple[str, str], dict] = {
    ("get", "system/identity"): {"json": {"name": "CCR2004"}},
    ("get", "system/resource"): {"json": RESOURCE},
    ("get", "system/health"): {"json": HEALTH},
    ("get", "system/routerboard"): {"json": ROUTERBOARD},
    ("get", "system/package/update"): {"json": PACKAGE_UPDATE},
    ("post", "system/package/update/check-for-updates"): {"json": []},
    ("get", "ip/firewall/filter"): {"json": FILTERS},
    ("get", "ip/dhcp-server/lease"): {"json": LEASES},
    ("get", "ip/firewall/connection"): {"json": CONNECTIONS},
    ("get", "ip/dhcp-server"): {"json": [{".id": "*1"}]},
    ("get", "interface"): {"json": INTERFACES},
    ("post", "interface/ethernet/monitor"): {"json": ETHERNET_MONITOR},
    ("get", "interface/bridge/host"): {"json": BRIDGE_HOSTS},
    ("get", "ip/neighbor"): {"json": NEIGHBORS},
}


def mock_router(aioclient_mock, overrides: dict[tuple[str, str], dict] | None = None):
    """Đăng ký mọi endpoint; `overrides` thay response của từng (method, path)."""
    routes = {**DEFAULT_ROUTES, **(overrides or {})}
    for (method, path), kwargs in routes.items():
        getattr(aioclient_mock, method)(REST + path, **kwargs)
    return aioclient_mock


@pytest.fixture
def router(aioclient_mock):
    """Router giả lập: mọi endpoint integration đọc đều OK."""
    return mock_router(aioclient_mock)
