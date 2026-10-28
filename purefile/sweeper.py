"""Background job that deletes stale uploads.

A job counts as stale when none of its files changed for ``file_ttl_seconds``.
Using the newest modification time (rather than the creation time) keeps a
slow, still-running upload of a large video from being deleted mid-transfer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from pathlib import Path

from purefile.config import get_settings
from purefile.storage import JOB_ID, job_root

log = logging.getLogger(__name__)


def _last_activity(job_dir: Path) -> float:
    times = [job_dir.stat().st_mtime]
    for child in job_dir.iterdir():
        with contextlib.suppress(OSError):
            times.append(child.stat().st_mtime)
    return max(times)


def sweep(max_age: float | None = None, now: float | None = None) -> int:
    """Delete stale job directories and return how many were removed."""
    max_age = get_settings().file_ttl_seconds if max_age is None else max_age
    now = time.time() if now is None else now
    removed = 0
    for job_dir in job_root().iterdir():
        if not (job_dir.is_dir() and JOB_ID.match(job_dir.name)):
            continue
        try:
            stale = now - _last_activity(job_dir) > max_age
        except OSError:
            continue  # deleted concurrently
        if stale:
            shutil.rmtree(job_dir, ignore_errors=True)
            removed += 1
    if removed:
        log.info("cleanup removed %d expired job(s)", removed)
    return removed


async def run_forever() -> None:
    """Sweep periodically until cancelled."""
    interval = get_settings().sweep_interval_seconds
    while True:
        try:
            await asyncio.to_thread(sweep)
        except Exception:
            log.exception("cleanup sweep failed")
        await asyncio.sleep(interval)
