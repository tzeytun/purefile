"""PNG cleaner: metadata chunks go, image chunks stay byte-identical."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo

from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION, CleanError
from purefile.clean.orientation import read_orientation
from purefile.clean.png import SIGNATURE, strip_png
from tests.conftest import pixels


def chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], len(SIGNATURE)
    while pos < len(png):
        length, kind = struct.unpack_from(">I4s", png, pos)
        out.append((kind, png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def idat(png: bytes) -> bytes:
    return b"".join(payload for kind, payload in chunks(png) if kind == b"IDAT")


def encode(
    mode: str = "RGBA", *, exif_orientation: int | None = None, **save_args: object
) -> bytes:
    img = Image.new(mode, (40, 30))
    bands = len(img.getbands())
    values = [
        ((x * 6) % 256, (y * 8) % 256, 128, 200)[:bands] for y in range(30) for x in range(40)
    ]
    img.putdata([v[0] for v in values] if bands == 1 else values)
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        exif[0x010F] = "Secret Camera Co"
        save_args["exif"] = exif
    buf = io.BytesIO()
    img.save(buf, "PNG", **save_args)
    return buf.getvalue()


def with_metadata() -> bytes:
    info = PngInfo()
    info.add_text("parameters", "secret prompt, Steps: 30")
    info.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta>secret</x:xmpmeta>")
    info.add_text("Comment", "secret compressed", zip=True)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    png = encode(pnginfo=info, icc_profile=icc, exif_orientation=1)
    # Append chunks Pillow cannot write: tIME, caBX (C2PA) and an unknown private chunk.
    extra = (
        chunk(b"tIME", b"\x07\xe8\x05\x11\x0e\x20\x09")
        + chunk(b"caBX", b"jumbc2pa secret manifest")
        + chunk(b"prVt", b"secret vendor data")
    )
    iend = png.rindex(b"IEND") - 4
    return png[:iend] + extra + png[iend:]


def test_removes_every_metadata_chunk() -> None:
    original = with_metadata()
    cleaned, changes = strip_png(original)
    kinds = [k for k, _ in chunks(cleaned)]
    assert not {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME", b"caBX", b"prVt"} & set(kinds)
    assert b"secret" not in cleaned.lower()
    assert {"Text chunks", "EXIF", "Modification time", "C2PA / JUMBF", "prVt chunk"} <= set(
        changes.removed
    )


def test_pixels_and_image_data_unchanged() -> None:
    original = with_metadata()
    cleaned, _ = strip_png(original)
    assert idat(cleaned) == idat(original)
    assert pixels(cleaned) == pixels(original)


def test_output_is_a_valid_png() -> None:
    cleaned, _ = strip_png(with_metadata())
    with Image.open(io.BytesIO(cleaned)) as img:
        img.verify()  # checks chunk CRCs


def test_keeps_icc_and_rendering_chunks() -> None:
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    original = encode(icc_profile=icc, dpi=(300, 300))
    cleaned, changes = strip_png(original)
    assert cleaned == original
    assert KEPT_ICC in changes.kept
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.info["icc_profile"] == icc


def test_keeps_palette_and_transparency() -> None:
    original = encode("P", transparency=0)
    cleaned, _ = strip_png(original)
    assert cleaned == original


def test_keeps_animation_chunks() -> None:
    frames = [Image.new("RGB", (8, 8), c) for c in ("red", "green", "blue")]
    buf = io.BytesIO()
    frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:], duration=100)
    cleaned, _ = strip_png(buf.getvalue())
    assert cleaned == buf.getvalue()


def test_orientation_is_preserved_alone() -> None:
    cleaned, changes = strip_png(encode(exif_orientation=6))
    exif_chunks = [p for k, p in chunks(cleaned) if k == b"eXIf"]
    assert len(exif_chunks) == 1
    assert read_orientation(exif_chunks[0]) == 6
    assert b"Secret" not in cleaned
    kinds = [k for k, _ in chunks(cleaned)]
    assert kinds.index(b"eXIf") < kinds.index(b"IDAT")
    assert KEPT_ORIENTATION in changes.kept


def test_orientation_found_in_exif_after_idat() -> None:
    plain = encode()
    exif = Image.Exif()
    exif[0x0112] = 8
    late = chunk(b"eXIf", exif.tobytes()[6:])  # PNG eXIf has no "Exif\0\0" prefix
    iend = plain.rindex(b"IEND") - 4
    cleaned, _ = strip_png(plain[:iend] + late + plain[iend:])
    kinds = [k for k, _ in chunks(cleaned)]
    assert kinds.count(b"eXIf") == 1
    assert kinds.index(b"eXIf") < kinds.index(b"IDAT")


def test_data_after_iend_is_removed() -> None:
    original = encode()
    cleaned, changes = strip_png(original + b"secret trailer")
    assert cleaned == original
    assert "Data after end of image" in changes.removed


def test_rejects_non_png() -> None:
    with pytest.raises(CleanError):
        strip_png(b"\xff\xd8\xff")


def test_rejects_missing_iend() -> None:
    original = encode()
    with pytest.raises(CleanError, match="IEND"):
        strip_png(original[: original.rindex(b"IEND") - 4])


def test_rejects_truncated_chunk() -> None:
    with pytest.raises(CleanError, match="truncated"):
        strip_png(SIGNATURE + struct.pack(">I", 100) + b"IHDR" + b"\x00" * 10)
