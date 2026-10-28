"""HTTP API.

Uploads are sent as the raw request body (not multipart) so they can be
streamed straight into the job directory while the size limit is enforced,
without an intermediate spooled copy. The original file name travels in the
``X-File-Name`` header (URL-encoded) and is never logged.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.requests import ClientDisconnect

from purefile import pipeline, storage
from purefile.clean import CleanError
from purefile.config import get_settings
from purefile.formats import SNIFF_BYTES, Format, UnsupportedFormatError, detect
from purefile.storage import Job, JobNotFoundError
from purefile.tools import ToolError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

NO_STORE = {"Cache-Control": "no-store"}
MAX_ZIP_FILES = 200


def api_error(status: int, code: str, message: str) -> HTTPException:
    """An error the UI can localize by ``code``."""
    return HTTPException(status, detail={"code": code, "message": message})


@router.get("/config")
def config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "max_image_mb": settings.max_image_mb,
        "max_video_mb": settings.max_video_mb,
        "file_ttl_seconds": settings.file_ttl_seconds,
        "formats": [f.value for f in Format],
    }


async def _receive(request: Request, job: Job) -> Format:
    """Stream the request body into the job, enforcing the per-type size limit."""
    settings = get_settings()
    fmt: Format | None = None
    limit = max(settings.max_image_bytes, settings.max_video_bytes)
    head = b""
    size = 0
    with job.upload_path.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if fmt is None:
                head += chunk
                if len(head) >= SNIFF_BYTES:
                    fmt = _identify(head)
                    limit = settings.max_video_bytes if fmt.is_video else settings.max_image_bytes
            if size > limit:
                raise _too_large(fmt)
            fh.write(chunk)
    if size == 0:
        raise api_error(400, "empty", "The file is empty.")
    if fmt is None:
        fmt = _identify(head)
        if size > (settings.max_video_bytes if fmt.is_video else settings.max_image_bytes):
            raise _too_large(fmt)
    job.format = fmt.value
    job.upload_path.rename(job.input_path)
    return fmt


def _identify(head: bytes) -> Format:
    try:
        return detect(head)
    except UnsupportedFormatError as exc:
        raise api_error(415, "unsupported_type", "This file type is not supported.") from exc


def _too_large(fmt: Format | None) -> HTTPException:
    settings = get_settings()
    limit = settings.max_video_mb if fmt is None or fmt.is_video else settings.max_image_mb
    return api_error(413, "too_large", f"The file is larger than {limit} MB.")


@router.post("/files")
async def upload(request: Request, x_file_name: str = Header("")) -> dict[str, Any]:
    """Receive one file, clean it, verify it, and report what was found."""
    settings = get_settings()
    declared = request.headers.get("content-length")
    if (
        declared
        and declared.isdigit()
        and int(declared) > max(settings.max_image_bytes, settings.max_video_bytes)
    ):
        raise _too_large(None)

    original_name = unquote(x_file_name)[:255]
    job = await run_in_threadpool(storage.create_job, original_name)
    try:
        fmt = await _receive(request, job)
        async with request.app.state.job_slots:
            result = await run_in_threadpool(pipeline.process, job.input_path, job.output_path, fmt)
        size_before = job.input_path.stat().st_size
        job.input_path.unlink()  # only the clean copy is kept, until it is downloaded
        job.clean_name = storage.clean_filename(original_name, fmt)
        job.save()
    except ClientDisconnect:
        storage.delete_job(job.id)
        raise api_error(400, "aborted", "The upload was interrupted.") from None
    except HTTPException:
        storage.delete_job(job.id)
        raise
    except CleanError as exc:
        storage.delete_job(job.id)
        log.warning("cleaning failed: %s", exc)
        raise api_error(422, "clean_failed", "The file could not be cleaned safely.") from exc
    except (ToolError, OSError) as exc:
        storage.delete_job(job.id)
        log.error("processing error: %s", exc)
        raise api_error(500, "server_error", "Processing failed on the server.") from exc

    return {
        "id": job.id,
        "name": original_name,
        "clean_name": job.clean_name,
        "format": fmt.value,
        "kind": "video" if fmt.is_video else "image",
        "size_before": size_before,
        "size_after": job.output_path.stat().st_size,
        "before": result.before.to_dict(),
        "after": result.after.to_dict(),
        "download_url": f"/api/files/{job.id}/download",
    }


def _ready_job(job_id: str) -> Job:
    try:
        job = storage.load_job(job_id)
        if job.clean_name and job.output_path.is_file():
            return job
    except JobNotFoundError:
        pass
    raise api_error(404, "not_found", "This file has expired or was already downloaded.")


@router.get("/files/{job_id}/download")
def download(job_id: str) -> FileResponse:
    """Send the clean file once, then delete it."""
    job = _ready_job(job_id)
    return FileResponse(
        job.output_path,
        media_type=job.fmt.mime_type,
        filename=job.clean_name or job.output_path.name,
        headers=NO_STORE,
        background=BackgroundTask(storage.delete_job, job.id),
    )


@router.delete("/files/{job_id}", status_code=204)
def delete(job_id: str) -> Response:
    storage.delete_job(job_id)
    return Response(status_code=204)


class _Sink(io.RawIOBase):
    """Write-only buffer that ``zipfile`` writes into while we stream it out."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        self._buffer += data
        return len(data)

    def take(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 1
    while candidate.lower() in used:
        n += 1
        stem, dot, ext = name.rpartition(".")
        candidate = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
    used.add(candidate.lower())
    return candidate


def _zip_stream(jobs: list[Job]) -> Iterator[bytes]:
    """Stream a ZIP of the clean files without writing it to disk.

    Entries are stored (media is already compressed) and get the fixed ZIP
    epoch as their timestamp, so the archive adds no metadata of its own.
    """
    sink = _Sink()
    used: set[str] = set()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for job in jobs:
            info = zipfile.ZipInfo(_unique(job.clean_name or job.id, used))
            with (
                job.output_path.open("rb") as src,
                archive.open(info, "w", force_zip64=True) as dst,
            ):
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
                    yield sink.take()
    yield sink.take()


@router.get("/zip")
def download_zip(ids: str = Query(..., max_length=MAX_ZIP_FILES * 33)) -> StreamingResponse:
    """Send several clean files as one ZIP, then delete them."""
    job_ids = list(dict.fromkeys(i for i in ids.split(",") if i))
    jobs = []
    for job_id in job_ids[:MAX_ZIP_FILES]:
        try:
            jobs.append(_ready_job(job_id))
        except HTTPException:
            continue  # expired files are skipped
    if not jobs:
        raise api_error(404, "not_found", "These files have expired or were already downloaded.")

    def cleanup() -> None:
        for job in jobs:
            storage.delete_job(job.id)

    return StreamingResponse(
        _zip_stream(jobs),
        media_type="application/zip",
        headers={**NO_STORE, "Content-Disposition": 'attachment; filename="purefile.zip"'},
        background=BackgroundTask(cleanup),
    )
