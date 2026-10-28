"""Generate synthetic test fixtures with realistic metadata.

No third-party photos or videos are committed to the repository. Instead this
script draws simple images, encodes short test videos with ffmpeg, embeds
EXIF/IPTC/XMP metadata with exiftool, and signs a C2PA manifest with
c2patool's built-in *test* certificate (no network access, no real identity).

Usage:
    python scripts/make_fixtures.py [OUTPUT_DIR]      # default: build/fixtures

Requires exiftool, c2patool and ffmpeg on PATH (or PUREFILE_*_PATH variables, see
.env.example), plus the dev dependencies (``pip install -e ".[dev]"``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw

from purefile.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "build" / "fixtures"

IPTC_DST = "http://cv.iptc.org/newscodes/digitalsourcetype/"
AI_GENERATED = IPTC_DST + "trainedAlgorithmicMedia"
AI_COMPOSITE = IPTC_DST + "compositeWithTrainedAlgorithmicMedia"
CAMERA = IPTC_DST + "digitalCapture"

NAVY = (26, 46, 81)
MINT = (71, 219, 152)
CORAL = (255, 107, 107)


def tool(name: str) -> str:
    """Path of an external tool, resolved through the app's settings (PUREFILE_*_PATH, .env)."""
    configured = getattr(get_settings(), f"{name}_path")
    found = shutil.which(configured)
    if not found:
        sys.exit(f"error: {name} not found (install it or set PUREFILE_{name.upper()}_PATH)")
    return found


def run(args: Sequence[str | Path]) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True)


# --- Images -------------------------------------------------------------------


def draw_scene(width: int, height: int, palette: tuple[tuple[int, int, int], ...]) -> Image.Image:
    """A colorful synthetic scene: vertical gradient, sun and rolling hills."""
    top, bottom, accent = palette
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)),
        )
    r = min(width, height) // 6
    cx, cy = width * 2 // 3, height // 3
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    for i, shade in enumerate((0.55, 0.35)):
        color = tuple(round(c * shade) for c in bottom)
        base = height * (0.7 + 0.12 * i)
        draw.ellipse(
            [-width * 0.3 + i * width * 0.4, base, width * (0.9 + i * 0.4), height * 1.6],
            fill=color,
        )
    return img


def srgb_icc() -> bytes:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile.tobytes()


def exiftool_write(path: Path, *assignments: str) -> None:
    run([tool("exiftool"), "-overwrite_original", "-q", *assignments, path])


