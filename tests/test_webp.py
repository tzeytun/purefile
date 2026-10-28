"""WebP cleaner: metadata chunks go, bitstream chunks stay byte-identical."""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image, ImageCms

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, CleanError
from purefile.clean.orientation import read_orientation
from purefile.clean.webp import FLAG_EXIF, FLAG_XMP, strip_webp
from tests.conftest import pixels

XMP = b"<x:xmpmeta>secret</x:xmpmeta>"
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def chunks(webp: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], 12
    while pos + 8 <= len(webp):
        fourcc, size = struct.unpack_from("<4sI", webp, pos)
        out.append((fourcc, webp[pos + 8 : pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return out


def image(mode: str = "RGB") -> Image.Image:
    img = Image.new(mode, (48, 32))
    img.putdata(
        [((x * 5) % 256, (y * 7) % 256, 90, 180)[: len(mode)] for y in range(32) for x in range(48)]
    )
    return img


def encode(orientation: int | None = 6, *, lossless: bool = False, mode: str = "RGB") -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Secret Camera Co"
    if orientation is not None:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    image(mode).save(
        buf, "WEBP", lossless=lossless, quality=80, exif=exif, xmp=XMP, icc_profile=ICC
    )
    return buf.getvalue()


def bitstream(webp: bytes) -> list[tuple[bytes, bytes]]:
    return [(k, p) for k, p in chunks(webp) if k in {b"VP8 ", b"VP8L", b"ALPH", b"ANMF", b"ANIM"}]


@pytest.mark.parametrize(
    ("lossless", "mode"),
    [(False, "RGB"), (True, "RGB"), (False, "RGBA")],
    ids=["lossy", "lossless", "alpha"],
)
def test_removes_metadata_and_keeps_bitstream(lossless: bool, mode: str) -> None:
    original = encode(lossless=lossless, mode=mode)
    cleaned, changes = strip_webp(original)
    kinds = [k for k, _ in chunks(cleaned)]
    assert b"XMP " not in kinds
    assert b"secret" not in cleaned.lower()
    assert bitstream(cleaned) == bitstream(original)
    assert pixels(cleaned) == pixels(original)
    assert {"EXIF", "XMP"} <= set(changes.removed)


def test_riff_size_and_flags_are_consistent() -> None:
    cleaned, _ = strip_webp(encode(orientation=None))
    (riff_size,) = struct.unpack_from("<I", cleaned, 4)
    assert riff_size == len(cleaned) - 8
    vp8x = dict(chunks(cleaned))[b"VP8X"]
    assert not vp8x[0] & (FLAG_EXIF | FLAG_XMP)
    assert b"EXIF" not in dict(chunks(cleaned))


def test_keeps_icc_profile() -> None:
    cleaned, changes = strip_webp(encode())
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.info["icc_profile"] == ICC
    assert KEPT_ICC in changes.kept


def test_orientation_is_preserved_alone() -> None:
    cleaned, changes = strip_webp(encode(orientation=6))
    exif = dict(chunks(cleaned))[b"EXIF"]
    assert read_orientation(exif) == 6
    assert dict(chunks(cleaned))[b"VP8X"][0] & FLAG_EXIF
    assert KEPT_ORIENTATION in changes.kept


def test_removes_c2pa_and_unknown_chunks() -> None:
    original = encode(orientation=None)
    extra = (
        b"C2PA" + struct.pack("<I", 9) + b"jumbc2pa!\x00" + b"ZZZZ" + struct.pack("<I", 2) + b"hi"
    )
    body = original[12:] + extra
    tampered = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body
    cleaned, changes = strip_webp(tampered)
    assert b"jumb" not in cleaned
    assert {"C2PA / JUMBF", "ZZZZ chunk"} <= set(changes.removed)


def test_animated_webp_keeps_frames() -> None:
    frames = [image(), image().rotate(90)]
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "Secret Camera Co"
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100, exif=exif)
    cleaned, _ = strip_webp(buf.getvalue())
    assert bitstream(cleaned) == bitstream(buf.getvalue())
    assert b"Secret" not in cleaned


def test_simple_format_is_unchanged() -> None:
    buf = io.BytesIO()
    image().save(buf, "WEBP", quality=80)
    cleaned, changes = strip_webp(buf.getvalue())
    assert cleaned == buf.getvalue()
    assert changes.removed == []


def test_data_after_riff_is_removed() -> None:
    original = encode(orientation=None)
    cleaned, changes = strip_webp(original + b"secret trailer")
    assert b"secret" not in cleaned
    assert "Data after end of image" in changes.removed


def test_rejects_non_webp() -> None:
    with pytest.raises(CleanError):
        strip_webp(b"RIFF\x00\x00\x00\x00AVI ")


def test_rejects_truncated_chunk() -> None:
    bad = b"RIFF" + struct.pack("<I", 100) + b"WEBP" + b"VP8 " + struct.pack("<I", 50) + b"\x00" * 4
    with pytest.raises(CleanError, match="truncated"):
        strip_webp(bad)
