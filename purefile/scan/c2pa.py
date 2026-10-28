"""Inspect C2PA / Content Credentials manifests with c2patool."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from purefile import tools
from purefile.config import get_settings


@dataclass
class C2PAInfo:
    """Summary of the active C2PA manifest in a file."""

    present: bool = False
    claim_generator: str | None = None
    issuer: str | None = None
    validation_state: str | None = None
    digital_source_types: list[str] = field(default_factory=list)
    error: str | None = None


def available() -> bool:
    return tools.resolve(get_settings().c2patool_path) is not None


def inspect(path: Path) -> C2PAInfo:
    """Run c2patool on ``path`` and summarize its active manifest.

    A missing manifest is not an error. If c2patool cannot read the file at
    all, ``error`` is set and ``present`` is ``False``; callers combine this
    with the structural checks done by the cleaners.
    """
    result = tools.run([get_settings().c2patool_path, path], check=False)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        if "no claim found" in stderr.lower() or "no manifest" in stderr.lower():
            return C2PAInfo()
        return C2PAInfo(error=stderr[-300:] or f"c2patool exited with {result.returncode}")
    try:
        store: dict[str, Any] = json.loads(stdout)
    except json.JSONDecodeError:
        return C2PAInfo(error="unreadable c2patool output")
    return _summarize(store)


def _summarize(store: dict[str, Any]) -> C2PAInfo:
    manifests: dict[str, Any] = store.get("manifests") or {}
    manifest: dict[str, Any] = manifests.get(store.get("active_manifest") or "") or next(
        iter(manifests.values()), {}
    )
    info = C2PAInfo(present=True, validation_state=store.get("validation_state"))
    info.claim_generator = _claim_generator(manifest)
    signature = manifest.get("signature_info") or {}
    info.issuer = signature.get("issuer") or signature.get("common_name")
    for assertion in manifest.get("assertions") or []:
        if not str(assertion.get("label", "")).startswith("c2pa.actions"):
            continue
        for action in (assertion.get("data") or {}).get("actions") or []:
            source_type = action.get("digitalSourceType")
            if source_type and source_type not in info.digital_source_types:
                info.digital_source_types.append(source_type)
    return info


def _claim_generator(manifest: dict[str, Any]) -> str | None:
    """Readable claim generator from a v1 (string) or v2 (info list) claim."""
    if generator := manifest.get("claim_generator"):
        return str(generator)
    infos = manifest.get("claim_generator_info") or []
    names = [
        " ".join(str(part) for part in (info.get("name"), info.get("version")) if part)
        for info in infos
        if isinstance(info, dict)
    ]
    return ", ".join(name for name in names if name) or None
