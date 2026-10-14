"""Sinh brand image cho integration — đúng quy cách repo home-assistant/brands.

Quy cách (README của home-assistant/brands, mục custom_integrations/<domain>/):
- PNG, nén lossless, viền cắt sát (không chừa khoảng trống thừa), nền ngoài ô trong suốt.
- icon.png 256×256, icon@2x.png 512×512 (tỉ lệ 1:1).
- logo.png cạnh ngắn 128–256 px, logo@2x.png cạnh ngắn 256–512 px — ở đây dùng lại icon.

Ảnh vẽ bằng stdlib (zlib + struct), không cần Pillow; khử răng cưa bằng siêu lấy mẫu
SS×SS điểm trên mỗi pixel. Thiết kế gốc (KHÔNG dùng logo MikroTik — thương hiệu của họ):
ô vuông bo góc gradient xanh đậm → đỏ + router trắng (thân, 2 ăng-ten, 3 đèn).
Cùng thư mục brand/ này HA 2026.x cũng tự phục vụ icon cho custom integration.

Dùng: python tools/make_brand.py   (sau đó restart HA mới thấy icon mới)
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "routeros_ha"
    / "brand"
)
TOP = (30, 45, 80)  # #1E2D50
BOTTOM = (200, 40, 50)  # #C82832


def inside_router(x: float, y: float) -> bool:
    # 3 đèn LED = lỗ tròn trong thân máy
    for lx in (0.32, 0.44, 0.56):
        if (x - lx) ** 2 + (y - 0.655) ** 2 <= 0.035**2:
            return False
    # thân máy: chữ nhật bo góc
    x0, x1, y0, y1, r = 0.16, 0.84, 0.54, 0.77, 0.06
    if x0 <= x <= x1 and y0 <= y <= y1:
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    # 2 ăng-ten
    for ax in (0.30, 0.70):
        if abs(x - ax) <= 0.035 and 0.22 <= y <= 0.54:
            return True
        if (x - ax) ** 2 + (y - 0.22) ** 2 <= 0.035**2:
            return True
    return False


SS = 4  # siêu lấy mẫu 4×4 điểm/pixel → viền mượt
TILE_RADIUS = 0.22  # bán kính bo góc ô nền, theo tỉ lệ cạnh


def inside_tile(x: float, y: float) -> bool:
    r = TILE_RADIUS
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int) -> bytes:
    px = bytearray()
    n = SS * SS
    for y in range(size):
        px.append(0)  # filter type 0 mỗi scanline
        t = y / (size - 1)
        bg = [TOP[i] + (BOTTOM[i] - TOP[i]) * t for i in range(3)]
        for x in range(size):
            tile = white = 0
            for sy in range(SS):
                fy = (y + (sy + 0.5) / SS) / size
                for sx in range(SS):
                    fx = (x + (sx + 0.5) / SS) / size
                    if inside_tile(fx, fy):
                        tile += 1
                        if inside_router(fx, fy):
                            white += 1
            if tile == 0:
                px.extend((0, 0, 0, 0))
                continue
            w = white / tile  # tỉ lệ trắng trong phần thuộc ô
            rgb = (round(bg[i] + (255 - bg[i]) * w) for i in range(3))
            px.extend((*rgb, round(255 * tile / n)))
    return bytes(px)


def write_png(path: pathlib.Path, size: int) -> None:
    raw = render(size)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    print(f"  {path.name:14} {size}x{size}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Sinh brand image vào {OUT}:")
    for name, size in (
        ("icon.png", 256),
        ("icon@2x.png", 512),
        ("logo.png", 256),
        ("logo@2x.png", 512),
    ):
        write_png(OUT / name, size)
    print("Lưu ý: HA chỉ hiển thị brand mới SAU KHI RESTART.")
