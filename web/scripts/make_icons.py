"""Generate simple non-transparent PNG placeholders for the PWA manifest."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


PUBLIC = Path(__file__).resolve().parent.parent / "public"
BOLT = [(0.58, 0.09), (0.22, 0.57), (0.46, 0.57), (0.40, 0.91), (0.79, 0.41), (0.55, 0.41)]


def inside_polygon(x: float, y: float, vertices: list[tuple[float, float]]) -> bool:
    """Test a pixel center against a polygon; coordinates and vertices are inputs; return inclusion."""
    inside = False
    previous = vertices[-1]
    for current in vertices:
        if (current[1] > y) != (previous[1] > y):
            crossing = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    """Encode a PNG chunk; kind and payload are inputs; return its bytes with CRC."""
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def write_icon(size: int, destination: Path) -> None:
    """Draw a blue icon with a white bolt; size and path are inputs; return nothing."""
    scanlines = bytearray()
    for row in range(size):
        scanlines.append(0)
        for column in range(size):
            color = (255, 255, 255, 255) if inside_polygon((column + 0.5) / size, (row + 0.5) / size, BOLT) else (59, 59, 255, 255)
            scanlines.extend(color)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    destination.write_bytes(b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(scanlines, 9)) + png_chunk(b"IEND", b""))


if __name__ == "__main__":
    for icon_size in (192, 512):
        write_icon(icon_size, PUBLIC / f"icon-{icon_size}.png")
