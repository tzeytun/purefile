# Contributing to Purefile

Thanks for helping! Bug reports, fixes, new format support and translations
are all welcome. By participating you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## The one rule

Purefile's promise is **zero quality loss**: pixel data and audio/video
streams must stay byte-identical, and nothing may be re-encoded. A change that
decodes and re-encodes media will not be accepted. New cleaners need tests that
prove the coded image data or stream hashes are unchanged.

## Setup

You need Python 3.12+, [exiftool](https://exiftool.org), [ffmpeg](https://ffmpeg.org)
and [c2patool](https://github.com/contentauth/c2pa-rs/releases) on your `PATH`
(or set `PUREFILE_*_PATH`, see `.env.example`), plus Node 20+ for the CSS.

```bash
git clone https://github.com/tzeytun/purefile.git
cd purefile
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
npm ci && npm run build:css
uvicorn purefile.main:app --reload                  # http://127.0.0.1:8000
```

Don't want to install the tools? Use Docker for everything:

```bash
docker compose up --build                      # run the app
docker compose --profile test run --build --rm test   # lint, types and tests
```

## Running the checks

```bash
ruff check . && ruff format --check .   # lint and formatting
mypy                                    # strict type checking
pytest --cov                            # tests (integration tests need the tools)
```

Tests that need exiftool, c2patool or ffmpeg are skipped when a tool is
missing, so run the suite in Docker (or CI) before opening a pull request.

Test files are generated, never committed: `python scripts/make_fixtures.py`
writes synthetic images and videos to `build/fixtures/`. **Do not add photos or
videos to the repository** unless their license clearly allows it.

## Branches and commits

- Branch from `main` and name branches `type/short-description`, for example
  `feat/avif-support`, `fix/png-trailing-data`, `docs/readme-typo`.
- Write commits in [Conventional Commits](https://www.conventionalcommits.org/)
  style: `feat(clean): ...`, `fix(ui): ...`, `docs: ...`, `test: ...`,
  `chore: ...`, `refactor: ...`. Explain *why* in the body when it isn't obvious.
- Keep pull requests focused, and add a line to `CHANGELOG.md` under
  `[Unreleased]` for user-visible changes.

## Code style

- Type hints everywhere (`mypy --strict` must pass); ruff decides formatting.
- Comment *why*, not *what*. Match the surrounding code.
- No hardcoded paths, no network calls at runtime, no analytics.
- Never log file names, contents or metadata values.

## Translations

UI strings live in `web/locales/<lang>.json`. To add a language, copy
`en.json`, translate the values (keep the `{placeholders}`), add the code to
`SUPPORTED` in `web/js/i18n.js` and a button in `web/index.html`.

## Regenerating screenshots and brand assets

After UI changes: `pip install -e ".[dev,brand]"`, `python -m playwright install chromium`, then
`python scripts/capture_screenshots.py` (rebuilds `docs/images/`). Brand files are rebuilt with
`python scripts/build_brand.py`.

## Reporting security issues

Please don't open a public issue; see [SECURITY.md](SECURITY.md).
