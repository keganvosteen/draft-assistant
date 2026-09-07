"""Generate the app icon as PNG, Windows .ico and macOS .icns.

Stdlib only (zlib + struct), so `python packaging/make_icons.py` works on a
clean machine and on CI runners without adding Pillow to the build image.

The mark is a football on a dark rounded tile. Shapes are drawn from signed
distance functions and antialiased analytically, which keeps it crisp at 16px
without supersampling.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "icons"

# Windows .ico and macOS .icns want different size sets; render the union once.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)

BG_TOP = (17, 24, 39)
BG_BOTTOM = (49, 46, 129)
BALL_TOP = (200, 93, 40)
BALL_BOTTOM = (124, 45, 18)
LACE = (248, 250, 252)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def _rounded_rect_sdf(x: float, y: float, half: float, radius: float) -> float:
    """Negative inside. Centred at the origin, square of half-width `half`."""
    dx = abs(x) - (half - radius)
    dy = abs(y) - (half - radius)
    outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius


def _lens_sdf(x: float, y: float, a: float, b: float) -> float:
    """Football silhouette: the overlap of two circles, pointed at (+-a, 0)."""
    radius = (a * a + b * b) / (2 * b)
    offset = radius - b
    d1 = math.hypot(x, y + offset) - radius
    d2 = math.hypot(x, y - offset) - radius
    return max(d1, d2)


def _coverage(sdf: float, feather: float) -> float:
    """Antialiased inside-ness for a signed distance, in pixels."""
    return min(1.0, max(0.0, 0.5 - sdf / feather))


def _over(dst: tuple[float, float, float, float], color, alpha: float):
    """Source-over compositing on straight (non-premultiplied) RGBA."""
    if alpha <= 0.0:
        return dst
    dr, dg, db, da = dst
    out_a = alpha + da * (1.0 - alpha)
    if out_a <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    out = tuple(
        (c * alpha + d * da * (1.0 - alpha)) / out_a
        for c, d in zip(color, (dr, dg, db))
    )
    return (out[0], out[1], out[2], out_a)


def render(size: int) -> bytes:
    """Return raw RGBA bytes for one square icon."""
    s = float(size)
    feather = 1.0
    half = s / 2.0
    tile_half = half * 0.98
    tile_radius = s * 0.225

    ball_a = s * 0.315
    ball_b = s * 0.205

    lace_half_w = s * 0.115
    lace_thick = s * 0.028
    tick_half_h = s * 0.062
    tick_thick = s * 0.026
    tick_xs = [-s * 0.072, -s * 0.024, s * 0.024, s * 0.072]

    rows = bytearray()
    for py in range(size):
        row = bytearray()
        y = py + 0.5 - half
        for px in range(size):
            x = px + 0.5 - half

            pixel = (0.0, 0.0, 0.0, 0.0)

            tile_cov = _coverage(_rounded_rect_sdf(x, y, tile_half, tile_radius), feather)
            if tile_cov > 0.0:
                t = (y + half) / s
                pixel = _over(pixel, _lerp(BG_TOP, BG_BOTTOM, t), tile_cov)

            ball_cov = _coverage(_lens_sdf(x, y, ball_a, ball_b), feather)
            if ball_cov > 0.0:
                t = (y + ball_b) / (2 * ball_b)
                shade = _lerp(BALL_TOP, BALL_BOTTOM, min(1.0, max(0.0, t)))
                pixel = _over(pixel, shade, ball_cov)

                # Central lace bar plus the perpendicular ticks, unioned.
                lace_sdf = max(abs(x) - lace_half_w, abs(y) - lace_thick * 0.5)
                for tx in tick_xs:
                    tick = max(abs(x - tx) - tick_thick * 0.5, abs(y) - tick_half_h)
                    lace_sdf = min(lace_sdf, tick)
                lace_cov = _coverage(lace_sdf, feather) * ball_cov
                if lace_cov > 0.0:
                    pixel = _over(pixel, LACE, lace_cov)

            r, g, b, a = pixel
            row += bytes((round(r), round(g), round(b), round(a * 255)))
        rows += b"\x00" + row
    return bytes(rows)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def png_bytes(size: int, scanlines: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(scanlines, 9))
        + _chunk(b"IEND", b"")
    )


def write_ico(path: Path, images: dict[int, bytes]) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    sizes = [s for s in ICO_SIZES if s in images]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        data = images[size]
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    path.write_bytes(bytes(header) + bytes(entries) + bytes(payload))


# macOS icon type codes, by pixel dimension.
ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}


def write_icns(path: Path, images: dict[int, bytes]) -> None:
    body = bytearray()
    for size, tag in ICNS_TYPES.items():
        data = images.get(size)
        if data is None:
            continue
        body += tag + struct.pack(">I", len(data) + 8) + data
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + bytes(body))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(ICO_SIZES) | set(ICNS_SIZES))
    images: dict[int, bytes] = {}
    for size in wanted:
        images[size] = png_bytes(size, render(size))
        print(f"  rendered {size}x{size}")

    (OUT_DIR / "icon-256.png").write_bytes(images[256])
    (OUT_DIR / "icon-512.png").write_bytes(images[512])
    (OUT_DIR / "icon-1024.png").write_bytes(images[1024])
    write_ico(OUT_DIR / "DraftAssistant.ico", images)
    write_icns(OUT_DIR / "DraftAssistant.icns", images)
    print(f"Icons written to {OUT_DIR}")


if __name__ == "__main__":
    main()
