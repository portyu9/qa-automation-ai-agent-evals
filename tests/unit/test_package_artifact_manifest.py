from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "package_artifact_manifest.py"
_REPOSITORY = "portyu9/qa-automation-ai-agent-evals"
_COMMIT = "a" * 40
_WORKFLOW = "CI"
_RUN_ID = "12345"
_RUN_ATTEMPT = "1"


def _artifact_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "qa_automation_ai_agent_evals-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "qa_automation_ai_agent_evals-0.1.0.tar.gz").write_bytes(b"sdist")
    return dist


def _run(
    dist: Path,
    mode: str,
    *,
    commit: str = _COMMIT,
    run_attempt: str = _RUN_ATTEMPT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            mode,
            "--dist-dir",
            str(dist),
            "--repository",
            _REPOSITORY,
            "--commit-sha",
            commit,
            "--workflow",
            _WORKFLOW,
            "--run-id",
            _RUN_ID,
            "--run-attempt",
            run_attempt,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _create(dist: Path) -> Path:
    result = _run(dist, "create")
    assert result.returncode == 0, result.stderr
    return dist / "artifact-manifest.json"


def _canonical_write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_manifest_creation_is_deterministic_and_verifies_exact_bytes(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest_path = _create(dist)
    first = manifest_path.read_bytes()

    second_result = _run(dist, "create")
    assert second_result.returncode == 0, second_result.stderr
    assert manifest_path.read_bytes() == first

    payload = json.loads(first)
    assert payload["schema_version"] == "agent-evals/package-artifact-manifest/v1"
    assert payload["source"] == {
        "repository": _REPOSITORY,
        "commit_sha": _COMMIT,
        "workflow": _WORKFLOW,
        "run_id": int(_RUN_ID),
        "run_attempt": int(_RUN_ATTEMPT),
    }
    assert [item["filename"] for item in payload["artifacts"]] == sorted(
        item["filename"] for item in payload["artifacts"]
    )
    for item in payload["artifacts"]:
        artifact = dist / item["filename"]
        assert item["size_bytes"] == artifact.stat().st_size
        assert item["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()

    verified = _run(dist, "verify")
    assert verified.returncode == 0, verified.stderr


def test_manifest_rejects_malformed_json(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest_path = _create(dist)
    manifest_path.write_text("{", encoding="utf-8")

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert "manifest is not valid UTF-8 JSON" in result.stderr


def test_manifest_rejects_duplicate_artifact_entry(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest_path = _create(dist)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"][1] = deepcopy(payload["artifacts"][0])
    _canonical_write(manifest_path, payload)

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert "duplicate artifact filenames" in result.stderr


def test_manifest_rejects_unexpected_retained_file(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    _create(dist)
    (dist / "unexpected.txt").write_text("not part of the release set", encoding="utf-8")

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert "retained artifact set mismatch" in result.stderr


@pytest.mark.parametrize(
    ("replacement", "expected"),
    ((b"WHEEL", "artifact digest mismatch"), (b"wheel-extra", "artifact size mismatch")),
)
def test_manifest_rejects_artifact_digest_or_size_mutation(
    tmp_path: Path,
    replacement: bytes,
    expected: str,
) -> None:
    dist = _artifact_dir(tmp_path)
    _create(dist)
    wheel = next(dist.glob("*.whl"))
    wheel.write_bytes(replacement)

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert expected in result.stderr


def test_manifest_rejects_source_context_mismatch(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    _create(dist)

    result = _run(dist, "verify", commit="b" * 40)

    assert result.returncode != 0
    assert "source context does not match expected CI context" in result.stderr


def test_manifest_reverification_accepts_prior_producing_attempt_in_same_run(
    tmp_path: Path,
) -> None:
    dist = _artifact_dir(tmp_path)
    _create(dist)

    result = _run(dist, "verify", run_attempt="2")

    assert result.returncode == 0, result.stderr


def test_manifest_rejects_impossible_future_producing_attempt(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    created = _run(dist, "create", run_attempt="2")
    assert created.returncode == 0, created.stderr

    result = _run(dist, "verify", run_attempt="1")

    assert result.returncode != 0
    assert "producing run attempt cannot be newer than verifier attempt" in result.stderr


def test_manifest_rejects_reordered_artifact_entries(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest_path = _create(dist)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"].reverse()
    _canonical_write(manifest_path, payload)

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert "artifact entries must be sorted by filename" in result.stderr


def test_manifest_rejects_invalid_source_field_type_without_traceback(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest_path = _create(dist)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source"]["repository"] = ["not", "text"]
    _canonical_write(manifest_path, payload)

    result = _run(dist, "verify")

    assert result.returncode != 0
    assert "repository must be canonical owner/name text" in result.stderr
    assert "Traceback" not in result.stderr
