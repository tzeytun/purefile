"""Minimal ISO base media file format (MP4/MOV/HEIF) box walker.

Metadata boxes are never removed from these files. Removing a box would shift
every following byte and invalidate the absolute offsets stored in ``stco``,
``co64`` and ``iloc``. Instead a box is *neutralized*: its type is overwritten
with ``free`` and its payload is zeroed, in place. Players skip ``free`` boxes,
and every other byte keeps its position.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

C2PA_UUID = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")
XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")

# Boxes whose children are boxes (``meta`` is handled separately).
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"udta", b"edts", b"dinf", b"stbl", b"moof",
              b"traf", b"mvex"}  # fmt: skip

_ZERO_CHUNK = 1 << 20


@dataclass(frozen=True)
class Box:
    """A box located in a file."""

    type: bytes
    offset: int
    size: int
    header_size: int
    usertype: bytes | None
    path: tuple[bytes, ...]
    large: bool = False  # uses a 64-bit size field

    @property
    def payload_offset(self) -> int:
        return self.offset + self.header_size

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def label(self) -> str:
        """Readable path such as ``moov/udta/meta``."""
        names = [t.decode("latin-1") for t in (*self.path, self.type)]
        return "/".join(names)


class BoxError(ValueError):
    """The file is not a well-formed ISO BMFF file."""


def iter_boxes(fh: BinaryIO, start: int, end: int, path: tuple[bytes, ...] = ()) -> Iterator[Box]:
    """Yield the boxes between ``start`` and ``end`` (one nesting level)."""
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(16)
        size, kind = struct.unpack_from(">I4s", header)
        header_size = 8
        large = size == 1
        if large:
            if len(header) < 16:
                raise BoxError("truncated largesize box header")
            (size,) = struct.unpack_from(">Q", header, 8)
            header_size = 16
        elif size == 0:
            size = end - pos
        if size < header_size or pos + size > end:
            raise BoxError(f"invalid size for box {kind!r} at offset {pos}")
        usertype = None
        if kind == b"uuid":
            fh.seek(pos + header_size)
            usertype = fh.read(16)
            header_size += 16
        yield Box(kind, pos, size, header_size, usertype, path, large)
        pos += size


def _meta_children_offset(fh: BinaryIO, box: Box) -> int:
    """Offset of the first child of a ``meta`` box.

    ISO ``meta`` is a FullBox (4 bytes of version/flags before its children),
    QuickTime ``meta`` is not. The two are told apart by checking whether a
    plausible child box header starts right after the box header.
    """
    fh.seek(box.payload_offset + 4)
    if fh.read(4) == b"hdlr":
        return box.payload_offset
    return box.payload_offset + 4


def walk(fh: BinaryIO, size: int, descend: set[bytes] = CONTAINERS) -> Iterator[Box]:
    """Yield every box in the file, depth-first, descending into ``descend`` and ``meta``."""

    def visit(start: int, end: int, path: tuple[bytes, ...]) -> Iterator[Box]:
        for box in iter_boxes(fh, start, end, path):
            yield box
            child_path = (*path, box.type)
            if box.type in descend:
                yield from visit(box.payload_offset, box.end, child_path)
            elif box.type == b"meta":
                yield from visit(_meta_children_offset(fh, box), box.end, child_path)

    yield from visit(0, size, ())


def find(
    path: Path, predicate: Callable[[Box], bool], descend: set[bytes] = CONTAINERS
) -> list[Box]:
    """Return all boxes for which ``predicate(box)`` is true."""
    with path.open("rb") as fh:
        size = path.stat().st_size
        return [box for box in walk(fh, size, descend) if predicate(box)]


def neutralize(path: Path, boxes: list[Box]) -> None:
    """Turn each box into a zero-filled ``free`` box of the same size, in place."""
    with path.open("r+b") as fh:
        for box in boxes:
            fh.seek(box.offset + 4)
            fh.write(b"free")
            # Zero everything after the size fields (a 64-bit size stays intact).
            pos = box.offset + (16 if box.large else 8)
            fh.seek(pos)
            remaining = box.end - pos
            while remaining > 0:
                n = min(remaining, _ZERO_CHUNK)
                fh.write(bytes(n))
                remaining -= n


def is_c2pa(box: Box) -> bool:
    return box.type == b"uuid" and box.usertype == C2PA_UUID


def is_xmp(box: Box) -> bool:
    return (box.type == b"uuid" and box.usertype == XMP_UUID) or box.type == b"XMP_"
