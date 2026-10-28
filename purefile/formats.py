"""Detect file formats from their leading bytes.

The client-supplied file name and MIME type are never trusted; only the
content decides which cleaner runs.
"""

from __future__ import annotations

import struct
from enum import StrEnum
from pathlib import Path


class Format(StrEnum):
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    HEIF = "heif"
    MP4 = "mp4"
    MOV = "mov"

    @property
    def is_video(self) -> bool:
        return self in (Format.MP4, Format.MOV)

    @property
    def extension(self) -> str:
        return {
            Format.JPEG: ".jpg",
            Format.PNG: ".png",
            Format.WEBP: ".webp",
            Format.HEIF: ".heic",
            Format.MP4: ".mp4",
            Format.MOV: ".mov",
        }[self]

    @property
    def mime_type(self) -> str:
        return {
            Format.JPEG: "image/jpeg",
            Format.PNG: "image/png",
            Format.WEBP: "image/webp",
            Format.HEIF: "image/heic",
            Format.MP4: "video/mp4",
            Format.MOV: "video/quicktime",
        }[self]


class UnsupportedFormatError(ValueError):
    """The file is not one of the supported formats."""


# ISO base media "ftyp" brands.
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}
AVIF_BRANDS = {b"avif", b"avis"}
MOV_BRANDS = {b"qt  "}
MP4_BRANDS = {
    b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"mp71",
    b"avc1", b"M4V ", b"M4VH", b"M4VP", b"dash", b"3gp4", b"3gp5", b"3gp6", b"3g2a",
    b"MSNV", b"XAVC", b"f4v ",
}  # fmt: skip
# Legacy QuickTime files may start without an ftyp box.
QUICKTIME_LEADING_BOXES = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}

SNIFF_BYTES = 64


def detect(header: bytes) -> Format:
    """Identify the format from the first bytes of a file.

    Raises:
        UnsupportedFormatError: if the bytes do not match a supported format.
    """
    if header.startswith(b"\xff\xd8\xff"):
        return Format.JPEG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return Format.PNG
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return Format.WEBP
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return _detect_ftyp(header)
    if len(header) >= 8 and header[4:8] in QUICKTIME_LEADING_BOXES:
        return Format.MOV
    raise UnsupportedFormatError("unsupported file type")


def _detect_ftyp(header: bytes) -> Format:
    size = struct.unpack(">I", header[:4])[0]
    end = min(size, len(header)) if size >= 16 else len(header)
    major = header[8:12]
    compatible = {header[i : i + 4] for i in range(16, end - 3, 4)}
    if major in AVIF_BRANDS:
        raise UnsupportedFormatError("AVIF is not supported yet")
    if major in HEIF_BRANDS or (major not in MP4_BRANDS | MOV_BRANDS and compatible & HEIF_BRANDS):
        return Format.HEIF
    if major in MOV_BRANDS:
        return Format.MOV
    if major in MP4_BRANDS or compatible & MP4_BRANDS:
        return Format.MP4
    raise UnsupportedFormatError(f"unsupported ISO media brand {major!r}")


def detect_file(path: Path) -> Format:
    """Identify the format of a file on disk."""
    with path.open("rb") as fh:
        return detect(fh.read(SNIFF_BYTES))
