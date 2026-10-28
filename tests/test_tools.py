"""Subprocess wrapper and settings."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from purefile import tools
from purefile.config import MB, get_settings


def test_missing_tool() -> None:
    with pytest.raises(tools.ToolError, match="not found"):
        tools.run(["definitely-not-a-real-tool-xyz"])


def test_failure_raises_with_stderr() -> None:
    with pytest.raises(tools.ToolError, match="boom"):
        tools.run([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])


def test_failure_without_check_returns_result() -> None:
    result = tools.run([sys.executable, "-c", "import sys; sys.exit(2)"], check=False)
    assert result.returncode == 2


def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(tools.subprocess, "run", slow)
    with pytest.raises(tools.ToolError, match="timed out"):
        tools.run([sys.executable, "-c", "pass"], timeout=1)


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUREFILE_MAX_IMAGE_MB", "5")
    monkeypatch.setenv("PUREFILE_MAX_VIDEO_MB", "7")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.max_image_bytes == 5 * MB
    assert settings.max_video_bytes == 7 * MB
