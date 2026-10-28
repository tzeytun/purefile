## What and why

<!-- What does this change, and what problem does it solve? Link issues with "Fixes #123". -->

## Checklist

- [ ] No re-encoding: pixel data / media streams stay byte-identical (tests prove it)
- [ ] `ruff check .`, `ruff format --check .`, `mypy` and `pytest` pass (Docker: `docker compose --profile test run --build --rm test`)
- [ ] Tests added or updated, using generated fixtures (no photos or videos committed)
- [ ] UI strings added to both `web/locales/en.json` and `tr.json`
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-visible changes
- [ ] Commits follow Conventional Commits
