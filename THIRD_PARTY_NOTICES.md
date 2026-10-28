# Third-party notices

Purefile itself is released under the [MIT License](LICENSE). It relies on the
following third-party software and assets. Versions listed are the ones the
project was built and tested with; the Docker image installs the versions
pinned in the `Dockerfile` and `pyproject.toml`.

## External tools

Purefile runs these as separate programs (through `subprocess`); it does not
link against them or include their source code.

| Tool | Used for | License | Project |
| --- | --- | --- | --- |
| ExifTool 13.x (Debian `libimage-exiftool-perl`) | Reading metadata, cleaning HEIC/HEIF | [Perl Artistic License or GPL-1.0-or-later](https://exiftool.org/#license) | <https://exiftool.org> |
| FFmpeg 7.1 (Debian `ffmpeg`) | Remuxing MP4/MOV without re-encoding, ffprobe | See the note below | <https://ffmpeg.org> |
| c2patool 0.27.22 | Detecting and verifying C2PA manifests | MIT or Apache-2.0 (dual-licensed) | <https://github.com/contentauth/c2pa-rs> |

**FFmpeg's license depends on the build.** FFmpeg is LGPL-2.1-or-later by
default, but builds that enable GPL components are licensed GPL-2.0-or-later
(or GPL-3.0-or-later with `--enable-version3`). The Docker image uses Debian's
`ffmpeg` package, which is configured with `--enable-gpl`, so **the FFmpeg
binary in the image is covered by the GPL**. Purefile only invokes it as a
separate process, so Purefile's own code stays MIT. If you build your own
image with an LGPL-only FFmpeg, the LGPL applies instead. If you redistribute
the Docker image, you are redistributing Debian's FFmpeg and must honor its
license; its source is available from
<https://sources.debian.org/src/ffmpeg/>.

The image also contains Debian's base system and Python runtime, each under
their own licenses (see `/usr/share/doc/*/copyright` inside the image).

## Fonts (self-hosted in `web/fonts/`)

| Font | License | Source |
| --- | --- | --- |
| Outfit | [SIL Open Font License 1.1](web/fonts/OFL-Outfit.txt) | <https://github.com/Outfitio/Outfit-Fonts> |
| Inter | [SIL Open Font License 1.1](web/fonts/OFL-Inter.txt) | <https://github.com/rsms/inter> |

The files are subsets (Latin and Latin Extended-A) converted to WOFF2 by
`scripts/build_fonts.py`. The wordmark in the logo was vector-traced from the
project's reference logo and is not a font.

## Python dependencies (runtime)

| Package | License |
| --- | --- |
| fastapi | MIT |
| starlette | BSD-3-Clause |
| pydantic, pydantic-core | MIT |
| pydantic-settings | MIT |
| python-multipart | Apache-2.0 |
| uvicorn | BSD-3-Clause |
| h11 | MIT |
| click | BSD-3-Clause |
| httptools | MIT |
| watchfiles | MIT |
| websockets | BSD-3-Clause |
| PyYAML | MIT |
| python-dotenv | BSD-3-Clause |
| anyio | MIT |
| idna | BSD-3-Clause |
| annotated-types, annotated-doc, typing-extensions, typing-inspection | MIT, MIT, PSF-2.0, MIT |

## Python dependencies (development and tooling only, not in the runtime image)

| Package | License | Used by |
| --- | --- | --- |
| pytest, pytest-cov | MIT | tests |
| coverage | Apache-2.0 | tests |
| httpx | BSD-3-Clause | API tests |
| ruff, mypy | MIT | linting, type checks |
| Pillow | MIT-CMU (HPND) | fixtures, pixel comparison |
| pillow-heif | BSD-3-Clause (its wheels bundle libheif, LGPL-3.0, and other codecs) | fixtures, pixel comparison |
| fonttools, Brotli | MIT | `scripts/build_fonts.py`, `scripts/build_brand.py` |
| NumPy | BSD-3-Clause and others | `scripts/build_brand.py` |
| Playwright | Apache-2.0 | screenshots, brand rasterizing |
| potracer | GPL-2.0-or-later | `scripts/build_brand.py` (vector tracing of the logo) |

`potracer` is only used by a maintainer script that regenerates the logo SVG.
It is not imported by the application, not installed in the Docker image, and
none of its code is included in Purefile. The generated SVG files are original
artwork derived from the project's logo.

## JavaScript dependencies (build time only)

The frontend ships no third-party JavaScript. Tailwind CSS is used at build
time to generate `web/css/app.css`.

| Package | License |
| --- | --- |
| tailwindcss, @tailwindcss/cli (4.3.3) and their dependencies | MIT |

Run `npm ls --all` for the complete tree.

## Test certificate

`scripts/make_fixtures.py` signs C2PA manifests on synthetic test files with
the test certificate that ships with c2patool. It identifies no real person or
organization and is not trusted by any validator.
