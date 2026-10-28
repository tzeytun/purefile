"""Metadata report: filtering, grouping and highlights."""

from __future__ import annotations

from purefile.scan.c2pa import C2PAInfo
from purefile.scan.report import (
    MAX_VALUE_LENGTH,
    Category,
    build_report,
    categorize,
    is_metadata,
    source_type_code,
)

AI_URI = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"

SAMPLE = {
    "SourceFile": "x.jpg",
    "ExifTool:ExifToolVersion": 13.5,
    "System:FileName": "x.jpg",
    "File:FileType": "JPEG",
    "File:Comment": "hello",
    "File:ImageWidth": 100,
    "JFIF:JFIFVersion": 1.01,
    "Composite:ImageSize": "100x80",
    "ICC_Profile:ProfileDescription": "sRGB",
    "ICC-header:ProfileVersion": "4.4.0",
    "IFD0:Make": "Canon",
    "IFD0:Model": "EOS R5",
    "IFD0:Orientation": "Rotate 90 CW",
    "IFD0:Software": "Lightroom",
    "ExifIFD:DateTimeOriginal": "2024:05:17 14:32:09",
    "GPS:GPSLatitude": "41 deg 0' 29.52\"",
    "GPS:GPSLatitudeRef": "North",
    "GPS:GPSLongitude": "28 deg 58' 42.24\"",
    "GPS:GPSLongitudeRef": "East",
    "IPTC:By-line": "Someone",
    "XMP-iptcExt:DigitalSourceType": AI_URI,
    "XMP-dc:Subject": ["a", "b"],
    "PNG:ImageWidth": 10,
    "PNG:Parameters": "a prompt",
    "RIFF:VP8Version": 0,
}


def test_structural_and_kept_fields_are_excluded() -> None:
    assert not is_metadata("System", "FileName")
    assert not is_metadata("File", "ImageWidth")
    assert not is_metadata("ICC_Profile", "ProfileDescription")
    assert not is_metadata("ICC-header", "ProfileVersion")
    assert not is_metadata("IFD0", "Orientation")
    assert not is_metadata("PNG", "ImageWidth")
    assert not is_metadata("RIFF", "VP8Version")
    assert is_metadata("File", "Comment")
    assert is_metadata("PNG", "Parameters")
    assert is_metadata("XMP-dc", "Subject")


def test_categories() -> None:
    assert categorize("XMP-iptcExt", "DigitalSourceType") is Category.AI
    assert categorize("CBOR", "ActionsDigitalSourceType") is Category.AI
    assert categorize("JUMBF", "JUMDLabel") is Category.PROVENANCE
    assert categorize("GPS", "GPSAltitude") is Category.LOCATION
    assert categorize("IPTC", "City") is Category.LOCATION
    assert categorize("IFD0", "Make") is Category.DEVICE
    assert categorize("MakerNotes", "ShutterCount") is Category.DEVICE
    assert categorize("IFD0", "Software") is Category.SOFTWARE
    assert categorize("IPTC", "By-line") is Category.AUTHOR
    assert categorize("ExifIFD", "OffsetTimeOriginal") is Category.TIME
    assert categorize("XMP-dc", "Subject") is Category.OTHER


def test_build_report_groups_and_counts() -> None:
    report = build_report(SAMPLE, C2PAInfo())
    data = report.to_dict()
    assert report.total == 13
    assert [g["category"] for g in data["groups"]] == [
        "ai", "location", "device", "time", "software", "author", "other",
    ]  # fmt: skip
    other = next(g for g in data["groups"] if g["category"] == "other")
    assert {"group": "XMP-dc", "tag": "Subject", "value": "a, b"} in other["fields"]
    assert data["clean"] is False


def test_highlights() -> None:
    report = build_report(SAMPLE, C2PAInfo())
    kinds = {(h.kind, h.value, h.alert) for h in report.highlights}
    assert ("source_type", "trainedAlgorithmicMedia", True) in kinds
    assert ("ai", "generation parameters", True) in kinds
    assert ("device", "Canon EOS R5", False) in kinds
    assert ("software", "Lightroom", False) in kinds
    assert ("time", "2024:05:17 14:32:09", False) in kinds
    location = next(h for h in report.highlights if h.kind == "location")
    assert "North" in location.value and "East" in location.value


def test_c2pa_from_c2patool() -> None:
    info = C2PAInfo(present=True, claim_generator="Gen 1.0", digital_source_types=[AI_URI])
    report = build_report({}, info)
    assert report.highlights[0].kind == "c2pa" and report.highlights[0].alert
    assert [h.value for h in report.highlights if h.kind == "source_type"] == [
        "trainedAlgorithmicMedia"
    ]
    assert not report.is_clean


def test_c2pa_fallback_from_exiftool_jumbf() -> None:
    tags = {
        "JUMBF:JUMDLabel": "c2pa",
        "CBOR:Claim_Generator_InfoName": "Some Generator",
        "CBOR:Claim_Generator_InfoVersion": "2.0",
        "CBOR:ActionsDigitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
    }
    report = build_report(tags, C2PAInfo())
    assert report.c2pa.present
    assert report.c2pa.claim_generator == "Some Generator 2.0"
    source = next(h for h in report.highlights if h.kind == "source_type")
    assert (source.value, source.alert) == ("digitalCapture", False)


def test_empty_report_is_clean() -> None:
    report = build_report(
        {"System:FileName": "x", "File:FileType": "JPEG"}, C2PAInfo(), kept=["ICC"]
    )
    assert report.is_clean and report.total == 0
    assert report.to_dict()["kept"] == ["ICC"]


def test_long_values_are_truncated() -> None:
    report = build_report({"XMP-dc:Description": "x" * 1000}, C2PAInfo())
    value = report.groups["other"][0].value
    assert len(value) == MAX_VALUE_LENGTH and value.endswith("…")


def test_source_type_code() -> None:
    assert source_type_code(AI_URI) == "trainedAlgorithmicMedia"
    assert source_type_code(AI_URI + "/") == "trainedAlgorithmicMedia"
