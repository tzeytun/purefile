"""Format-specific metadata removal. Every cleaner is lossless by construction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from purefile.clean.base import Changes, CleanError
from purefile.clean.heif import strip_heif
from purefile.clean.jpeg import strip_jpeg
from purefile.clean.png import strip_png
from purefile.clean.webp import strip_webp
from purefile.formats import Format

__all__ = ["Changes", "CleanError", "clean_file"]

BYTE_CLEANERS: dict[Format, Callable[[bytes], tuple[bytes, Changes]]] = {
    Format.JPEG: strip_jpeg,
    Format.PNG: strip_png,
    Format.WEBP: strip_webp,
}


def clean_file(src: Path, dst: Path, fmt: Format) -> Changes:
    """Write a metadata-free copy of ``src`` (of format ``fmt``) to ``dst``."""
    if fmt in BYTE_CLEANERS:
        data, changes = BYTE_CLEANERS[fmt](src.read_bytes())
        dst.write_bytes(data)
        return changes
    if fmt is Format.HEIF:
        return strip_heif(src, dst)
    raise CleanError(f"no cleaner for {fmt}")
