"""c2patool output parsing (the tool itself is faked)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from purefile.scan import c2pa

V2_STORE = {
    "active_manifest": "urn:b",
    "manifests": {
        "urn:a": {"claim_generator": "Old Tool/1.0"},
        "urn:b": {
            "claim_generator_info": [
                {"name": "Image Generator", "version": "3.1"},
                {"name": "SDK"},
            ],
            "signature_info": {"issuer": "Example CA"},
            "assertions": [
                {"label": "c2pa.thumbnail.claim.jpeg", "data": {}},
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "uri/trainedAlgorithmicMedia",
                            },
                            {
                                "action": "c2pa.edited",
                                "digitalSourceType": "uri/trainedAlgorithmicMedia",
                            },
                        ]
                    },
                },
            ],
        },
    },
    "validation_state": "Valid",
}


def fake_run(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str = "", stderr: str = ""
) -> None:
    def run(args: Any, **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, returncode, stdout.encode(), stderr.encode())

    monkeypatch.setattr(c2pa.tools, "run", run)


def test_parses_active_v2_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, 0, json.dumps(V2_STORE))
    info = c2pa.inspect(Path("x.jpg"))
    assert info.present
    assert info.claim_generator == "Image Generator 3.1, SDK"
    assert info.issuer == "Example CA"
    assert info.validation_state == "Valid"
    assert info.digital_source_types == ["uri/trainedAlgorithmicMedia"]


def test_parses_v1_claim_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    store = {
        "active_manifest": "urn:a",
        "manifests": {"urn:a": {"claim_generator": "Old Tool/1.0"}},
    }
    fake_run(monkeypatch, 0, json.dumps(store))
    assert c2pa.inspect(Path("x.jpg")).claim_generator == "Old Tool/1.0"


def test_no_claim_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, 1, stderr="Error: No claim found")
    info = c2pa.inspect(Path("x.jpg"))
    assert not info.present and info.error is None


def test_tool_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, 1, stderr="Error: type is unsupported")
    info = c2pa.inspect(Path("x.gif"))
    assert not info.present and info.error == "Error: type is unsupported"


def test_unreadable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, 0, "not json")
    assert c2pa.inspect(Path("x.jpg")).error == "unreadable c2patool output"
