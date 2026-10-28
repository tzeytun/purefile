"""Lossless WebP metadata removal.

WebP is a RIFF container. Image chunks (VP8, VP8L, ALPH, ANIM, ANMF) are copied
verbatim. EXIF, XMP and C2PA chunks are dropped, the VP8X feature flags are
updated to match, and the RIFF size is recomputed. The ICC profile (ICCP) is kept.
"""

from __future__ import annotations

import struct

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, Changes, CleanError
from purefile.clean.orientation import minimal_exif, read_orientation

KEEP = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}
DESCRIPTIONS = {b"EXIF": "EXIF", b"XMP ": "XMP", b"C2PA": "C2PA / JUMBF"}

FLAG_EXIF = 0x08
FLAG_XMP = 0x04


def _chunk(fourcc: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) % 2 else b""
    return fourcc + struct.pack("<I", len(payload)) + payload + pad


def strip_webp(data: bytes) -> tuple[bytes, Changes]:
    """Return a copy of ``data`` without metadata, plus a summary of the changes."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise CleanError("not a WebP file")
    changes = Changes()
    (riff_size,) = struct.unpack_from("<I", data, 4)
    end = min(len(data), 8 + riff_size)
    chunks: list[tuple[bytes, bytes]] = []
    orientation: int | None = None
    pos = 12
    while pos + 8 <= end:
        fourcc, size = struct.unpack_from("<4sI", data, pos)
        payload = data[pos + 8 : pos + 8 + size]
        if len(payload) != size:
            raise CleanError("corrupt WebP: truncated chunk")
        pos += 8 + size + (size & 1)
        if fourcc in KEEP:
            chunks.append((fourcc, payload))
            if fourcc == b"ICCP":
                changes.keep(KEPT_ICC)
        else:
            if fourcc == b"EXIF" and orientation is None:
                orientation = read_orientation(payload)
            changes.remove(DESCRIPTIONS.get(fourcc, f"{fourcc.decode('latin-1').strip()} chunk"))

    keep_orientation = orientation is not None and orientation != 1
    has_vp8x = bool(chunks) and chunks[0][0] == b"VP8X"
    if has_vp8x:
        flags = chunks[0][1][0] & ~(FLAG_EXIF | FLAG_XMP)
        if keep_orientation:
            flags |= FLAG_EXIF
        chunks[0] = (b"VP8X", bytes([flags]) + chunks[0][1][1:])
    if keep_orientation and has_vp8x and orientation is not None:
        # The spec places EXIF after the image data.
        chunks.append((b"EXIF", minimal_exif(orientation)))
        changes.keep(KEPT_ORIENTATION)

    body = b"".join(_chunk(fourcc, payload) for fourcc, payload in chunks)
    if end < len(data):
        changes.remove("Data after end of image")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body, changes
