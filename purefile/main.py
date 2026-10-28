"""FastAPI application: API routes, static frontend, cleanup job, security headers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from purefile import __version__, sweeper, tools
from purefile.api import router
from purefile.config import get_settings

log = logging.getLogger(__name__)

# The frontend only ever talks to its own origin; object URLs show local previews.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' blob: data:",
        "media-src 'self' blob:",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.job_slots = asyncio.Semaphore(settings.max_concurrent_jobs)
    for name in ("exiftool", "ffmpeg", "ffprobe", "c2patool"):
        if tools.resolve(getattr(settings, f"{name}_path")) is None:
            log.warning("%s not found: some files cannot be processed", name)
    await asyncio.to_thread(sweeper.sweep)  # leftovers from a previous run
    task = asyncio.create_task(sweeper.run_forever())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    settings = get_settings()
    # No /docs: the Swagger UI would load scripts from a CDN.
    app = FastAPI(
        title="Purefile",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, object]:
        missing = [
            name
            for name in ("exiftool", "ffmpeg", "ffprobe", "c2patool")
            if tools.resolve(getattr(settings, f"{name}_path")) is None
        ]
        return {"status": "ok" if not missing else "degraded", "missing_tools": missing}

    app.include_router(router)
    brand_dir = settings.web_dir.parent / "assets" / "brand"
    if brand_dir.is_dir():
        app.mount("/brand", StaticFiles(directory=brand_dir), name="brand")
    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = create_app()
