# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately with GitHub's built-in reporting:

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the problem and how to reproduce it.

If you can, include the affected version or commit, the steps or a proof of
concept, and what an attacker could achieve. Do not attach real personal
photos; synthetic files (see `scripts/make_fixtures.py`) are preferred.

You can expect an acknowledgement within a few days. Fixes are developed
privately and released together with a security advisory crediting you,
unless you prefer to stay anonymous.

## Scope

In scope:

- Anything that lets an uploaded file read, write or delete other files,
  or run commands (path traversal, argument injection, unsafe parsing, ...).
- Uploaded files or their metadata surviving past download or the cleanup
  time limit, or being exposed to other users.
- Cleaned files that still contain metadata Purefile claims to remove.
- Denial of service through a single small request (for example a crafted
  file that makes a cleaner use unbounded memory or time).
- Requests the app makes to external hosts at runtime.

Out of scope:

- Invisible watermarks embedded in pixels. Purefile removes metadata only.
- Vulnerabilities in exiftool, FFmpeg or c2patool themselves. Report those
  upstream; we will update the Docker image once a fix is released.
- Volume-based denial of service against a self-hosted instance. Put a rate
  limit and authentication in front of any instance exposed to the internet.

## Supported versions

Only the latest release receives security fixes while the project is at 0.x.
