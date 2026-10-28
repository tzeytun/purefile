"""MP4/MOV metadata removal by stream-copy remuxing.

ffmpeg copies the video, audio and subtitle packets unchanged (``-c copy``)
into a new container without global/stream metadata or chapters. ``bitexact``
mode stops ffmpeg from adding its own fingerprints (encoder tag, compressor
name, creation times). Data tracks such as timecode, GPS telemetry (GoPro
``gpmd``, Apple ``mebx``) and cover art are not copied.

Rotation lives in the track header's display matrix, not in metadata, and is
carried over by the remux; it is checked afterwards and re-applied if lost.
Finally, any C2PA/XMP ``uuid`` box or user-data/meta box that survived is
neutralized in place (see :mod:`purefile.clean.isobmff`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from purefile import tools
from purefile.clean import isobmff
from purefile.clean.base import KEPT_ORIENTATION, Changes, CleanError
from purefile.config import get_settings
from purefile.formats import Format

# Containers in which user data and metadata boxes are neutralized.
METADATA_BOX_PARENTS = {(), (b"moov",), (b"moov", b"trak")}


def probe(path: Path) -> dict[str, Any]:
    """ffprobe stream, format and chapter information as JSON."""
    result = tools.run(
        [get_settings().ffprobe_path, "-v", "error", "-show_streams", "-show_chapters",
         "-show_format", "-of", "json", path]
    )  # fmt: skip
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def _is_attached_picture(stream: dict[str, Any]) -> bool:
    return bool((stream.get("disposition") or {}).get("attached_pic"))


def video_streams(info: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s for s in info.get("streams", [])
        if s.get("codec_type") == "video" and not _is_attached_picture(s)
    ]  # fmt: skip


def rotation(info: dict[str, Any]) -> float:
    """Display rotation of the first video stream in degrees (0 if none)."""
    streams = video_streams(info)
    if not streams:
        return 0.0
    for side_data in streams[0].get("side_data_list") or []:
        if "rotation" in side_data:
            return float(side_data["rotation"])
    return float((streams[0].get("tags") or {}).get("rotate", 0))


def _remux(src: Path, dst: Path, fmt: Format, rotate: float | None = None) -> None:
    settings = get_settings()
    input_options = ["-display_rotation:v:0", f"{rotate:g}"] if rotate is not None else []
    tools.run(
        [
            settings.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            *input_options, "-i", src,
            # Real video (no cover art), audio and subtitles. Data tracks are left out.
            "-map", "0:V", "-map", "0:a?", "-map", "0:s?",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-c", "copy",
            "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
            "-f", "mov" if fmt is Format.MOV else "mp4",
            dst,
        ]
    )  # fmt: skip


def _metadata_boxes(path: Path) -> list[isobmff.Box]:
    """C2PA/XMP boxes anywhere, plus user-data/meta boxes at movie and track level."""
    found = isobmff.find(
        path,
        lambda b: (
            isobmff.is_c2pa(b)
            or isobmff.is_xmp(b)
            or (b.type in (b"udta", b"meta") and b.path in METADATA_BOX_PARENTS)
        ),
    )
    # Skip boxes nested inside one that is already being neutralized.
    outer: list[isobmff.Box] = []
    for box in sorted(found, key=lambda b: (b.offset, -b.size)):
        if not any(o.offset <= box.offset < o.end for o in outer):
            outer.append(box)
    return outer


def strip_video(src: Path, dst: Path, fmt: Format) -> Changes:
    """Write a metadata-free remux of ``src`` to ``dst``."""
    changes = Changes()
    info = probe(src)
    if not video_streams(info):
        raise CleanError("no video stream found")

    _remux(src, dst, fmt)
    wanted = rotation(info)
    if abs(rotation(probe(dst)) - wanted) > 0.5:
        _remux(src, dst, fmt, rotate=wanted)
        if abs(rotation(probe(dst)) - wanted) > 0.5:
            raise CleanError("could not preserve the video rotation")
    if wanted:
        changes.keep(KEPT_ORIENTATION)

    changes.remove("Container and stream metadata")
    streams = info.get("streams", [])
    if any(s.get("codec_type") == "data" for s in streams):
        changes.remove("Data tracks (timecode, telemetry)")
    if any(_is_attached_picture(s) for s in streams):
        changes.remove("Cover art")
    if info.get("chapters"):
        changes.remove("Chapters")

    leftovers = _metadata_boxes(dst)
    if leftovers:
        isobmff.neutralize(dst, leftovers)
    return changes
