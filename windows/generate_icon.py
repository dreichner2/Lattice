#!/usr/bin/env python3
"""Generate the deterministic multi-size Lattice Windows application icon."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _rounded_square_contains(x: int, y: int, size: int) -> bool:
    inset = max(1, round(size * 0.035))
    radius = max(2, round(size * 0.18))
    left = inset
    top = inset
    right = size - inset
    bottom = size - inset
    px = x + 0.5
    py = y + 0.5
    if not (left <= px < right and top <= py < bottom):
        return False
    center_x = min(max(px, left + radius), right - radius)
    center_y = min(max(py, top + radius), bottom - radius)
    return (px - center_x) ** 2 + (py - center_y) ** 2 <= radius**2


def _render_pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    transparent = (0, 0, 0, 0)
    pixels = [[transparent for _x in range(size)] for _y in range(size)]

    background = (32, 36, 48, 255)
    for y in range(size):
        for x in range(size):
            if _rounded_square_contains(x, y, size):
                pixels[y][x] = background

    def fill(left: float, top: float, right: float, bottom: float, color: tuple[int, int, int, int]) -> None:
        x0 = max(0, round(size * left))
        y0 = max(0, round(size * top))
        x1 = min(size, round(size * right))
        y1 = min(size, round(size * bottom))
        for row in range(y0, y1):
            for column in range(x0, x1):
                if _rounded_square_contains(column, row, size):
                    pixels[row][column] = color

    # Three upright volumes and two rails form the small Lattice bookshelf mark.
    fill(0.18, 0.25, 0.34, 0.75, (124, 135, 239, 255))
    fill(0.39, 0.18, 0.58, 0.75, (216, 149, 107, 255))
    fill(0.64, 0.31, 0.80, 0.75, (98, 161, 138, 255))
    fill(0.15, 0.74, 0.84, 0.82, (245, 246, 248, 255))
    fill(0.15, 0.48, 0.84, 0.53, (70, 76, 94, 255))

    return pixels


def _render_dib(size: int) -> bytes:
    """Return a classic 32-bit ICO bitmap understood by Windows PowerShell 5.1.

    PNG-compressed ICO frames render in modern Windows, but the legacy
    ``System.Drawing.Icon.ToBitmap`` used by the installer can reject them.
    A bottom-up BGRA DIB plus its 1-bit transparency mask works consistently in
    both the legacy installer and the modern WPF shell.
    """

    pixels = _render_pixels(size)
    xor_bitmap = bytearray()
    and_mask = bytearray()
    mask_stride = ((size + 31) // 32) * 4

    for row in reversed(pixels):
        for red, green, blue, alpha in row:
            xor_bitmap.extend((blue, green, red, alpha))

    for row in reversed(pixels):
        mask_row = bytearray(mask_stride)
        for x, (_red, _green, _blue, alpha) in enumerate(row):
            if alpha == 0:
                mask_row[x // 8] |= 0x80 >> (x % 8)
        and_mask.extend(mask_row)

    bitmap_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(xor_bitmap),
        0,
        0,
        0,
        0,
    )
    return bitmap_header + bytes(xor_bitmap) + bytes(and_mask)


def build_icon() -> bytes:
    images = [(size, _render_dib(size)) for size in ICON_SIZES]
    offset = 6 + (16 * len(images))
    entries = bytearray()
    payload = bytearray()
    for size, image in images:
        encoded_size = 0 if size == 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                encoded_size,
                encoded_size,
                0,
                0,
                1,
                32,
                len(image),
                offset,
            )
        )
        payload.extend(image)
        offset += len(image)
    return struct.pack("<HHH", 0, 1, len(images)) + bytes(entries) + bytes(payload)


def validate_icon(data: bytes) -> None:
    if len(data) < 6:
        raise ValueError("ICO data is truncated")
    reserved, image_type, count = struct.unpack_from("<HHH", data)
    if reserved != 0 or image_type != 1 or count != len(ICON_SIZES):
        raise ValueError("ICO header is invalid")
    observed_sizes: list[int] = []
    for index in range(count):
        width, height, _colors, _reserved, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + (16 * index)
        )
        decoded_width = 256 if width == 0 else width
        decoded_height = 256 if height == 0 else height
        if decoded_width != decoded_height or planes != 1 or bits != 32:
            raise ValueError("ICO image entry is invalid")
        if offset + length > len(data):
            raise ValueError("ICO image payload is invalid")
        mask_stride = ((decoded_width + 31) // 32) * 4
        expected_length = 40 + decoded_width * decoded_height * 4 + mask_stride * decoded_height
        if length != expected_length:
            raise ValueError("ICO bitmap payload has an invalid length")
        (
            header_size,
            bitmap_width,
            bitmap_height,
            bitmap_planes,
            bitmap_bits,
            compression,
        ) = struct.unpack_from("<IiiHHI", data, offset)
        if (
            header_size != 40
            or bitmap_width != decoded_width
            or bitmap_height != decoded_height * 2
            or bitmap_planes != 1
            or bitmap_bits != 32
            or compression != 0
        ):
            raise ValueError("ICO bitmap payload is invalid")
        observed_sizes.append(decoded_width)
    if tuple(observed_sizes) != ICON_SIZES:
        raise ValueError("ICO sizes are incomplete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    icon = build_icon()
    validate_icon(icon)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_bytes(icon)
    temporary.replace(output)
    print(f"Generated {output} ({len(ICON_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
