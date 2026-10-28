"""Build the Purefile brand assets from the reference logo PNG.

The reference ``assets/brand/purefile-logo.png`` is the source of truth. This
script recreates it as vector art and renders every raster derivative:

* The icon is rebuilt from straight lines and circular arcs whose sizes were
  measured on the reference (see ``ICON_*`` below).
* The wordmark is vector-traced from the reference with potrace. Its letter
  shapes ("f" with a right-only crossbar, short "r" arm, large "i" dot) are not
  a stock font, so tracing preserves them; the result is plain outlined paths.
* Brand colors are sampled from the reference pixels.

Outputs (in ``assets/brand/``): purefile-logo.svg, purefile-logo-dark.svg,
purefile-icon.svg, favicon.ico, favicon-32.png, apple-touch-icon.png,
icon-192.png, icon-512.png and social-preview.png.

Usage:
    python scripts/build_brand.py            # build everything
    python scripts/build_brand.py --compare  # also write an overlay diff vs. the PNG

Requires the ``brand`` extra (``pip install -e ".[brand]"``) and Chromium for
Playwright (``python -m playwright install chromium``).
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from pathlib import Path

import numpy as np
import potrace  # type: ignore[import-untyped]
from PIL import Image, ImageFilter
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "assets" / "brand"
SOURCE_PNG = BRAND_DIR / "purefile-logo.png"
OUTFIT_WOFF2 = ROOT / "web" / "fonts" / "Outfit-Variable.woff2"

OFF_WHITE = "#F7F8FA"  # UI background and dark-mode logo fill (design system value)
TAGLINE = "Clean files. Nothing extra."

# Position of the icon's top-left corner in the reference PNG. All geometry
# below is in reference-pixel units relative to this origin.
ICON_ORIGIN = (337, 275)
ICON_SIZE = (269, 309)
# Bounding box of the wordmark in the reference PNG (with a small margin).
WORDMARK_BOX = (650, 330, 1450, 580)
LOGO_SIZE = (1100, 309)

# Document body: rounded rectangle whose top-right corner is cut away. The cut
# has a concave inner corner and a smaller convex corner where it meets the
# right edge.
ICON_BODY = (
    "M58 0H139V73"
    "A49 49 0 0 0 188 122"  # concave inner corner of the cut
    "H229"
    "A40 40 0 0 1 269 162"  # convex corner below the flap
    "V251A58 58 0 0 1 211 309"
    "H58A58 58 0 0 1 0 251"
    "V58A58 58 0 0 1 58 0Z"
)
# Folded flap: straight fold edge that curls down into a tip, separated from
# the body by a gap of about 18 px that follows the body outline.
ICON_FLAP = (
    "M156 0H157.5L257 93.3"
    "C263 98.9 269 108 269 120"  # the curl toward the tip
    "A58 58 0 0 0 229 104"  # follows the convex body corner
    "H210A54 54 0 0 1 156 50Z"
)


def sample_color(img: Image.Image, predicate: object) -> str:
    """Return the most common color among pixels matching ``predicate``."""
    counts: Counter[tuple[int, int, int]] = Counter()
    for count, rgb in img.getcolors(maxcolors=1 << 24) or []:
        if predicate(rgb):  # type: ignore[operator]
            counts[rgb] += count
    r, g, b = counts.most_common(1)[0][0]
    return f"#{r:02X}{g:02X}{b:02X}"


def sample_brand_colors(img: Image.Image) -> tuple[str, str]:
    """Sample the navy and mint brand colors from the reference image."""
    navy = sample_color(img, lambda c: sum(c) < 250)
    mint = sample_color(img, lambda c: c[1] - c[0] > 60 and c[1] > 150)
    return navy, mint


def trace_wordmark(img: Image.Image) -> str:
    """Vector-trace the wordmark and return SVG path data in icon-origin units."""
    scale = 4  # trace at 4x for sub-pixel accurate edges
    x0, y0, x1, y1 = WORDMARK_BOX
    crop = (
        img.convert("L")
        .crop(WORDMARK_BOX)
        .resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.Resampling.LANCZOS)
        .filter(ImageFilter.GaussianBlur(scale * 0.6))
    )
    ink = np.asarray(crop) < 148  # midway between navy and background luminance
    curves = potrace.Bitmap(~ink).trace(turdsize=50, alphamax=1.0, opticurve=True, opttolerance=0.4)

    ox, oy = ICON_ORIGIN

    def pt(p: potrace.Point) -> str:
        return f"{p.x / scale + x0 - ox:.1f} {p.y / scale + y0 - oy:.1f}"

    parts: list[str] = []
    for curve in curves:
        parts.append(f"M{pt(curve.start_point)}")
        for seg in curve.segments:
            if seg.is_corner:
                parts.append(f"L{pt(seg.c)}L{pt(seg.end_point)}")
            else:
                parts.append(f"C{pt(seg.c1)} {pt(seg.c2)} {pt(seg.end_point)}")
        parts.append("Z")
    return "".join(parts)


def svg_doc(view_box: str, body: str, width: float, height: float) -> str:
    """Wrap SVG elements in a standalone, accessible SVG document."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" '
        f'width="{width:g}" height="{height:g}" role="img" aria-label="Purefile">'
        f"<title>Purefile</title>{body}</svg>\n"
    )


