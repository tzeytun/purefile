"""Format detection from leading bytes."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from purefile.formats import Format, UnsupportedFormatError, detect, detect_file


def ftyp(major: bytes, *compatible: bytes) -> bytes:
    payload = major + b"\x00\x00\x00\x00" + b"".join(compatible)
    return struct.pack(">I", 8 + len(payload)) + b"ftyp" + payload


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", Format.JPEG),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", Format.PNG),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", Format.WEBP),
        (ftyp(b"heic", b"mif1", b"heic"), Format.HEIF),
        (ftyp(b"mif1", b"heic"), Format.HEIF),
        (ftyp(b"isom", b"isom", b"avc1"), Format.MP4),
        (ftyp(b"mp42", b"mp41"), Format.MP4),
        (ftyp(b"XYZW", b"isom"), Format.MP4),
        (ftyp(b"qt  ", b"qt  "), Format.MOV),
        (b"\x00\x00\x00\x08wide\x00\x00\x00\x00mdat", Format.MOV),
        (b"\x00\x00\x01\x00moov", Format.MOV),
    ],
)
def test_detects_supported_formats(header: bytes, expected: Format) -> None:
    assert detect(header) is expected


@pytest.mark.parametrize(
    "header",
    [
        b"GIF89a",
        b"%PDF-1.7",
        b"RIFF\x10\x00\x00\x00AVI LIST",
        ftyp(b"avif", b"mif1", b"avif"),
        ftyp(b"crx ", b"crx "),
        b"",
    ],
    ids=["gif", "pdf", "avi", "avif", "unknown-brand", "empty"],
)
def test_rejects_unsupported(header: bytes) -> None:
    with pytest.raises(UnsupportedFormatError):
        detect(header)


def test_format_properties() -> None:
    assert Format.MP4.is_video and Format.MOV.is_video
    assert not Format.HEIF.is_video
    assert Format.HEIF.extension == ".heic"
    assert Format.JPEG.mime_type == "image/jpeg"
    assert {f.extension for f in Format} == {".jpg", ".png", ".webp", ".heic", ".mp4", ".mov"}


def test_detect_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(100))
    assert detect_file(path) is Format.PNG
