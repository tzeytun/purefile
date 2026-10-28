"""Lossless PNG metadata removal.

Chunks are copied verbatim (including their CRCs) unless they carry metadata.
Critical chunks (IHDR, PLTE, IDAT, IEND) are never touched, so the decoded
pixels are identical.

Kept ancillary chunks are limited to an allow-list of rendering-relevant ones
(color management, transparency, physical size, animation). Everything else is
dropped: text (tEXt/iTXt/zTXt), eXIf, C2PA (caBX), timestamps (tIME) and any
unknown ancillary chunk, which decoders are required to ignore anyway.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, Changes, CleanError
from purefile.clean.orientation import minimal_exif, read_orientation

SIGNATURE = b"\x89PNG\r\n\x1a\n"

CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
KEEP_ANCILLARY = {
    # Color management and HDR
    b"iCCP", b"sRGB", b"gAMA", b"cHRM", b"cICP", b"mDCV", b"mDCv", b"cLLI", b"cLLi", b"sBIT",
    # Transparency, background, palette helpers
    b"tRNS", b"bKGD", b"hIST", b"sPLT",
    # Physical pixel size and offsets
    b"pHYs", b"oFFs", b"sCAL", b"pCAL",
    # Animation (APNG)
    b"acTL", b"fcTL", b"fdAT",
}  # fmt: skip

DESCRIPTIONS = {
    b"tEXt": "Text chunks",
    b"iTXt": "Text chunks",
    b"zTXt": "Text chunks",
    b"eXIf": "EXIF",
    b"caBX": "C2PA / JUMBF",
    b"tIME": "Modification time",
}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes, bytes]]:
    """Yield ``(type, payload, raw_chunk)`` up to and including IEND."""
    pos = len(SIGNATURE)
    while pos + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        end = pos + 12 + length
        if end > len(data):
            raise CleanError("corrupt PNG: truncated chunk")
        yield kind, data[pos + 8 : pos + 8 + length], data[pos:end]
        pos = end
        if kind == b"IEND":
            return
    raise CleanError("corrupt PNG: missing IEND")


def strip_png(data: bytes) -> tuple[bytes, Changes]:
    """Return a copy of ``data`` without metadata, plus a summary of the changes."""
    if not data.startswith(SIGNATURE):
        raise CleanError("not a PNG file")
    changes = Changes()
    # Some writers put eXIf after IDAT, so look for orientation up front.
    orientation = next(
        (read_orientation(payload) for kind, payload, _ in _chunks(data) if kind == b"eXIf"),
        None,
    )
    out = bytearray(SIGNATURE)
    consumed = len(SIGNATURE)
    for kind, _payload, chunk in _chunks(data):
        consumed += len(chunk)
        if kind == b"IDAT" and orientation is not None and orientation != 1:
            # A minimal eXIf goes right before the first IDAT, as the spec requires.
            out += _chunk(b"eXIf", minimal_exif(orientation))
            changes.keep(KEPT_ORIENTATION)
            orientation = None
        if kind in CRITICAL or kind in KEEP_ANCILLARY:
            out += chunk
            if kind == b"iCCP":
                changes.keep(KEPT_ICC)
        else:
            changes.remove(DESCRIPTIONS.get(kind, f"{kind.decode('latin-1')} chunk"))
    if consumed < len(data):
        changes.remove("Data after end of image")
    return bytes(out), changes