def icon_elements(body_fill: str, flap_fill: str) -> str:
    return f'<path fill="{body_fill}" d="{ICON_BODY}"/><path fill="{flap_fill}" d="{ICON_FLAP}"/>'


def build_svgs(navy: str, mint: str, wordmark: str) -> dict[str, str]:
    """Return the three SVG documents keyed by file name."""
    w, h = LOGO_SIZE

    def logo(fg: str) -> str:
        wordmark_el = f'<path fill="{fg}" fill-rule="evenodd" d="{wordmark}"/>'
        return svg_doc(f"0 0 {w} {h}", icon_elements(fg, mint) + wordmark_el, w / 2, h / 2)

    # The icon is centered in a square canvas so it can be used for favicons.
    side = ICON_SIZE[1]
    pad = (side - ICON_SIZE[0]) / 2
    icon = svg_doc(f"{-pad:g} 0 {side} {side}", icon_elements(navy, mint), side / 4, side / 4)
    return {
        "purefile-logo.svg": logo(navy),
        "purefile-logo-dark.svg": logo(OFF_WHITE),
        "purefile-icon.svg": icon,
    }


def render(page: Page, html: str, width: int, height: int, out: Path) -> None:
    """Render an HTML snippet to a PNG of exactly ``width`` x ``height`` pixels."""
    page.set_viewport_size({"width": width, "height": height})
    page.set_content(
        "<!doctype html><html><head><style>"
        "html,body{margin:0;width:100%;height:100%;background:transparent}"
        "svg{display:block}</style></head>"
        f"<body>{html}</body></html>"
    )
    page.evaluate("document.fonts.ready")
    page.screenshot(path=str(out), omit_background=True)


def sized(svg: str, width: int, height: int) -> str:
    """Override the intrinsic size of an SVG document."""
    return svg.replace("<svg ", f'<svg style="width:{width}px;height:{height}px" ', 1)


def app_icon_html(icon_svg: str, size: int, fraction: float) -> str:
    """Icon centered on an opaque off-white square (iOS/PWA icons)."""
    inner = round(size * fraction)
    return (
        f'<div style="width:{size}px;height:{size}px;background:{OFF_WHITE};'
        f'display:flex;align-items:center;justify-content:center">'
        f"{sized(icon_svg, inner, inner)}</div>"
    )


def social_preview_html(logo_svg: str, navy: str) -> str:
    font = base64.b64encode(OUTFIT_WOFF2.read_bytes()).decode()
    return (
        "<style>@font-face{font-family:Outfit;font-weight:100 900;"
        f"src:url(data:font/woff2;base64,{font}) format('woff2')}}</style>"
        f'<div style="width:1280px;height:640px;background:{OFF_WHITE};display:flex;'
        'flex-direction:column;align-items:center;justify-content:center;gap:44px">'
        f"{sized(logo_svg, 660, round(660 * LOGO_SIZE[1] / LOGO_SIZE[0]))}"
        f'<div style="font-family:Outfit;font-weight:400;font-size:44px;color:{navy};'
        f'opacity:.72;letter-spacing:.01em">{TAGLINE}</div></div>'
    )


