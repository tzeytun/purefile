"""End-to-end image cleaning against the real tools (exiftool, c2patool).

Each generated fixture carries EXIF/IPTC/XMP metadata, an ICC profile and a
C2PA manifest. After cleaning, exiftool and c2patool must find no metadata,
while decoded pixels and the ICC profile must be unchanged.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from purefile import pipeline
from purefile.clean import CleanError
from purefile.clean.base import KEPT_ICC, KEPT_ORIENTATION
from purefile.formats import Format, detect_file
from tests.conftest import c2patool_output, exiftool_tags, pixels, requires_tools

pytestmark = requires_tools

IMAGES = ["photo.jpg", "ai-render.png", "composite.webp", "portrait.heic"]
METADATA_GROUP_PREFIXES = (
    "ExifIFD", "GPS", "IPTC", "XMP", "JUMBF", "CBOR", "Jpeg2000", "Photoshop", "MakerNotes",
    "InteropIFD", "IFD1",
)  # fmt: skip


@pytest.fixture(params=IMAGES)
def cleaned(
    request: pytest.FixtureRequest, fixtures_dir: Path, tmp_path: Path
) -> tuple[Path, Path, pipeline.Result]:
    src = fixtures_dir / request.param
    dst = tmp_path / f"clean{src.suffix}"
    return src, dst, pipeline.process(src, dst, detect_file(src))


def test_before_report_finds_metadata(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    _, _, result = cleaned
    assert result.before.total > 10
    assert result.before.c2pa.present
    kinds = {h.kind for h in result.before.highlights}
    assert {"c2pa", "source_type", "software", "time"} <= kinds


def test_exiftool_finds_no_metadata(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    _, dst, result = cleaned
    tags = exiftool_tags(dst)
    leftovers = [key for key in tags if key.startswith(METADATA_GROUP_PREFIXES)]
    leftovers += [key for key in tags if key.startswith("IFD0:") and key != "IFD0:Orientation"]
    leftovers += [key for key in tags if key in ("File:Comment", "PNG:Parameters", "PNG:Software")]
    assert leftovers == []
    assert result.after.is_clean and result.after.total == 0


def test_c2patool_finds_no_manifest(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    _, dst, _ = cleaned
    result = c2patool_output(dst)
    assert result.returncode != 0
    assert "no claim found" in result.stderr.lower()


def test_pixels_unchanged(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, _ = cleaned
    assert pixels(dst) == pixels(src)


def test_icc_profile_preserved(cleaned: tuple[Path, Path, pipeline.Result]) -> None:
    src, dst, result = cleaned
    with Image.open(src) as before, Image.open(dst) as after:
        assert after.info.get("icc_profile")
        assert after.info.get("icc_profile") == before.info.get("icc_profile")
    assert KEPT_ICC in result.after.kept


def test_jpeg_orientation_preserved(fixtures_dir: Path, tmp_path: Path) -> None:
    dst = tmp_path / "clean.jpg"
    result = pipeline.process(fixtures_dir / "photo.jpg", dst, Format.JPEG)
    assert exiftool_tags(dst)["IFD0:Orientation"] == "Rotate 90 CW"
    assert KEPT_ORIENTATION in result.after.kept


def test_ai_provenance_is_flagged(fixtures_dir: Path) -> None:
    report = pipeline.scan(fixtures_dir / "ai-render.png", Format.PNG)
    alerts = {(h.kind, h.value) for h in report.highlights if h.alert}
    assert ("c2pa", "Fixture Diffusion 1.0") in alerts
    assert ("source_type", "trainedAlgorithmicMedia") in alerts
    assert ("ai", "generation parameters") in alerts


def test_camera_capture_is_not_flagged_as_ai(fixtures_dir: Path) -> None:
    report = pipeline.scan(fixtures_dir / "photo.jpg", Format.JPEG)
    source = next(h for h in report.highlights if h.kind == "source_type")
    assert (source.value, source.alert) == ("digitalCapture", False)


def test_failed_verification_deletes_output(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_op_cleaner(src: Path, dst: Path, fmt: Format) -> object:
        shutil.copyfile(src, dst)
        return None

    monkeypatch.setattr(pipeline, "clean_file", no_op_cleaner)
    dst = tmp_path / "out.jpg"
    with pytest.raises(CleanError, match="metadata remained"):
        pipeline.process(fixtures_dir / "photo.jpg", dst, Format.JPEG)
    assert not dst.exists()


def test_already_clean_file_stays_clean(
    cleaned: tuple[Path, Path, pipeline.Result], tmp_path: Path
) -> None:
    _, dst, _ = cleaned
    again = tmp_path / f"again{dst.suffix}"
    result = pipeline.process(dst, again, detect_file(dst))
    assert result.before.is_clean and result.after.is_clean


def test_heif_leftover_uuid_boxes_are_neutralized(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If exiftool ever leaves a C2PA box behind, it is overwritten in place."""
    from purefile.clean import heif, isobmff

    def keep_everything(args: list[object], **_: object) -> None:
        shutil.copyfile(str(args[-1]), str(args[-2]))

    monkeypatch.setattr(heif.tools, "run", keep_everything)
    dst = tmp_path / "out.heic"
    changes = heif.strip_heif(fixtures_dir / "portrait.heic", dst)
    assert isobmff.find(dst, isobmff.is_c2pa) == []
    assert "uuid box" in changes.removed
    assert pixels(dst) == pixels(fixtures_dir / "portrait.heic")
