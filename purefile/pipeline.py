"""Scan -> clean -> verify, for a single file."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from purefile.clean import Changes, CleanError, clean_file, isobmff
from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION
from purefile.formats import Format
from purefile.scan import c2pa, exif
from purefile.scan.report import ICC_GROUP, Report, build_report

log = logging.getLogger(__name__)

ISOBMFF_FORMATS = {Format.HEIF, Format.MP4, Format.MOV}


@dataclass
class Result:
    format: Format
    before: Report
    after: Report
    changes: Changes


def scan(path: Path, fmt: Format) -> Report:
    """Report the metadata contained in ``path``."""
    tags = exif.read_tags(path)
    info = c2pa.inspect(path) if c2pa.available() else c2pa.C2PAInfo()
    if fmt in ISOBMFF_FORMATS and not info.present and isobmff.find(path, isobmff.is_c2pa):
        info.present = True
    return build_report(tags, info, kept=_kept(tags))


def _kept(tags: dict[str, Any]) -> list[str]:
    """Display-relevant data that is intentionally preserved."""
    kept: list[str] = []
    if any(ICC_GROUP.match(key.partition(":")[0]) for key in tags):
        kept.append(KEPT_ICC)
    rotated = any(
        key.endswith(":Rotation") and str(value) not in ("0", "Horizontal (normal)")
        for key, value in tags.items()
    )
    if "IFD0:Orientation" in tags or rotated:
        kept.append(KEPT_ORIENTATION)
    return kept


def process(src: Path, dst: Path, fmt: Format) -> Result:
    """Clean ``src`` into ``dst`` and verify that no metadata remains.

    Raises:
        CleanError: if the input is corrupt or anything is left after cleaning.
            ``dst`` is deleted in that case, so an unclean file is never served.
    """
    before = scan(src, fmt)
    try:
        changes = clean_file(src, dst, fmt)
        after = scan(dst, fmt)
        if not after.is_clean:
            leftovers = [f"{f.group}:{f.tag}" for fields in after.groups.values() for f in fields]
            if after.c2pa.present:
                leftovers.append("C2PA manifest")
            raise CleanError("metadata remained after cleaning: " + ", ".join(leftovers[:10]))
    except Exception:
        dst.unlink(missing_ok=True)
        raise
    log.info("cleaned %s file: %d fields removed", fmt, before.total)
    return Result(fmt, before, after, changes)
