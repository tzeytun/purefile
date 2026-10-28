"""Reading and writing the EXIF Orientation tag."""

from __future__ import annotations

import struct

import pytest
from PIL import Image

from purefile.clean.orientation import EXIF_HEADER, minimal_exif, read_orientation


@pytest.mark.parametrize("value", range(1, 9))
def test_minimal_exif_roundtrip(value: int) -> None:
    block = minimal_exif(value)
    assert read_orientation(block) == value
    assert read_orientation(EXIF_HEADER + block) == value


def test_minimal_exif_is_readable_by_pillow() -> None:
    exif = Image.Exif()
    exif.load(EXIF_HEADER + minimal_exif(6))
    assert dict(exif) == {0x0112: 6}


@pytest.mark.parametrize("endian", ["<", ">"])
def test_reads_both_byte_orders(endian: str) -> None:
    exif = Image.Exif()
    exif[0x010F] = "Make"
    exif[0x0112] = 8
    block = exif.tobytes()
    if endian == ">":
        # Pillow writes little-endian; build a big-endian equivalent by hand.
        block = b"MM\x00*" + struct.pack(">IH", 8, 1) + struct.pack(">HHIHH", 0x0112, 3, 1, 8, 0)
    assert read_orientation(block) == 8


@pytest.mark.parametrize(
    "block",
    [
        b"",
        b"not tiff",
        b"II*\x00\xff\xff\x00\x00",  # IFD offset past the end
        b"MM\x00*" + struct.pack(">IH", 8, 1) + struct.pack(">HHIHH", 0x0112, 3, 1, 9, 0),
        b"MM\x00*" + struct.pack(">IH", 8, 1) + struct.pack(">HHIHH", 0x0112, 4, 1, 6, 0),
        b"MM\x00*" + struct.pack(">IH", 8, 1) + struct.pack(">HHIHH", 0x010F, 2, 4, 0, 0),
    ],
    ids=["empty", "garbage", "bad-offset", "out-of-range", "wrong-type", "absent"],
)
def test_invalid_or_missing_orientation(block: bytes) -> None:
    assert read_orientation(block) is None


@pytest.mark.parametrize("value", [0, 9])
def test_minimal_exif_rejects_invalid_values(value: int) -> None:
    with pytest.raises(ValueError):
        minimal_exif(value)
