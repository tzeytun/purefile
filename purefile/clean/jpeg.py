"""Lossless JPEG metadata removal.

The file is walked marker by marker. Metadata segments are dropped and every
other segment, including the entropy-coded scan data, is copied byte-for-byte,
so the decoded pixels are identical.

Kept: APP0 JFIF, APP2 ICC_PROFILE, APP14 Adobe (needed for CMYK/YCCK color
transforms), all coding segments (DQT, DHT, SOFn, DRI, SOS, ...).
Removed: APP1 EXIF/XMP, APP11 JUMBF (C2PA), APP13 IPTC, all other APPn, COM, and
anything after EOI (MPF secondary images, Ultra HDR gain maps, vendor trailers).
If EXIF carried a non-default Orientation, a minimal EXIF block with only that
tag is written back so the photo still displays upright.
"""

from __future__ import annotations

import struct

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, Changes, CleanError
from purefile.clean.orientation import EXIF_HEADER, minimal_exif, read_orientation

SOI = 0xD8
EOI = 0xD9
SOS = 0xDA
COM = 0xFE
APP0 = 0xE0
APP15 = 0xEF
# Markers without a length field.
STANDALONE = {0x01, *range(0xD0, 0xD8)}

# APPn payload signatures, used to decide what to keep and to name what is removed.
JFIF = b"JFIF\x00"
ICC_PROFILE = b"ICC_PROFILE\x00"
ADOBE = b"Adobe"
XMP = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXTENDED = b"http://ns.adobe.com/xmp/extension/\x00"


def _describe(marker: int, payload: bytes) -> str:
    """Human-readable name of a removed segment."""
    if marker == COM:
        return "JPEG comment"
    n = marker - APP0
    if n == 1:
        if payload.startswith(b"Exif\x00"):
            return "EXIF"
        if payload.startswith(XMP) or payload.startswith(XMP_EXTENDED):
            return "XMP"
    if n == 11:
        return "C2PA / JUMBF"
    if n == 13:
        return "IPTC / Photoshop"
    if n == 2 and payload.startswith(b"MPF\x00"):
        return "Multi-picture index (MPF)"
    if n == 0 and payload.startswith(b"JFXX\x00"):
        return "JFIF thumbnail"
    return f"APP{n} segment"


def _keep_app(marker: int, payload: bytes) -> bool:
    n = marker - APP0
    return (
        (n == 0 and payload.startswith(JFIF))
        or (n == 2 and payload.startswith(ICC_PROFILE))
        or (n == 14 and payload.startswith(ADOBE))
    )


def _scan_end(data: bytes, pos: int) -> int:
    """Return the offset of the first marker after entropy-coded data starting at ``pos``."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos == -1 or pos + 1 >= len(data):
            return len(data)
        nxt = data[pos + 1]
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7 or nxt == 0xFF:
            # Stuffed byte, restart marker, or fill byte: still inside the scan.
            pos += 1 if nxt == 0xFF else 2
            continue
        return pos


def strip_jpeg(data: bytes) -> tuple[bytes, Changes]:
    """Return a copy of ``data`` without metadata, plus a summary of the changes."""
    if not data.startswith(b"\xff\xd8"):
        raise CleanError("not a JPEG file")
    changes = Changes()
    orientation: int | None = None
    # Segments are collected first so the minimal EXIF block can be placed
    # right after SOI/JFIF regardless of where the original EXIF appeared.
    jfif: bytes = b""
    body: list[bytes] = []
    pos = 2
    saw_eoi = False

    while pos < len(data):
        if data[pos] != 0xFF:
            # Stray bytes between segments are ignored by decoders; do the same.
            pos = data.find(b"\xff", pos)
            if pos == -1:
                break
        while pos < len(data) and data[pos] == 0xFF:  # skip fill bytes
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1

        if marker == EOI:
            saw_eoi = True
            break
        if marker in STANDALONE:
            body.append(bytes((0xFF, marker)))
            continue
        if pos + 2 > len(data):
            raise CleanError("corrupt JPEG: truncated segment header")
        (length,) = struct.unpack_from(">H", data, pos)
        if length < 2 or pos + length > len(data):
            raise CleanError("corrupt JPEG: invalid segment length")
        segment = data[pos - 2 : pos + length]
        payload = data[pos + 2 : pos + length]
        pos += length

        if APP0 <= marker <= APP15 or marker == COM:
            if marker == APP0 + 1 and payload.startswith(EXIF_HEADER) and orientation is None:
                orientation = read_orientation(payload)
            if marker != COM and _keep_app(marker, payload):
                if marker == APP0 and not jfif and not body:
                    jfif = segment
                else:
                    body.append(segment)
                if marker == APP0 + 2:
                    changes.keep(KEPT_ICC)
            else:
                changes.remove(_describe(marker, payload))
            continue

        body.append(segment)
        if marker == SOS:
            end = _scan_end(data, pos)
            body.append(data[pos:end])
            pos = end

    out = bytearray(b"\xff\xd8")
    out += jfif
    if orientation is not None and orientation != 1:
        exif = EXIF_HEADER + minimal_exif(orientation)
        out += struct.pack(">BBH", 0xFF, APP0 + 1, len(exif) + 2) + exif
        changes.keep(KEPT_ORIENTATION)
    for part in body:
        out += part
    if saw_eoi:
        out += b"\xff\xd9"
        if pos < len(data):
            changes.remove("Data after end of image (embedded previews, gain maps)")
    return bytes(out), changes
