"""Read embedded metadata with exiftool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from purefile import tools
from purefile.config import get_settings


def read_tags(path: Path) -> dict[str, Any]:
    """Return every tag exiftool finds, keyed as ``"Group:Tag"`` (family 1 groups).

    ``-a`` keeps duplicate tags, ``-u`` includes unknown tags, and ``-s`` uses
    tag names rather than descriptions so keys are stable.
    """
    settings = get_settings()
    result = tools.run(
        [
            settings.exiftool_path,
            "-json",
            "-G1",
            "-a",
            "-u",
            "-s",
            "-api",
            "LargeFileSupport=1",
            "-charset",
            "filename=utf8",
            path,
        ]
    )
    records: list[dict[str, Any]] = json.loads(result.stdout.decode("utf-8", errors="replace"))
    return records[0] if records else {}
