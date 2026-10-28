"""Regenerate every README screenshot and the demo GIF.

Starts the app on a free local port with a throwaway working directory, builds
synthetic fixtures, drives the UI with Playwright and writes the images to
``docs/images/``. Re-run it after any UI change.

Usage:
    python scripts/capture_screenshots.py

Requires the dev and brand extras (``pip install -e ".[dev,brand]"``), Chromium
for Playwright (``python -m playwright install chromium``), and exiftool,
c2patool and ffmpeg (see ``.env.example``).
"""

from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import make_fixtures
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from purefile.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 844}
GIF_VIEWPORT = {"width": 960, "height": 600}

# Fixtures shown in screenshots (in card order) and the one used for the GIF.
HERO_FILES = ["ai-render.png", "photo.jpg", "clip.mp4"]
GIF_FILE = "ai-render.png"

# Drop events need real File objects; build them in the page from base64 so the
# drag-over highlight and the drop handler run exactly as for a user.
DROP_JS = """
async ({name, data, type}) => {
  const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
  const dt = new DataTransfer();
  dt.items.add(new File([bytes], name, {type}));
  const init = {dataTransfer: dt, bubbles: true, cancelable: true};
  const fire = (kind) => document.dispatchEvent(new DragEvent(kind, init));
  fire('dragenter'); fire('dragover');
  await new Promise(r => setTimeout(r, 900));
  fire('drop');
}
"""
MIME = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
        ".heic": "image/heic", ".mp4": "video/mp4", ".mov": "video/quicktime"}  # fmt: skip


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_app(workdir: Path) -> Iterator[str]:
    """Run uvicorn against a throwaway directory and yield its base URL."""
    port = free_port()
    env = {**os.environ, "PUREFILE_TMP_DIR": str(workdir / "jobs")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "purefile.main:app", "--port", str(port),
         "--no-access-log"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            sys.exit("error: the app did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def new_context(
    browser: Browser, viewport: dict[str, int], scheme: str, **kwargs: object
) -> BrowserContext:
    # bypass_csp lets Playwright evaluate its helpers; the app's own CSP is
    # verified by the test suite and by the network assertion below.
    return browser.new_context(
        viewport=viewport,
        color_scheme=scheme,
        locale="en-US",
        bypass_csp=True,
        **kwargs,  # type: ignore[arg-type]
    )


def open_app(context: BrowserContext, url: str, external: list[str]) -> Page:
    page = context.new_page()
    page.on(
        "request",
        lambda r: external.append(r.url) if not r.url.startswith((url, "blob:", "data:")) else None,
    )
    page.goto(url)
    page.wait_for_function("document.fonts.status === 'loaded'")
    return page


def upload_and_wait(page: Page, paths: list[Path]) -> None:
    page.set_input_files("#file-input", [str(p) for p in paths])
    page.wait_for_function(
        f"document.querySelectorAll('#file-list > li [data-ref=status]').length === {len(paths)}"
        " && [...document.querySelectorAll('#file-list [data-ref=status]')]"
        ".every(s => s.textContent.includes('Clean'))",
        timeout=120_000,
    )
    page.wait_for_timeout(1200)  # let the peel animation finish


def shoot(page: Page, name: str, *, full_page: bool = False) -> None:
    page.screenshot(path=str(OUT / name), full_page=full_page)
    print(f"wrote docs/images/{name}")


def capture_stills(browser: Browser, url: str, fx: Path, external: list[str]) -> None:
    files = [fx / n for n in HERO_FILES]

    # Light desktop: hero (top of page with results) and the full page.
    context = new_context(browser, DESKTOP, "light")
    page = open_app(context, url, external)
    shoot(page, "empty-light.png")
    upload_and_wait(page, files)
    # Hero: tagline, drop zone and the first result card.
    page.screenshot(
        path=str(OUT / "hero.png"),
        full_page=True,
        clip={"x": 0, "y": 0, "width": 1280, "height": 1060},
    )
    print("wrote docs/images/hero.png")
    shoot(page, "light.png", full_page=True)

    # Before/after report: expand the AI-generated image's metadata list.
    page.locator("#file-list > li").first.scroll_into_view_if_needed()
    page.locator("#file-list > li").first.locator("summary").click()
    page.wait_for_timeout(300)
    page.locator("#file-list > li").first.screenshot(path=str(OUT / "report.png"))
    print("wrote docs/images/report.png")
    context.close()

    # Dark desktop.
    context = new_context(browser, DESKTOP, "dark")
    page = open_app(context, url, external)
    upload_and_wait(page, files)
    page.evaluate("window.scrollTo(0, 0)")
    shoot(page, "dark.png")
    context.close()

    # Mobile (2x for crisp text).
    context = new_context(
        browser, MOBILE, "light", device_scale_factor=2, is_mobile=True, has_touch=True
    )
    page = open_app(context, url, external)
    upload_and_wait(page, files[:2])
    page.evaluate("document.getElementById('workspace').scrollIntoView()")
    page.wait_for_timeout(300)
    shoot(page, "mobile.png")
    context.close()


def capture_demo(browser: Browser, url: str, fx: Path, external: list[str], workdir: Path) -> None:
    """Record a drop-and-clean session and convert it to a small GIF."""
    video_dir = workdir / "video"
    context = new_context(
        browser,
        GIF_VIEWPORT,
        "light",
        record_video_dir=str(video_dir),
        record_video_size=GIF_VIEWPORT,
    )
    page = open_app(context, url, external)
    page.wait_for_timeout(900)
    source = fx / GIF_FILE
    page.evaluate(
        DROP_JS,
        {
            "name": source.name,
            "data": base64.b64encode(source.read_bytes()).decode(),
            "type": MIME[source.suffix],
        },
    )
    page.wait_for_function(
        "[...document.querySelectorAll('#file-list [data-ref=status]')]"
        ".some(s => s.textContent.includes('Clean'))",
        timeout=60_000,
    )
    page.wait_for_timeout(1000)
    page.locator("#file-list > li").first.locator("summary").click()
    page.wait_for_timeout(1800)
    context.close()  # flushes the video

    recording = next(video_dir.glob("*.webm"))
    palette = workdir / "palette.png"
    scale = "fps=12,scale=800:-1:flags=lanczos"
    ffmpeg = shutil.which(get_settings().ffmpeg_path) or "ffmpeg"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(recording),
         "-vf", f"{scale},palettegen=max_colors=96", str(palette)],
        check=True,
    )  # fmt: skip
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(recording), "-i", str(palette),
         "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
         "-loop", "0", str(OUT / "demo.gif")],
        check=True,
    )  # fmt: skip
    print(f"wrote docs/images/demo.gif ({(OUT / 'demo.gif').stat().st_size // 1024} KB)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="purefile-shots-") as tmp:
        workdir = Path(tmp)
        fx = workdir / "fixtures"
        make_fixtures.generate(fx)
        external: list[str] = []
        with running_app(workdir) as url, sync_playwright() as p:
            browser = p.chromium.launch()
            capture_stills(browser, url, fx, external)
            capture_demo(browser, url, fx, external, workdir)
            browser.close()
    if external:
        sys.exit(f"error: the app made requests to other origins: {sorted(set(external))}")
    print("verified: no requests left the app's own origin")


if __name__ == "__main__":
    main()
