# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-28

First public release.

### Added

- Lossless metadata removal, with no re-encoding, for JPEG, PNG, WebP,
  HEIC/HEIF, MP4 and MOV. EXIF, IPTC, XMP and C2PA / Content Credentials
  manifests are removed. ICC color profiles are kept, and a non-default
  orientation is preserved so photos and vertical videos still display upright.
- "Before" scan that groups the metadata found and highlights C2PA manifests
  (with the claim generator), IPTC/XMP `DigitalSourceType` values such as
  `trainedAlgorithmicMedia`, GPS locations, device, software and timestamps.
- Verification after cleaning with exiftool and c2patool; a file that still
  contains metadata is never returned.
- Web app with multi-file drag and drop, upload progress, per-file and ZIP
  downloads (`_pure` is appended to the file name), English and Turkish
  interface, dark mode and self-hosted fonts.
- Files are deleted right after download and by a cleanup job after 10
  minutes. No analytics, no tracking, no external requests at runtime.
- Docker image and `docker-compose.yml` with exiftool, ffmpeg and c2patool.
- Settings through `PUREFILE_*` environment variables (size limits, retention,
  concurrency).
- Test suite and `scripts/make_fixtures.py`, which generates synthetic test
  files, including C2PA manifests signed with c2patool's test certificate.
- Brand assets: SVG logos, favicons, app icons and a social preview image.

[Unreleased]: https://github.com/tzeytun/purefile/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tzeytun/purefile/releases/tag/v0.1.0
