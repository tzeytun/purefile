"""Thin wrappers for running the external command-line tools.

All tools are invoked with explicit argument lists (never through a shell) and
a timeout, so file names can never be interpreted as commands or options.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from purefile.config import get_settings


class ToolError(RuntimeError):
    """An external tool is missing, timed out or failed."""


def resolve(executable: str) -> str | None:
    """Return the absolute path of ``executable``, or ``None`` if it is not installed."""
    return shutil.which(executable)


def run(
    args: Sequence[str | Path],
    *,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a tool and capture its output.

    Raises:
        ToolError: if the executable is missing, times out, or (with ``check``)
            exits with a non-zero status.
    """
    argv = [str(a) for a in args]
    executable = resolve(argv[0])
    if executable is None:
        raise ToolError(f"required tool not found: {argv[0]}")
    argv[0] = executable
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            timeout=timeout or get_settings().tool_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{Path(argv[0]).name} timed out") from exc
    if check and result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise ToolError(f"{Path(argv[0]).name} failed ({result.returncode}): {stderr[-500:]}")
    return result
