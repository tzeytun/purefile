"""Turn raw exiftool/c2patool output into a grouped, readable metadata report.

exiftool reports *everything* it understands, including structural facts such
as image dimensions or codec parameters. Those are not metadata and survive
cleaning by design, so they are filtered out here. Whatever remains is grouped
by what it reveals (AI provenance, location, device, ...).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from purefile.scan.c2pa import C2PAInfo

MAX_VALUE_LENGTH = 300


class Category(StrEnum):
    AI = "ai"
    PROVENANCE = "provenance"
    LOCATION = "location"
    DEVICE = "device"
    TIME = "time"
    SOFTWARE = "software"
    AUTHOR = "author"
    OTHER = "other"


CATEGORY_ORDER = list(Category)

# Groups that describe the file itself (or exiftool), not embedded metadata.
STRUCTURAL_GROUPS = {"ExifTool", "System", "Composite", "JFIF", "Meta", "QuickTime"}
# The ICC profile is kept on purpose: removing it would change displayed colors.
ICC_GROUP = re.compile(r"^ICC(_Profile|-\w+)$")
# Groups that only ever contain metadata.
C2PA_GROUPS = {"JUMBF", "CBOR", "Jpeg2000"}

# Structural tags inside container groups that also hold metadata.
STRUCTURAL_TAGS: dict[str, set[str]] = {
    "File": {
        "FileType", "FileTypeExtension", "MIMEType", "ExifByteOrder", "CurrentIPTCDigest",
        "ImageWidth", "ImageHeight", "EncodingProcess", "BitsPerSample", "ColorComponents",
        "YCbCrSubSampling", "Warning", "Error",
    },
    "PNG": {
        "ImageWidth", "ImageHeight", "BitDepth", "ColorType", "Compression", "Filter",
        "Interlace", "ProfileName", "Gamma", "SRGBRendering", "PixelsPerUnitX",
        "PixelsPerUnitY", "PixelUnits", "WhitePointX", "WhitePointY", "RedX", "RedY",
        "GreenX", "GreenY", "BlueX", "BlueY", "BackgroundColor", "SignificantBits", "Palette",
        "Transparency", "AnimationFrames", "AnimationPlays", "ColorPrimaries",
        "TransferCharacteristics", "MatrixCoefficients", "VideoFullRangeFlag",
    },
    "RIFF": {
        "WebP_Flags", "ImageWidth", "ImageHeight", "VP8Version", "HorizontalScale",
        "VerticalScale", "AlphaPreprocessing", "AlphaFiltering", "AlphaCompression",
        "BackgroundColor", "AnimationLoopCount",
    },
}  # fmt: skip
# Written back on purpose so photos keep displaying upright.
KEPT_TAGS = {("IFD0", "Orientation")}

AI_SOURCE_TYPES = {
    "trainedAlgorithmicMedia",
    "compositeWithTrainedAlgorithmicMedia",
    "algorithmicMedia",
    "compositeSynthetic",
    "algorithmicallyEnhanced",
}
AI_TAGS = {"DigitalSourceType", "ActionsDigitalSourceType", "AISystemUsed", "AISystemVersionUsed",
           "AIPromptInformation", "AIPromptWriterName", "Parameters", "Prompt", "Workflow",
           "NegativePrompt"}  # fmt: skip
DEVICE_TAGS = {"Make", "Model", "SerialNumber", "BodySerialNumber", "CameraSerialNumber",
               "InternalSerialNumber", "LensMake", "LensModel", "LensSerialNumber", "LensInfo",
               "UniqueCameraModel", "HostComputer", "OwnerName", "CameraOwnerName"}  # fmt: skip
SOFTWARE_TAGS = {"Software", "CreatorTool", "ProcessingSoftware", "XMPToolkit", "Encoder",
                 "HistorySoftwareAgent", "Producer", "Generator"}  # fmt: skip
AUTHOR_TAGS = {"Artist", "Creator", "By-line", "Copyright", "CopyrightNotice", "Rights",
               "Credit", "Author", "Writer-Editor", "Source", "Contact"}  # fmt: skip
LOCATION_WORDS = re.compile(r"GPS|Location|City|Country|Sub-?location|Province|State")
TIME_WORDS = re.compile(r"Date|Time")


@dataclass
class Field:
    group: str
    tag: str
    value: str


@dataclass
class Highlight:
    """A notable finding shown as a badge. ``alert`` findings get the coral badge."""

    kind: str  # c2pa | ai | source_type | location | device | software | time
    value: str
    alert: bool = False


@dataclass
class Report:
    total: int = 0
    groups: dict[str, list[Field]] = field(default_factory=dict)
    highlights: list[Highlight] = field(default_factory=list)
    c2pa: C2PAInfo = field(default_factory=C2PAInfo)
    kept: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.total == 0 and not self.c2pa.present

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["groups"] = [
            {"category": category, "fields": [asdict(f) for f in fields]}
            for category, fields in self.groups.items()
        ]
        data["clean"] = self.is_clean
        return data


def _stringify(value: Any) -> str:
    text = ", ".join(_stringify(v) for v in value) if isinstance(value, list) else str(value)
    text = text.strip()
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 1] + "…"


def is_metadata(group: str, tag: str) -> bool:
    """Whether a tag is embedded metadata (as opposed to file structure or the kept ICC profile)."""
    if group in STRUCTURAL_GROUPS or ICC_GROUP.match(group) or (group, tag) in KEPT_TAGS:
        return False
    return tag not in STRUCTURAL_TAGS.get(group, set())


def categorize(group: str, tag: str) -> Category:
    if tag in AI_TAGS:
        return Category.AI
    if group in C2PA_GROUPS:
        return Category.PROVENANCE
    if group == "GPS" or LOCATION_WORDS.search(tag):
        return Category.LOCATION
    if (
        tag in DEVICE_TAGS
        or group.startswith("MakerNotes")
        or group in {"Canon", "Nikon", "Sony", "Apple", "Samsung"}
    ):
        return Category.DEVICE
    if tag in SOFTWARE_TAGS:
        return Category.SOFTWARE
    if tag in AUTHOR_TAGS:
        return Category.AUTHOR
    if TIME_WORDS.search(tag):
        return Category.TIME
    return Category.OTHER


def source_type_code(uri: str) -> str:
    """``http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`` -> code."""
    return uri.rstrip("/").rsplit("/", 1)[-1]


def build_report(tags: dict[str, Any], c2pa: C2PAInfo, kept: list[str] | None = None) -> Report:
    """Build a report from ``exiftool -G1 -json`` output and a c2patool summary."""
    report = Report(c2pa=c2pa, kept=list(kept or []))
    buckets: dict[Category, list[Field]] = {}
    first: dict[str, str] = {}  # first value seen per tag, for highlights
    for key, raw in tags.items():
        group, _, tag = key.partition(":")
        if not tag or not is_metadata(group, tag):
            continue
        value = _stringify(raw)
        buckets.setdefault(categorize(group, tag), []).append(Field(group, tag, value))
        first.setdefault(tag, value)
        report.total += 1
    report.groups = {c.value: buckets[c] for c in CATEGORY_ORDER if c in buckets}

    # C2PA: prefer c2patool's view; fall back to exiftool's JUMBF parsing.
    if not c2pa.present and first.get("JUMDLabel") == "c2pa":
        c2pa.present = True
        c2pa.claim_generator = " ".join(
            v
            for v in (
                first.get("Claim_Generator_InfoName"),
                first.get("Claim_Generator_InfoVersion"),
            )
            if v
        ) or first.get("Claim_generator")
    if c2pa.present:
        report.highlights.append(Highlight("c2pa", c2pa.claim_generator or "", alert=True))

    source_types = [source_type_code(t) for t in c2pa.digital_source_types]
    for tag in ("DigitalSourceType", "ActionsDigitalSourceType"):
        for uri in tags_named(tags, tag):
            code = source_type_code(uri)
            if code not in source_types:
                source_types.append(code)
    for code in source_types:
        report.highlights.append(Highlight("source_type", code, alert=code in AI_SOURCE_TYPES))
    if any(t in first for t in ("Parameters", "Prompt", "Workflow", "AIPromptInformation")):
        report.highlights.append(Highlight("ai", "generation parameters", alert=True))

    if location := _location(first):
        report.highlights.append(Highlight("location", location))
    if device := " ".join(v for v in (first.get("Make"), first.get("Model")) if v):
        report.highlights.append(Highlight("device", device))
    for tag in ("Software", "CreatorTool", "Encoder"):
        if tag in first:
            report.highlights.append(Highlight("software", first[tag]))
            break
    for tag in ("DateTimeOriginal", "CreateDate", "CreationTime", "DateCreated", "ModifyDate"):
        if tag in first:
            report.highlights.append(Highlight("time", first[tag]))
            break
    return report


def tags_named(tags: dict[str, Any], name: str) -> list[str]:
    """All values of tags called ``name`` in any group (flattening lists)."""
    values: list[str] = []
    for key, raw in tags.items():
        if key.partition(":")[2] != name:
            continue
        values.extend(str(v) for v in (raw if isinstance(raw, list) else [raw]))
    return values


def _location(first: dict[str, str]) -> str | None:
    if "GPSLatitude" in first and "GPSLongitude" in first:
        lat = f"{first['GPSLatitude']} {first.get('GPSLatitudeRef', '')}".strip()
        lon = f"{first['GPSLongitude']} {first.get('GPSLongitudeRef', '')}".strip()
        return f"{lat}, {lon}"
    for tag in ("GPSCoordinates", "GPSPosition", "LocationInformation", "City"):
        if tag in first:
            return first[tag]
    return None
