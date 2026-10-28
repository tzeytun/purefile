# syntax=docker/dockerfile:1.7
#
# Purefile: one image with the app and every tool it needs (exiftool, ffmpeg,
# c2patool). Stages:
#   css     - builds the Tailwind stylesheet (Node is not shipped)
#   runtime - the production image (default)
#   test    - runtime + dev dependencies, runs ruff and pytest

# ---------------------------------------------------------------------------
FROM node:22-alpine AS css
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./web
RUN npm run build:css

# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS runtime

# c2patool is only published as an x86_64 Linux binary; the image targets linux/amd64.
ARG C2PATOOL_VERSION=0.27.22
ARG C2PATOOL_SHA256=6f138ad53da1a62f1cd6ee71c60727efa27d13b811f4c0ea8c2a8528968b358b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PUREFILE_TMP_DIR=/tmp/purefile \
    PUREFILE_WEB_DIR=/app/web

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg libimage-exiftool-perl ca-certificates curl; \
    curl -fsSL -o /tmp/c2patool.tar.gz \
      "https://github.com/contentauth/c2pa-rs/releases/download/c2patool-v${C2PATOOL_VERSION}/c2patool-v${C2PATOOL_VERSION}-x86_64-unknown-linux-gnu.tar.gz"; \
    echo "${C2PATOOL_SHA256}  /tmp/c2patool.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/c2patool.tar.gz -C /usr/local/bin --strip-components=1 c2patool/c2patool; \
    rm /tmp/c2patool.tar.gz; \
    apt-get purge -y curl; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    exiftool -ver; ffmpeg -version | head -n1; c2patool --version

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY purefile ./purefile
RUN pip install .

COPY web ./web
COPY --from=css /src/web/css/app.css ./web/css/app.css
COPY assets/brand ./assets/brand

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin purefile
USER purefile

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# No access log: request lines would record client IP addresses.
CMD ["uvicorn", "purefile.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]

# ---------------------------------------------------------------------------
FROM runtime AS test
USER root
COPY tests ./tests
COPY scripts ./scripts
RUN pip install -e ".[dev]"
USER purefile
ENV PUREFILE_TMP_DIR=/tmp/purefile-test \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    MYPY_CACHE_DIR=/tmp/mypy-cache \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    COVERAGE_FILE=/tmp/.coverage
CMD ["sh", "-c", "ruff check . && ruff format --check . && mypy && pytest -p no:cacheprovider --cov --cov-report=term-missing"]
