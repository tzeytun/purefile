"""ISO BMFF box walking and in-place neutralization."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from purefile.clean import isobmff
from purefile.clean.isobmff import C2PA_UUID, XMP_UUID, BoxError


def box(kind: bytes, payload: bytes = b"", *, large: bool = False) -> bytes:
    if large:
        return struct.pack(">I", 1) + kind + struct.pack(">Q", 16 + len(payload)) + payload
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def uuid_box(usertype: bytes, payload: bytes) -> bytes:
    return box(b"uuid", usertype + payload)


def sample_file() -> bytes:
    """ftyp, C2PA uuid, moov (with udta/meta/XMP_ and trak/udta), large mdat."""
    qt_meta = box(b"meta", box(b"hdlr", bytes(25)) + box(b"keys", b"secret keys"))
    iso_meta = box(
        b"meta", b"\x00\x00\x00\x00" + box(b"hdlr", bytes(25)) + box(b"XMP_", b"secret xmp")
    )
    moov = box(
        b"moov",
        box(b"mvhd", bytes(100))
        + box(b"trak", box(b"tkhd", bytes(84)) + box(b"udta", box(b"\xa9xyz", b"+41.0+028.9/")))
        + box(b"udta", iso_meta)
        + qt_meta,
    )
    return (
        box(b"ftyp", b"isom\x00\x00\x00\x00isom")
        + uuid_box(C2PA_UUID, b"jumbc2pa secret manifest")
        + moov
        + uuid_box(XMP_UUID, b"<x:xmpmeta>secret</x:xmpmeta>")
        + box(b"mdat", b"\x01\x02\x03" * 10, large=True)
    )


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "sample.mp4"
    path.write_bytes(sample_file())
    return path


def test_walks_nested_boxes(sample: Path) -> None:
    labels = [b.label for b in isobmff.find(sample, lambda b: True)]
    assert labels == [
        "ftyp", "uuid", "moov", "moov/mvhd", "moov/trak", "moov/trak/tkhd", "moov/trak/udta",
        "moov/trak/udta/\xa9xyz", "moov/udta", "moov/udta/meta", "moov/udta/meta/hdlr",
        "moov/udta/meta/XMP_", "moov/meta", "moov/meta/hdlr", "moov/meta/keys", "uuid", "mdat",
    ]  # fmt: skip


def test_identifies_c2pa_and_xmp(sample: Path) -> None:
    assert [b.offset for b in isobmff.find(sample, isobmff.is_c2pa)] == [20]
    xmp = isobmff.find(sample, isobmff.is_xmp)
    assert sorted(b.label for b in xmp) == ["moov/udta/meta/XMP_", "uuid"]


def test_large_box_header(sample: Path) -> None:
    (mdat,) = isobmff.find(sample, lambda b: b.type == b"mdat")
    assert mdat.large and mdat.header_size == 16 and mdat.size == 46


def test_neutralize_keeps_size_and_offsets(sample: Path) -> None:
    before = sample.read_bytes()
    targets = isobmff.find(sample, lambda b: isobmff.is_c2pa(b) or isobmff.is_xmp(b))
    isobmff.neutralize(sample, targets)
    after = sample.read_bytes()
    assert len(after) == len(before)
    assert b"secret xmp" not in after and b"jumb" not in after and b"xmpmeta" not in after
    for target in targets:
        assert after[target.offset : target.offset + 4] == before[target.offset : target.offset + 4]
        assert after[target.offset + 4 : target.offset + 8] == b"free"
        assert after[target.offset + 8 : target.end] == bytes(target.size - 8)
    # Untouched regions are byte-identical (e.g. the media data).
    (mdat,) = isobmff.find(sample, lambda b: b.type == b"mdat")
    assert after[mdat.offset :] == before[mdat.offset :]
    labels = [b.label for b in isobmff.find(sample, lambda b: True)]
    assert "moov/udta/meta/free" in labels


def test_neutralize_large_box_keeps_64bit_size(tmp_path: Path) -> None:
    path = tmp_path / "large.mp4"
    path.write_bytes(box(b"ftyp", b"isom") + box(b"XMP_", b"secret", large=True))
    (target,) = isobmff.find(path, isobmff.is_xmp)
    isobmff.neutralize(path, [target])
    data = path.read_bytes()
    assert data[target.offset + 4 : target.offset + 8] == b"free"
    assert struct.unpack_from(">Q", data, target.offset + 8)[0] == target.size
    assert b"secret" not in data


def test_size_zero_extends_to_end(tmp_path: Path) -> None:
    path = tmp_path / "zero.mp4"
    path.write_bytes(box(b"ftyp", b"isom") + struct.pack(">I", 0) + b"mdat" + bytes(50))
    (mdat,) = isobmff.find(path, lambda b: b.type == b"mdat")
    assert mdat.end == path.stat().st_size


@pytest.mark.parametrize(
    "data",
    [
        struct.pack(">I", 4) + b"ftyp",  # smaller than its header
        struct.pack(">I", 100) + b"ftyp" + bytes(8),  # past the end of the file
        struct.pack(">I", 1) + b"mdat" + b"\x00\x00",  # truncated 64-bit size
    ],
    ids=["too-small", "past-end", "truncated-largesize"],
)
def test_rejects_malformed_boxes(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(data)
    with pytest.raises(BoxError):
        isobmff.find(path, lambda b: True)