def build_rasters(svgs: dict[str, str], navy: str, compare: bool) -> None:
    icon = svgs["purefile-icon.svg"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        render(page, sized(icon, 32, 32), 32, 32, BRAND_DIR / "favicon-32.png")
        ico_layers: list[Image.Image] = []
        for size in (16, 32, 48):
            tmp = BRAND_DIR / f".ico-{size}.png"
            render(page, sized(icon, size, size), size, size, tmp)
            ico_layers.append(Image.open(tmp).convert("RGBA"))
            ico_layers[-1].load()
            tmp.unlink()
        ico_layers[-1].save(
            BRAND_DIR / "favicon.ico",
            sizes=[(16, 16), (32, 32), (48, 48)],
            append_images=ico_layers[:-1],
        )
        for name, size in (
            ("apple-touch-icon.png", 180),
            ("icon-192.png", 192),
            ("icon-512.png", 512),
        ):
            render(page, app_icon_html(icon, size, 0.62), size, size, BRAND_DIR / name)
        render(
            page,
            social_preview_html(svgs["purefile-logo.svg"], navy),
            1280,
            640,
            BRAND_DIR / "social-preview.png",
        )
        if compare:
            write_comparison(page, svgs["purefile-logo.svg"])
        browser.close()


def write_comparison(page: Page, logo_svg: str) -> None:
    """Render the SVG logo at reference scale and report how well it matches.

    Writes ``build/brand-compare.png``: red = only in the PNG, blue = only in
    the SVG, gray = both.
    """
    ref = Image.open(SOURCE_PNG).convert("RGB")
    ox, oy = ICON_ORIGIN
    w, h = LOGO_SIZE
    html = (
        f'<div style="position:relative;width:{ref.width}px;height:{ref.height}px">'
        f'<div style="position:absolute;left:{ox}px;top:{oy}px">{sized(logo_svg, w, h)}</div></div>'
    )
    out_dir = ROOT / "build"
    out_dir.mkdir(exist_ok=True)
    tmp = out_dir / "brand-svg.png"
    render(page, html, ref.width, ref.height, tmp)
    svg_ink = np.asarray(Image.open(tmp).convert("RGBA"))[..., 3] > 127
    # Midpoint thresholds between each brand color and the background, so
    # anti-aliased edge pixels are split fairly.
    rgb = np.asarray(ref).astype(int)
    png_ink = (np.asarray(ref.convert("L")) < 148) | (rgb[..., 1] - rgb[..., 0] > 74)
    union = np.logical_or(svg_ink, png_ink).sum()
    iou = np.logical_and(svg_ink, png_ink).sum() / union
    diff = np.full((*svg_ink.shape, 3), 255, np.uint8)
    diff[svg_ink & png_ink] = (190, 190, 190)
    diff[png_ink & ~svg_ink] = (230, 40, 40)
    diff[svg_ink & ~png_ink] = (40, 90, 230)
    Image.fromarray(diff).save(out_dir / "brand-compare.png")
    print(f"overlay IoU vs. reference PNG: {iou:.4f} (diff: build/brand-compare.png)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--compare", action="store_true", help="write an overlay diff vs. the PNG")
    args = parser.parse_args()

    ref = Image.open(SOURCE_PNG).convert("RGB")
    navy, mint = sample_brand_colors(ref)
    print(f"sampled colors: navy {navy}, mint {mint}")

    svgs = build_svgs(navy, mint, trace_wordmark(ref))
    for name, content in svgs.items():
        (BRAND_DIR / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote assets/brand/{name}")
    build_rasters(svgs, navy, args.compare)
    print("wrote favicons, app icons and social-preview.png")


if __name__ == "__main__":
    main()