def c2pa_sign(path: Path, source_type: str, generator: str) -> None:
    """Embed a C2PA manifest signed with c2patool's built-in test certificate."""
    manifest = {
        "claim_generator_info": [{"name": generator, "version": "1.0"}],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {"actions": [{"action": "c2pa.created", "digitalSourceType": source_type}]},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        signed = Path(tmp) / f"signed{path.suffix}"
        run([tool("c2patool"), path, "-m", manifest_path, "-o", signed, "-f"])
        shutil.copyfile(signed, path)


CAMERA_EXIF = (
    "-EXIF:Make=Purefile Optics",
    "-EXIF:Model=Synthetic One",
    "-EXIF:Software=Fixture Builder 1.0",
    "-EXIF:Artist=Test Photographer",
    "-EXIF:DateTimeOriginal=2024:05:17 14:32:09",
    "-EXIF:CreateDate=2024:05:17 14:32:09",
    "-EXIF:SerialNumber=PF-0001",
    "-EXIF:GPSLatitude=41.0082",
    "-EXIF:GPSLatitudeRef=N",
    "-EXIF:GPSLongitude=28.9784",
    "-EXIF:GPSLongitudeRef=E",
)


def make_jpeg(out: Path) -> Path:
    """Camera-style JPEG: EXIF (incl. GPS, Orientation 6), IPTC, XMP, comment, ICC, C2PA."""
    path = out / "photo.jpg"
    draw_scene(960, 640, ((255, 196, 140), (64, 92, 160), (255, 236, 180))).save(
        path, quality=90, icc_profile=srgb_icc(), comment=b"Shot on a synthetic camera"
    )
    exiftool_write(
        path,
        *CAMERA_EXIF,
        "-EXIF:Orientation#=6",
        "-IPTC:By-line=Test Photographer",
        "-IPTC:City=Istanbul",
        "-IPTC:Keywords=fixture",
        "-XMP-dc:Creator=Test Photographer",
        "-XMP-dc:Description=Synthetic test photo",
        f"-XMP-iptcExt:DigitalSourceType={CAMERA}",
    )
    c2pa_sign(path, CAMERA, "Purefile Fixture Camera")
    return path


def make_png(out: Path) -> Path:
    """AI-render-style PNG: generation parameters, XMP, eXIf, tIME, ICC, C2PA."""
    from PIL.PngImagePlugin import PngInfo

    path = out / "ai-render.png"
    info = PngInfo()
    info.add_text("parameters", "a lighthouse at dusk, oil painting\nSteps: 30, Sampler: Euler a")
    info.add_text("Software", "Fixture Diffusion 2.1")
    draw_scene(768, 768, ((40, 30, 90), (250, 120, 90), (255, 220, 120))).save(
        path, pnginfo=info, icc_profile=srgb_icc()
    )
    exiftool_write(
        path,
        "-EXIF:Software=Fixture Diffusion 2.1",
        "-EXIF:DateTimeOriginal=2025:01:02 03:04:05",
        "-PNG:CreationTime=2025:01:02 03:04:05",
        f"-XMP-iptcExt:DigitalSourceType={AI_GENERATED}",
        "-XMP-xmp:CreatorTool=Fixture Diffusion 2.1",
    )
    c2pa_sign(path, AI_GENERATED, "Fixture Diffusion")
    return path


def make_webp(out: Path) -> Path:
    """Edited-composite WebP: EXIF, XMP, ICC, C2PA."""
    path = out / "composite.webp"
    draw_scene(800, 600, ((20, 60, 70), (120, 200, 170), CORAL)).save(
        path, quality=90, icc_profile=srgb_icc()
    )
    exiftool_write(
        path,
        "-EXIF:Make=Purefile Optics",
        "-EXIF:Model=Synthetic One",
        "-EXIF:Software=Fixture Editor 3",
        "-EXIF:DateTimeOriginal=2025:03:04 05:06:07",
        "-EXIF:GPSLatitude=40.7128",
        "-EXIF:GPSLatitudeRef=N",
        "-EXIF:GPSLongitude=74.0060",
        "-EXIF:GPSLongitudeRef=W",
        f"-XMP-iptcExt:DigitalSourceType={AI_COMPOSITE}",
    )
    c2pa_sign(path, AI_COMPOSITE, "Fixture Editor")
    return path


def make_heic(out: Path) -> Path:
    """Phone-style HEIC: EXIF (incl. GPS), XMP, ICC, C2PA."""
    import pillow_heif

    path = out / "portrait.heic"
    img = draw_scene(640, 960, ((150, 200, 255), (30, 80, 60), (255, 250, 210)))
    exif = Image.Exif()
    exif[0x010F] = "Purefile Optics"  # Make
    exif[0x0110] = "Synthetic Phone"  # Model
    exif[0x0131] = "Fixture OS 18.0"  # Software
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator><rdf:Seq><rdf:li>Test Photographer</rdf:li></rdf:Seq></dc:creator>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    pillow_heif.from_pillow(img).save(
        path, quality=80, exif=exif.tobytes(), xmp=xmp.encode(), icc_profile=srgb_icc()
    )
    exiftool_write(
        path,
        "-EXIF:DateTimeOriginal=2025:06:07 08:09:10",
        "-EXIF:GPSLatitude=48.8584",
        "-EXIF:GPSLatitudeRef=N",
        "-EXIF:GPSLongitude=2.2945",
        "-EXIF:GPSLongitudeRef=E",
    )
    c2pa_sign(path, CAMERA, "Purefile Fixture Phone")
    return path


# --- Videos -------------------------------------------------------------------


def encode_test_video(path: Path, seconds: int, size: str) -> None:
    """A short H.264/AAC clip of ffmpeg's built-in test pattern and a sine tone."""
    run([
        tool("ffmpeg"), "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", path,
    ])  # fmt: skip


def make_mp4(out: Path) -> Path:
    """Vertical clip: rotation 90, title/location/date, chapters, cover art, Keys, XMP, C2PA."""
    path = out / "clip.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        raw, cover, chapters = Path(tmp) / "raw.mp4", Path(tmp) / "cover.png", Path(tmp) / "ch.txt"
        encode_test_video(raw, 3, "640x360")
        draw_scene(320, 180, ((255, 196, 140), (64, 92, 160), (255, 236, 180))).save(cover)
        chapters.write_text(
            ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1500\ntitle=Secret chapter\n"
        )
        run([
            tool("ffmpeg"), "-loglevel", "error", "-y",
            "-display_rotation", "90", "-i", raw, "-i", cover, "-i", chapters,
            "-map", "0", "-map", "1", "-map_chapters", "2", "-c", "copy",
            "-disposition:v:1", "attached_pic",
            "-metadata", "title=Secret holiday clip",
            "-metadata", "comment=Recorded on a synthetic phone",
            "-metadata", "location=+41.0082+028.9784/",
            "-metadata", "creation_time=2024-05-17T14:32:09Z",
            "-metadata:s:v:0", "handler_name=Core Media Video",
            path,
        ])  # fmt: skip
    exiftool_write(
        path,
        "-Keys:Make=Purefile Optics",
        "-Keys:Model=Synthetic Phone",
        "-Keys:Software=Fixture OS 18.0",
        f"-XMP-iptcExt:DigitalSourceType={AI_COMPOSITE}",
        "-XMP-xmp:CreatorTool=Fixture Video Editor",
    )
    c2pa_sign(path, AI_COMPOSITE, "Fixture Video Editor")
    return path


def make_mov(out: Path) -> Path:
    """QuickTime clip: rotation 270, timecode data track, Apple-style Keys with GPS, C2PA."""
    path = out / "clip.mov"
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.mp4"
        encode_test_video(raw, 2, "480x270")
        run([
            tool("ffmpeg"), "-loglevel", "error", "-y", "-display_rotation", "270", "-i", raw,
            "-map", "0", "-c", "copy", "-timecode", "01:00:00:00",
            "-metadata", "creation_time=2025-02-03T04:05:06Z", "-f", "mov", path,
        ])  # fmt: skip
    exiftool_write(
        path,
        "-Keys:Make=Purefile Optics",
        "-Keys:Model=Synthetic Camera",
        "-Keys:GPSCoordinates=48.8584, 2.2945",
        "-Keys:CreationDate=2025:02:03 04:05:06+01:00",
        "-UserData:Software=Fixture Recorder 2",
    )
    c2pa_sign(path, CAMERA, "Purefile Fixture Camera")
    return path


IMAGE_BUILDERS = (make_jpeg, make_png, make_webp, make_heic)
VIDEO_BUILDERS = (make_mp4, make_mov)


def generate(out: Path = DEFAULT_OUT, *, video: bool = True) -> dict[str, Path]:
    """Build every fixture into ``out`` and return them keyed by file name."""
    out.mkdir(parents=True, exist_ok=True)
    builders = IMAGE_BUILDERS + (VIDEO_BUILDERS if video else ())
    built = [build(out) for build in builders]
    return {path.name: path for path in built}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    for name, path in generate(out).items():
        print(f"{name:<20} {path.stat().st_size // 1024:>6} KB")


if __name__ == "__main__":
    main()
