"""Hằng số cho RouterOS (MikroTik).

Mọi đường dẫn REST đã đối chiếu trên CCR2004-16G-2S+ / RouterOS 7.24.4 ngày 2026-10-14.
"""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "routeros_ha"
MANUFACTURER = "MikroTik"

CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_BLOCK_PREFIX = "block_prefix"
CONF_KILL_CONNECTIONS = "kill_connections"
CONF_MONITOR_PORTS = "monitor_ports"

DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 600
# Rule firewall filter có comment bắt đầu bằng chuỗi này → 1 switch "chặn thiết bị".
DEFAULT_BLOCK_PREFIX = "Block IP - "
DEFAULT_KILL_CONNECTIONS = True
# Mỗi cổng ethernet (kể cả SFP) → 1 binary_sensor link + 2 sensor tốc độ RX/TX.
DEFAULT_MONITOR_PORTS = True

# check-for-updates bắt router gọi ra upgrade.mikrotik.com → không cần làm mỗi lần poll.
UPDATE_CHECK_INTERVAL = timedelta(hours=12)

# Tốc độ link chỉ đổi khi cắm lại dây → đọc `/interface/ethernet/monitor` khi một cổng
# đổi trạng thái running, hoặc định kỳ theo mốc này.
PORT_RATE_REFRESH = timedelta(minutes=5)

REQUEST_TIMEOUT = 15
# Xoá connection-tracking song song tối đa N request một lúc.
KILL_CONCURRENCY = 8
