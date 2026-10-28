"""Read and write the EXIF Orientation tag.

Cameras often store pixels unrotated and rely on EXIF Orientation to display
them upright. Dropping it would turn portrait photos sideways, so cleaners keep
exactly one tag: a minimal EXIF block that contains only Orientation.
"""

from __future__ import annotations

import struct

ORIENTATION_TAG = 0x0112
SHORT = 3
EXIF_HEADER = b"Exif\x00\x00"


def read_orientation(exif: bytes) -> int | None:
    """Return the Orientation value (1-8) from a TIFF/EXIF block, if present and valid."""
    if exif.startswith(EXIF_HEADER):
        exif = exif[len(EXIF_HEADER) :]
    if exif[:4] == b"II*\x00":
        endian = "<"
    elif exif[:4] == b"MM\x00*":
        endian = ">"
    else:
        return None
    try:
        (ifd_offset,) = struct.unpack_from(endian + "I", exif, 4)
        (count,) = struct.unpack_from(endian + "H", exif, ifd_offset)
        for i in range(count):
            entry = ifd_offset + 2 + i * 12
            tag, typ, n = struct.unpack_from(endian + "HHI", exif, entry)
            if tag == ORIENTATION_TAG and typ == SHORT and n == 1:
                (value,) = struct.unpack_from(endian + "H", exif, entry + 8)
                return value if 1 <= value <= 8 else None
    except struct.error:
        return None
    return None


def minimal_exif(orientation: int) -> bytes:
    """Build a TIFF block with a single IFD0 entry: Orientation."""
    if not 1 <= orientation <= 8:
        raise ValueError(f"invalid orientation {orientation}")
    header = b"MM\x00*" + struct.pack(">I", 8)
    ifd = struct.pack(">H", 1) + struct.pack(">HHIHH", ORIENTATION_TAG, SHORT, 1, orientation, 0)
    return header + ifd + struct.pack(">I", 0)
