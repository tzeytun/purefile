"""HEIC/HEIF metadata removal.

HEIF stores EXIF and XMP as *items* whose data lives in ``mdat`` and is
referenced through ``iloc`` offsets, so it cannot be cut out byte-wise without
rewriting the item tables. exiftool does exactly that, copying the coded image
data unchanged. The ICC profile (a ``colr`` property) and rotation/mirroring
(``irot``/``imir`` properties) are part of the image description and are kept.

Afterwards any remaining C2PA or XMP ``uuid`` box is neutralized in place as a
safety net.
"""

from __future__ import annotations

from pathlib import Path

from purefile import tools
from purefile.clean import isobmff
from purefile.clean.base import Changes
from purefile.config import get_settings


def strip_heif(src: Path, dst: Path) -> Changes:
    """Write a metadata-free copy of ``src`` to ``dst``."""
    changes = Changes()
    dst.unlink(missing_ok=True)  # exiftool refuses to overwrite with -o
    tools.run(
        [
            get_settings().exiftool_path,
            "-q",
            "-all=",
            "--ICC_Profile:all",
            "-api",
            "LargeFileSupport=1",
            "-o",
            dst,
            src,
        ]
    )
    changes.remove("EXIF, XMP and C2PA items")
    leftovers = isobmff.find(dst, lambda b: isobmff.is_c2pa(b) or isobmff.is_xmp(b))
    if leftovers:
        isobmff.neutralize(dst, leftovers)
        for box in leftovers:
            changes.remove(f"{box.label} box")
    return changes
