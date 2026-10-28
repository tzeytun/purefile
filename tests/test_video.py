"""Video cleaning: streams stay byte-identical, rotation survives, metadata goes."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

from purefile import pipeline, tools
from purefile.clean import video
from purefile.clean.base import KEPT_ORIENTATION, CleanError
from purefile.config import get_settings
from purefile.formats import Format, detect_file
from tests.conftest import c2patool_output, exiftool_tags, requires_video_tools

VIDEOS = ["clip.mp4", "clip.mov"]
EXPECTED_ROTATION = {"clip.mp4": 90.0, "clip.mov": -90.0}
METADATA_GROUP_PREFIXES = ("Keys", "ItemList", "UserData", "XMP", "GPS", "JUMBF", "CBOR",
                           "Jpeg2000", "Microsoft")  # fmt: skip
QUICKTIME_DATES = ("CreateDate", "ModifyDate", "TrackCreateDate", "TrackModifyDate",
                   "MediaCreateDate", "MediaModifyDate")  # fmt: skip


def stream_hashes(path: Path) -> list[str]:
    """Per-stream MD5 of the copied video and audio packets."""
    result = subprocess.run(
        [tools.resolve(get_settings().ffmpeg_path) or "ffmpeg", "-v", "error", "-i", str(path),
         "-map", "0:V", "-map", "0:a", "-c", "copy", "-f", "streamhash", "-hash", "md5", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return result.stdout.splitlines()


# --- Integration (real ffmpeg, exiftool, c2patool) -----------------------------


@pytest.fixture(params=VIDEOS)
def cleaned(
    request: pytest.FixtureRequest, fixtures_dir: Path, tmp_path: Path
) -> tuple[Path, Path, pipeline.Result]:
    src = fixtures_dir / request.param
    dst = tmp_path / f"clean{src.suffix}"
    return src, dst, pipeline.process(src, dst, detect_file(src))


@requires_video_tools
def test_streams_are_bit_identical(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, _ = cleaned
    before, after = stream_hashes(src), stream_hashes(dst)
    assert len(before) == 2  # one video and one audio stream
    assert after == before


@requires_video_tools
def test_rotation_is_preserved(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, result = cleaned
    assert video.rotation(video.probe(dst)) == EXPECTED_ROTATION[src.name]
    assert KEPT_ORIENTATION in result.after.kept


@requires_video_tools
def test_exiftool_finds_no_metadata(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    _, dst, result = cleaned
    tags = exiftool_tags(dst)
    leftovers = [key for key in tags if key.startswith(METADATA_GROUP_PREFIXES)]
    for key, value in tags.items():
        if key.partition(":")[2] in QUICKTIME_DATES and not str(value).startswith("0000:00:00"):
            leftovers.append(key)
        if key.endswith(":CompressorName") and value:
            leftovers.append(key)
    assert leftovers == []
    assert result.after.is_clean


@requires_video_tools
def test_c2patool_finds_no_manifest(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    _, dst, _ = cleaned
    assert "no claim found" in c2patool_output(dst).stderr.lower()


@requires_video_tools
def test_data_tracks_cover_art_and_chapters_removed(
    cleaned: tuple[Path, Path, pipeline.Result],
) -> None:
    _, dst, _ = cleaned
    info = video.probe(dst)
    assert [s["codec_type"] for s in info["streams"]] == ["video", "audio"]
    assert info["chapters"] == []


@requires_video_tools
def test_duration_is_unchanged(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, _ = cleaned
    before = float(video.probe(src)["format"]["duration"])
    after = float(video.probe(dst)["format"]["duration"])
    assert after == pytest.approx(before, abs=0.05)


@requires_video_tools
def test_before_report_flags_ai_and_location(fixtures_dir: Path) -> None:
    report = pipeline.scan(fixtures_dir / "clip.mp4", Format.MP4)
    alerts = {(h.kind, h.value) for h in report.highlights if h.alert}
    assert ("c2pa", "Fixture Video Editor 1.0") in alerts
    assert ("source_type", "compositeWithTrainedAlgorithmicMedia") in alerts
    location = next(h for h in report.highlights if h.kind == "location")
    assert location.value.startswith("41.00")


@requires_video_tools
def test_output_container_matches_input(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, _ = cleaned
    assert detect_file(dst) is detect_file(src)


# --- Unit (ffmpeg/ffprobe faked) ----------------------------------------------


def probe_with_rotation(
    degrees: float | None, *, extra: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    stream: dict[str, Any] = {"codec_type": "video", "disposition": {"attached_pic": 0}}
    if degrees is not None:
        stream["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": degrees}]
    return {"streams": [stream, *(extra or [])], "chapters": []}


def test_rotation_parsing() -> None:
    assert video.rotation(probe_with_rotation(-90)) == -90
    assert video.rotation(probe_with_rotation(None)) == 0
    assert video.rotation({"streams": [{"codec_type": "video", "tags": {"rotate": "180"}}]}) == 180
    cover_only = {"streams": [{"codec_type": "video", "disposition": {"attached_pic": 1}}]}
    assert video.rotation(cover_only) == 0


def fake_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rotations_after: list[float]
) -> list[float | None]:
    """Fake probe/remux; returns the list of ``rotate`` arguments passed to remux."""
    calls: list[float | None] = []
    results = iter(rotations_after)

    def probe(path: Path) -> dict[str, Any]:
        if path.name == "in.mp4":
            return probe_with_rotation(90)
        return probe_with_rotation(next(results))

    def remux(src: Path, dst: Path, fmt: Format, rotate: float | None = None) -> None:
        calls.append(rotate)
        dst.write_bytes(struct.pack(">I", 16) + b"ftypisom" + bytes(4))

    monkeypatch.setattr(video, "probe", probe)
    monkeypatch.setattr(video, "_remux", remux)
    (tmp_path / "in.mp4").write_bytes(b"")
    return calls


def test_rotation_is_reapplied_when_lost(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = fake_ffmpeg(monkeypatch, tmp_path, rotations_after=[0, 90])
    changes = video.strip_video(tmp_path / "in.mp4", tmp_path / "out.mp4", Format.MP4)
    assert calls == [None, 90]
    assert KEPT_ORIENTATION in changes.kept


def test_rotation_failure_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_ffmpeg(monkeypatch, tmp_path, rotations_after=[0, 0])
    with pytest.raises(CleanError, match="rotation"):
        video.strip_video(tmp_path / "in.mp4", tmp_path / "out.mp4", Format.MP4)


def test_audio_only_file_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(video, "probe", lambda path: {"streams": [{"codec_type": "audio"}]})
    with pytest.raises(CleanError, match="no video stream"):
        video.strip_video(tmp_path / "in.mp4", tmp_path / "out.mp4", Format.MP4)


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def test_metadata_boxes_selects_outermost(tmp_path: Path) -> None:
    from purefile.clean.isobmff import C2PA_UUID

    udta = box(b"udta", box(b"meta", box(b"hdlr", bytes(25)) + box(b"XMP_", b"x")))
    trak = box(b"trak", box(b"tkhd", bytes(84)) + box(b"udta", box(b"name", b"secret")))
    mdia_udta = box(b"mdia", box(b"udta", b""))  # deeper user data is left alone
    path = tmp_path / "x.mp4"
    path.write_bytes(
        box(b"ftyp", b"isom")
        + box(b"uuid", C2PA_UUID + b"manifest")
        + box(b"moov", box(b"mvhd", bytes(100)) + trak + udta + mdia_udta)
        + box(b"mdat", b"data")
    )
    labels = [b.label for b in video._metadata_boxes(path)]
    assert labels == ["uuid", "moov/trak/udta", "moov/udta"]
