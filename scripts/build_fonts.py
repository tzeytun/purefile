"""Download and subset the self-hosted web fonts (Outfit, Inter).

Both fonts are licensed under the SIL Open Font License 1.1. They are fetched
from a pinned commit of the google/fonts repository, subset to Latin + Latin
Extended-A (covers English and Turkish), and written as variable WOFF2 files
to ``web/fonts/``. The app itself never contacts any font CDN.

Usage:
    python scripts/build_fonts.py
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = ROOT / "web" / "fonts"

# Pinned so that builds are reproducible.
GOOGLE_FONTS_COMMIT = "ddf386ba1b9fbc6b2c818f1ddcd9148f54ced94b"
BASE_URL = f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/ofl"

FONTS: dict[str, str] = {
    "Outfit-Variable.woff2": "outfit/Outfit%5Bwght%5D.ttf",
    "Inter-Variable.woff2": "inter/Inter%5Bopsz,wght%5D.ttf",
}
LICENSES: dict[str, str] = {
    "OFL-Outfit.txt": "outfit/OFL.txt",
    "OFL-Inter.txt": "inter/OFL.txt",
}

# Basic Latin, Latin-1, Latin Extended-A, common punctuation, arrows, check mark.
UNICODES: list[int] = [
    *range(0x0020, 0x007F),
    *range(0x00A0, 0x0100),
    *range(0x0100, 0x0180),
    *range(0x2010, 0x2028),
    *range(0x2030, 0x203B),
    0x20AC,
    0x2122,
    *range(0x2190, 0x2194),
    0x2212,
    0x2713,
]


def fetch(path: str) -> bytes:
    """Download a file from the pinned google/fonts commit."""
    with urllib.request.urlopen(f"{BASE_URL}/{path}", timeout=60) as response:
        data: bytes = response.read()
    return data


def subset_to_woff2(ttf: bytes, out_path: Path) -> None:
    """Subset a variable TTF to ``UNICODES`` and save it as WOFF2."""
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    font = TTFont(io.BytesIO(ttf))
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(out_path)


def main() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for out_name, src in FONTS.items():
        out_path = FONTS_DIR / out_name
        subset_to_woff2(fetch(src), out_path)
        print(f"wrote {out_path.relative_to(ROOT)} ({out_path.stat().st_size // 1024} KB)")
    for out_name, src in LICENSES.items():
        (FONTS_DIR / out_name).write_bytes(fetch(src))
        print(f"wrote {(FONTS_DIR / out_name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
