"""JPEG cleaner: metadata segments go, coded image data stays byte-identical."""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image, ImageCms

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, CleanError
from purefile.clean.jpeg import strip_jpeg
from purefile.clean.orientation import read_orientation
from tests.conftest import pixels

XMP = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>secret</x:xmpmeta>"


def segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def exif_block(orientation: int | None = None, **tags: str) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = tags.get("make", "Secret Camera Co")
    exif[0x0131] = tags.get("software", "Secret Editor")
    if orientation is not None:
        exif[0x0112] = orientation
    return exif.tobytes()  # starts with b"Exif\0\0"


def encode(mode: str = "RGB", **save_args: object) -> bytes:
    img = Image.new(mode, (64, 48))
    for x in range(64):
        for y in range(48):
            value = (x * 4, y * 5, (x + y) * 2, 255)[: len(mode)]
            img.putpixel((x, y), value if len(mode) > 1 else value[0])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, **save_args)
    return buf.getvalue()


def inject(jpeg: bytes, *segments: bytes) -> bytes:
    """Insert segments right after SOI."""
    return jpeg[:2] + b"".join(segments) + jpeg[2:]


def markers(jpeg: bytes) -> list[tuple[int, bytes]]:
    """(marker, payload) for every segment up to the first SOS."""
    out = []
    pos = 2
    while True:
        marker = jpeg[pos + 1]
        (length,) = struct.unpack_from(">H", jpeg, pos + 2)
        out.append((marker, jpeg[pos + 4 : pos + 2 + length]))
        if marker == 0xDA:
            return out
        pos += 2 + length


def coded_data(jpeg: bytes) -> bytes:
    """Everything from the first SOS up to and including EOI."""
    start = jpeg.index(b"\xff\xda")
    return jpeg[start : jpeg.index(b"\xff\xd9", start) + 2]


ALL_METADATA = (
    segment(0xE1, exif_block()),
    segment(0xE1, XMP),
    segment(0xED, b"Photoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x05\x1c\x02\x50\x00\x01X"),
    segment(0xEB, b"JP\x00\x11\x00\x00\x00\x01jumbc2pa"),
    segment(0xFE, b"a comment"),
    segment(0xE2, b"MPF\x00II*\x00"),
    segment(0xEC, b"Ducky\x00\x01"),
)


def test_removes_every_metadata_segment() -> None:
    original = encode()
    cleaned, changes = strip_jpeg(inject(original, *ALL_METADATA))
    kinds = [m for m, _ in markers(cleaned)]
    assert not {0xE1, 0xEB, 0xED, 0xEC, 0xFE} & set(kinds)
    assert all(not payload.startswith(b"MPF") for m, payload in markers(cleaned) if m == 0xE2)
    assert b"Secret" not in cleaned and b"secret" not in cleaned and b"jumb" not in cleaned
    assert set(changes.removed) == {
        "EXIF", "XMP", "IPTC / Photoshop", "C2PA / JUMBF", "JPEG comment",
        "Multi-picture index (MPF)", "APP12 segment",
    }  # fmt: skip
    assert cleaned == original  # nothing else was touched


@pytest.mark.filterwarnings("ignore:Image appears to be a malformed MPO file")
@pytest.mark.parametrize(
    ("mode", "save_args"),
    [
        ("RGB", {}),
        ("RGB", {"progressive": True}),
        ("RGB", {"restart_marker_blocks": 1}),
        ("RGB", {"subsampling": 0}),
        ("L", {}),
        ("CMYK", {}),
    ],
    ids=["baseline", "progressive", "restart-markers", "444", "grayscale", "cmyk"],
)
def test_pixels_and_coded_data_unchanged(mode: str, save_args: dict[str, object]) -> None:
    original = inject(encode(mode, **save_args), *ALL_METADATA)
    cleaned, _ = strip_jpeg(original)
    assert coded_data(cleaned) == coded_data(original)
    assert pixels(cleaned) == pixels(original)


def test_keeps_adobe_segment_for_cmyk() -> None:
    cleaned, _ = strip_jpeg(encode("CMYK"))
    assert any(m == 0xEE and p.startswith(b"Adobe") for m, p in markers(cleaned))


def test_keeps_icc_profile() -> None:
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    original = inject(encode(icc_profile=icc), segment(0xE1, exif_block()))
    cleaned, changes = strip_jpeg(original)
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.info["icc_profile"] == icc
    assert KEPT_ICC in changes.kept


def test_keeps_large_multi_segment_icc_profile() -> None:
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes() + bytes(150_000)
    cleaned, _ = strip_jpeg(encode(icc_profile=icc))
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.info["icc_profile"] == icc


@pytest.mark.parametrize("orientation", [3, 6, 8])
def test_orientation_is_preserved_alone(orientation: int) -> None:
    original = inject(encode(), segment(0xE1, exif_block(orientation)))
    cleaned, changes = strip_jpeg(original)
    app1 = [p for m, p in markers(cleaned) if m == 0xE1]
    assert len(app1) == 1
    assert read_orientation(app1[0]) == orientation
    assert b"Secret" not in cleaned
    with Image.open(io.BytesIO(cleaned)) as img:
        exif = img.getexif()
        assert dict(exif) == {0x0112: orientation}
    assert KEPT_ORIENTATION in changes.kept
    # APP0 JFIF must stay first, the minimal EXIF right after it.
    assert [m for m, _ in markers(cleaned)][:2] == [0xE0, 0xE1]


def test_default_orientation_is_not_written_back() -> None:
    cleaned, changes = strip_jpeg(inject(encode(), segment(0xE1, exif_block(1))))
    assert all(m != 0xE1 for m, _ in markers(cleaned))
    assert KEPT_ORIENTATION not in changes.kept


def test_data_after_eoi_is_removed() -> None:
    original = encode()
    trailer = b"\xff\xd8\xff\xe1secondary image with its own EXIF\xff\xd9"
    cleaned, changes = strip_jpeg(original + trailer)
    assert cleaned == original
    assert any("after end of image" in r for r in changes.removed)


def test_stray_bytes_between_segments_are_skipped() -> None:
    original = encode()
    dirty = original[:2] + b"\x00\x00" + segment(0xE1, exif_block()) + original[2:]
    cleaned, _ = strip_jpeg(dirty)
    assert cleaned == original


def test_fill_bytes_before_markers_are_tolerated() -> None:
    original = encode()
    padded = original[:2] + b"\xff\xff" + original[2:]
    cleaned, _ = strip_jpeg(padded)
    assert pixels(cleaned) == pixels(original)


def test_truncated_file_keeps_available_data() -> None:
    original = encode()
    truncated = original[: len(original) - 2]  # no EOI
    cleaned, _ = strip_jpeg(truncated)
    assert cleaned == truncated


def test_rejects_non_jpeg() -> None:
    with pytest.raises(CleanError):
        strip_jpeg(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    "bad_segment",
    [b"\xff\xe1\x00\x01", b"\xff\xe1\xff\xff", b"\xff\xe1"],
    ids=["length-too-small", "length-past-end", "truncated-header"],
)
def test_rejects_corrupt_segments(bad_segment: bytes) -> None:
    with pytest.raises(CleanError):
        strip_jpeg(b"\xff\xd8" + bad_segment)
