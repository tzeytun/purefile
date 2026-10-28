"""Short-lived per-upload working directories.

Every upload gets its own directory named by a random 128-bit id. The id is
the only handle a client ever sees; it cannot be guessed and never contains
user input. Nothing here is permanent: a job is deleted right after its
download, and :mod:`purefile.sweeper` removes anything left behind.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from purefile.config import get_settings
from purefile.formats import Format

JOB_ID = re.compile(r"^[0-9a-f]{32}$")
JOB_FILE = "job.json"
MAX_STEM_LENGTH = 120

# Extensions accepted as-is for each format (otherwise the canonical one is used).
EXTENSIONS: dict[Format, set[str]] = {
    Format.JPEG: {".jpg", ".jpeg", ".jpe", ".jfif"},
    Format.PNG: {".png"},
    Format.WEBP: {".webp"},
    Format.HEIF: {".heic", ".heif", ".hif"},
    Format.MP4: {".mp4", ".m4v"},
    Format.MOV: {".mov", ".qt"},
}


class JobNotFoundError(LookupError):
    """No job with that id exists (anymore)."""


@dataclass
class Job:
    id: str
    created: float
    original_name: str = ""
    format: str | None = None
    clean_name: str | None = None

    @property
    def dir(self) -> Path:
        return job_root() / self.id

    @property
    def upload_path(self) -> Path:
        """Where the upload is streamed before its format is known."""
        return self.dir / "upload.part"

    @property
    def input_path(self) -> Path:
        # exiftool and c2patool pick a parser by extension, so use the real one.
        return self.dir / f"input{self.fmt.extension}"

    @property
    def output_path(self) -> Path:
        return self.dir / f"output{self.fmt.extension}"

    @property
    def fmt(self) -> Format:
        if self.format is None:
            raise JobNotFoundError(f"{self.id} has not been identified yet")
        return Format(self.format)

    def save(self) -> None:
        (self.dir / JOB_FILE).write_text(json.dumps(asdict(self)), encoding="utf-8")


def job_root() -> Path:
    root = get_settings().tmp_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_job(original_name: str) -> Job:
    job = Job(id=uuid.uuid4().hex, created=time.time(), original_name=original_name)
    job.dir.mkdir(mode=0o700)
    job.save()
    return job


def load_job(job_id: str) -> Job:
    if not JOB_ID.match(job_id):
        raise JobNotFoundError(job_id)
    try:
        data = json.loads((job_root() / job_id / JOB_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JobNotFoundError(job_id) from exc
    return Job(**data)


def delete_job(job_id: str) -> None:
    if JOB_ID.match(job_id):
        shutil.rmtree(job_root() / job_id, ignore_errors=True)


def clean_filename(original_name: str, fmt: Format) -> str:
    """``holiday.JPG`` -> ``holiday_pure.JPG``; unsafe characters are removed."""
    # Browsers may send full paths; keep only the final component (either separator).
    name = PureWindowsPath(PurePosixPath(original_name).name).name
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"/\\|?*')
    path = PurePosixPath(name.strip(" ."))
    suffix = path.suffix if path.suffix.lower() in EXTENSIONS[fmt] else fmt.extension
    stem = (path.stem if path.suffix else path.name).strip(" .")[:MAX_STEM_LENGTH] or "file"
    return f"{stem}_pure{suffix}"
