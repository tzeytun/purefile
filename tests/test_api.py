"""HTTP API, job storage and the cleanup sweeper."""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from purefile import pipeline, storage, sweeper
from purefile.clean import CleanError
from purefile.clean.base import Changes
from purefile.config import get_settings
from purefile.formats import Format
from purefile.main import create_app
from purefile.scan.report import Report
from tests.conftest import requires_tools


def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "teal").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "jobs"
    monkeypatch.setenv("PUREFILE_TMP_DIR", str(root))
    monkeypatch.setenv("PUREFILE_MAX_IMAGE_MB", "1")
    monkeypatch.setenv("PUREFILE_MAX_VIDEO_MB", "2")
    get_settings.cache_clear()
    return root


@pytest.fixture
def client(tmp_root: Path) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace scanning/cleaning with a copy so API tests need no external tools."""

    def process(src: Path, dst: Path, fmt: Format) -> pipeline.Result:
        shutil.copyfile(src, dst)
        return pipeline.Result(fmt, Report(total=3), Report(), Changes())

    monkeypatch.setattr(pipeline, "process", process)


def upload(client: TestClient, data: bytes, name: str = "Holiday photo.JPG") -> dict[str, object]:
    response = client.post("/api/files", content=data, headers={"X-File-Name": quote(name)})
    return {"status": response.status_code, **response.json()}


def test_config(client: TestClient) -> None:
    data = client.get("/api/config").json()
    assert data["max_image_mb"] == 1 and data["max_video_mb"] == 2
    assert "heif" in data["formats"]


@pytest.mark.usefixtures("fake_pipeline")
def test_upload_and_download_once(client: TestClient, tmp_root: Path) -> None:
    data = jpeg_bytes()
    result = upload(client, data)
    assert result["status"] == 200
    assert result["clean_name"] == "Holiday photo_pure.JPG"
    assert result["format"] == "jpeg" and result["kind"] == "image"
    assert result["before"]["total"] == 3 and result["after"]["clean"] is True
    job_dir = tmp_root / str(result["id"])
    assert [p.name for p in job_dir.iterdir() if p.name != "job.json"] == ["output.jpg"]

    response = client.get(str(result["download_url"]))
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/jpeg"
    assert "Holiday%20photo_pure.JPG" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert not job_dir.exists()  # deleted right after the download
    assert client.get(str(result["download_url"])).json()["detail"]["code"] == "not_found"


@pytest.mark.usefixtures("fake_pipeline")
def test_zip_download(client: TestClient, tmp_root: Path) -> None:
    ids = [upload(client, jpeg_bytes(), "same.jpg")["id"] for _ in range(3)]
    response = client.get("/api/zip", params={"ids": ",".join(map(str, ids)) + ",bogus"})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert names == ["same_pure.jpg", "same_pure (2).jpg", "same_pure (3).jpg"]
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert archive.read(names[0]) == jpeg_bytes()
    assert list(tmp_root.iterdir()) == []


def test_zip_of_nothing(client: TestClient) -> None:
    assert client.get("/api/zip", params={"ids": "0" * 32}).status_code == 404


@pytest.mark.usefixtures("fake_pipeline")
def test_delete(client: TestClient, tmp_root: Path) -> None:
    job_id = upload(client, jpeg_bytes())["id"]
    assert client.delete(f"/api/files/{job_id}").status_code == 204
    assert not (tmp_root / str(job_id)).exists()
    # Ids are validated before any filesystem access; traversal attempts are no-ops.
    outside = tmp_root.parent / "keep-me"
    outside.mkdir()
    storage.delete_job("../keep-me")
    assert client.delete("/api/files/..%2Fkeep-me").status_code in (204, 404, 405)
    assert outside.exists()


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"GIF89a" + bytes(100), 415, "unsupported_type"),
        (b"", 400, "empty"),
        (b"\xff\xd8\xff" + bytes(1024 * 1024), 413, "too_large"),
        (b"\xff\xd8\xff", 422, "clean_failed"),
    ],
    ids=["unsupported", "empty", "image-too-large", "corrupt"],
)
def test_upload_errors(
    client: TestClient,
    tmp_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    status: int,
    code: str,
) -> None:
    def failing(src: Path, dst: Path, fmt: Format) -> pipeline.Result:
        raise CleanError("corrupt")

    monkeypatch.setattr(pipeline, "process", failing)
    result = upload(client, data)
    assert result["status"] == status
    assert result["detail"]["code"] == code  # type: ignore[index]
    assert list(tmp_root.iterdir()) == []  # nothing is left behind


@pytest.mark.usefixtures("fake_pipeline")
def test_video_limit_applies_to_videos(client: TestClient) -> None:
    mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomavc1" + bytes(1024 * 1024 + 100)
    assert upload(client, mp4, "clip.mp4")["status"] == 200  # over the image limit, under video
    too_big = mp4 + bytes(1024 * 1024)
    assert upload(client, too_big, "clip.mp4")["status"] == 413


def test_security_headers_and_no_docs(client: TestClient) -> None:
    response = client.get("/api/config")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert client.get("/docs").status_code == 404


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] in ("ok", "degraded")


def test_frontend_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text


@requires_tools
def test_end_to_end_with_real_tools(client: TestClient, fixtures_dir: Path) -> None:
    result = upload(client, (fixtures_dir / "photo.jpg").read_bytes(), "photo.jpg")
    assert result["status"] == 200
    assert result["before"]["c2pa"]["present"] is True  # type: ignore[index]
    assert result["after"]["clean"] is True  # type: ignore[index]
    assert "orientation" in result["after"]["kept"]  # type: ignore[index]
    assert client.get(str(result["download_url"])).status_code == 200


# --- Storage ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "fmt", "expected"),
    [
        ("holiday.jpg", Format.JPEG, "holiday_pure.jpg"),
        ("IMG_0001.JPEG", Format.JPEG, "IMG_0001_pure.JPEG"),
        ("photo.png", Format.JPEG, "photo_pure.jpg"),  # content wins over a wrong extension
        ("C:\\Users\\me\\Desktop\\clip.MOV", Format.MOV, "clip_pure.MOV"),
        ("../../etc/passwd", Format.PNG, "passwd_pure.png"),
        ('bad<>:"|?*name.webp', Format.WEBP, "badname_pure.webp"),
        ("", Format.HEIF, "file_pure.heic"),
        ("çiçek fotoğrafı.heic", Format.HEIF, "çiçek fotoğrafı_pure.heic"),  # noqa: RUF001
        ("noext", Format.MP4, "noext_pure.mp4"),
    ],
)
def test_clean_filename(name: str, fmt: Format, expected: str) -> None:
    assert storage.clean_filename(name, fmt) == expected


def test_clean_filename_is_bounded() -> None:
    assert len(storage.clean_filename("x" * 1000 + ".jpg", Format.JPEG)) <= 130


@pytest.mark.usefixtures("tmp_root")
def test_load_job_rejects_bad_ids() -> None:
    for bad in ("../x", "A" * 32, "0" * 31, ""):
        with pytest.raises(storage.JobNotFoundError):
            storage.load_job(bad)
    with pytest.raises(storage.JobNotFoundError):
        storage.load_job("0" * 32)  # well-formed but unknown


@pytest.mark.usefixtures("tmp_root")
def test_job_roundtrip() -> None:
    job = storage.create_job("a.jpg")
    job.format = "jpeg"
    job.save()
    loaded = storage.load_job(job.id)
    assert loaded.fmt is Format.JPEG and loaded.input_path.name == "input.jpg"
    with pytest.raises(storage.JobNotFoundError):
        _ = storage.Job(id=job.id, created=0).fmt


# --- Sweeper ---------------------------------------------------------------------


@pytest.mark.usefixtures("tmp_root")
def test_sweeper_removes_only_stale_jobs(tmp_root: Path) -> None:
    stale, fresh = storage.create_job("old.jpg"), storage.create_job("new.jpg")
    old = time.time() - 3600
    for path in (stale.dir, *stale.dir.iterdir()):
        os.utime(path, (old, old))
    unrelated = tmp_root / "not-a-job"
    unrelated.mkdir()
    os.utime(unrelated, (old, old))

    assert sweeper.sweep(max_age=600) == 1
    assert not stale.dir.exists() and fresh.dir.exists() and unrelated.exists()


@pytest.mark.usefixtures("tmp_root")
def test_sweeper_keeps_uploads_in_progress() -> None:
    job = storage.create_job("big.mp4")
    old = time.time() - 3600
    os.utime(job.dir, (old, old))
    (job.dir / "upload.part").write_bytes(b"still arriving")  # recent activity
    assert sweeper.sweep(max_age=600) == 0


@pytest.mark.usefixtures("tmp_root")
def test_run_forever_sweeps_until_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def sweep() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("a failing sweep must not stop the loop")
        return 0

    monkeypatch.setattr(sweeper, "sweep", sweep)
    monkeypatch.setenv("PUREFILE_SWEEP_INTERVAL_SECONDS", "5")
    monkeypatch.setattr(sweeper.asyncio, "sleep", _fast_sleep)

    async def main() -> None:
        task = asyncio.create_task(sweeper.run_forever())
        while len(calls) < 2:
            await _real_sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert len(calls) >= 2


_real_sleep = asyncio.sleep


async def _fast_sleep(_: float) -> None:
    await _real_sleep(0)
