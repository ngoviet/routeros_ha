"""Đổi entity_id của routeros_ha về đúng id của integration cũ `mikrotik_router` (tomaae).

Mục đích: dashboard / automation không phải sửa, và lịch sử recorder nối tiếp vào id cũ.
Chạy SAU KHI đã xoá config entry `mikrotik_router` (để các id cũ được giải phóng).

    python tools/migrate_entity_ids.py           # chạy thử: chỉ in kế hoạch
    python tools/migrate_entity_ids.py --apply   # đổi thật

Cần `.env` có HA_URL (vd http://192.168.10.15:8123) và HA_TOKEN (long-lived token).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = "routeros_ha"

# key (phần unique_id sau "<serial>_") → entity_id cũ của mikrotik_router
FIXED = {
    "cpu_load": "sensor.mikrotik_cpu_load",
    "memory_usage": "sensor.mikrotik_memory_usage",
    "hdd_usage": "sensor.mikrotik_hdd_usage",
    "uptime": "sensor.mikrotik_uptime",
    "health_cpu-temperature": "sensor.mikrotik_ccr2004_16g_2s_cpu_temperature",
    "health_board-temperature1": "sensor.mikrotik_ccr2004_16g_2s_board_temperature",
}
# Switch chặn: mặc định switch.mikrotik_filter_block_ip_<slug>; ngoại lệ do tomaae từng tạo
# trùng tên nên HA thêm hậu tố _2 (dashboard đang dùng đúng id có hậu tố).
SWITCH_EXCEPTIONS = {"ipad_air": "switch.mikrotik_filter_block_ip_ipad_air_2"}


def target_for(key: str) -> str | None:
    if key in FIXED:
        return FIXED[key]
    if key.startswith("block_"):
        slug = key.removeprefix("block_")
        return SWITCH_EXCEPTIONS.get(slug, f"switch.mikrotik_filter_block_ip_{slug}")
    return None


def load_env() -> dict[str, str]:
    return dict(
        line.strip().split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


async def main(apply: bool) -> int:
    env = load_env()
    url = env["HA_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": env["HA_TOKEN"]}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            print("Token bị từ chối")
            return 1
        msg_id = 0

        async def call(payload: dict) -> dict:
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                res = json.loads(await ws.recv())
                if res.get("id") == msg_id:
                    return res

        entries = (await call({"type": "config/entity_registry/list"}))["result"]
        in_use = {e["entity_id"] for e in entries}
        ours = [e for e in entries if e["platform"] == DOMAIN]
        if not ours:
            print("Chưa có entity routeros_ha nào — thêm integration trước.")
            return 1
        if any(e["platform"] == "mikrotik_router" for e in entries):
            print(
                "⚠ Vẫn còn entity mikrotik_router — xoá config entry cũ trước rồi chạy lại."
            )

        failed = 0
        for e in sorted(ours, key=lambda e: e["entity_id"]):
            key = e["unique_id"].split("_", 1)[1]
            target = target_for(key)
            if target is None or target == e["entity_id"]:
                continue
            if target in in_use:
                print(
                    f"  BỎ QUA  {e['entity_id']} → {target} (id đích đang có người dùng)"
                )
                continue
            print(f"  {'ĐỔI' if apply else 'SẼ ĐỔI'}  {e['entity_id']} → {target}")
            if apply:
                res = await call(
                    {
                        "type": "config/entity_registry/update",
                        "entity_id": e["entity_id"],
                        "new_entity_id": target,
                    }
                )
                if not res.get("success"):
                    failed += 1
                    print(f"     lỗi: {res.get('error')}")
        if not apply:
            print("\nChạy thử xong. Thêm --apply để đổi thật.")
        return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="đổi thật (mặc định chỉ in)"
    )
    sys.exit(asyncio.run(main(parser.parse_args().apply)))
