from __future__ import annotations

import hashlib
import json
import shutil
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
    reference_dir: Path | None = None,
    output_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
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
    ]
    if reference_dir is not None:
        args.extend(("--reference-dir", str(reference_dir)))
    if output_file is not None:
        args.extend(("--output", str(output_file)))
    return subprocess.run(
        args,
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


def _reproduced_dir(tmp_path: Path, retained: Path) -> Path:
    reproduced = tmp_path / "reproduced"
    reproduced.mkdir()
    for path in retained.iterdir():
        if path.name != "artifact-manifest.json":
            shutil.copy2(path, reproduced / path.name)
    return reproduced


def test_reproduction_comparison_accepts_exact_retained_bytes(tmp_path: Path) -> None:
    retained = _artifact_dir(tmp_path)
    _create(retained)
    reproduced = _reproduced_dir(tmp_path, retained)

    result = _run(reproduced, "compare", reference_dir=retained)

    assert result.returncode == 0, result.stderr
    assert "reproduced exact retained package bytes" in result.stdout


def test_reproduction_comparison_rejects_digest_mutation(tmp_path: Path) -> None:
    retained = _artifact_dir(tmp_path)
    _create(retained)
    reproduced = _reproduced_dir(tmp_path, retained)
    wheel = next(reproduced.glob("*.whl"))
    wheel.write_bytes(b"WHEEL")

    result = _run(reproduced, "compare", reference_dir=retained)

    assert result.returncode != 0
    assert "reproduced artifact digest mismatch" in result.stderr


def test_reproduction_comparison_rejects_missing_or_extra_material(tmp_path: Path) -> None:
    retained = _artifact_dir(tmp_path)
    _create(retained)
    reproduced = _reproduced_dir(tmp_path, retained)
    next(reproduced.glob("*.whl")).unlink()
    (reproduced / "unexpected.txt").write_text("extra", encoding="utf-8")

    result = _run(reproduced, "compare", reference_dir=retained)

    assert result.returncode != 0
    assert "reproduced artifact set mismatch" in result.stderr


def test_reproduction_comparison_rejects_symlink_material(tmp_path: Path) -> None:
    retained = _artifact_dir(tmp_path)
    _create(retained)
    reproduced = _reproduced_dir(tmp_path, retained)
    wheel = next(reproduced.glob("*.whl"))
    wheel.unlink()
    wheel.symlink_to(next(retained.glob("*.whl")))

    result = _run(reproduced, "compare", reference_dir=retained)

    assert result.returncode != 0
    assert "reproduced artifact directory must contain regular files only" in result.stderr


def test_locked_sdist_requirement_exact_manifest_digest_and_local_file(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    manifest = _create(dist)
    locked = tmp_path / "sdist-lock.txt"
    result = _run(dist, "locked-sdist", output_file=locked)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(item for item in parsed["artifacts"] if item["kind"] == "sdist")
    sdist = dist / entry["filename"]
    assert locked.read_text(encoding="utf-8") == (
        f"qa-automation-ai-agent-evals @ {sdist.resolve().as_uri()} "
        f"--hash=sha256:{entry['sha256']}\n"
    )
    assert "https://" not in locked.read_text(encoding="utf-8")
    # Exclusive creation prevents a stale or malicious preexisting lock.
    again = _run(dist, "locked-sdist", output_file=locked)
    assert again.returncode != 0


def test_locked_sdist_requirement_rejects_digest_context_and_path_mutation(tmp_path: Path) -> None:
    dist = _artifact_dir(tmp_path)
    _create(dist)
    sdist = next(dist.glob("*.tar.gz"))
    original = sdist.read_bytes()
    sdist.write_bytes(b"X" + original[1:])
    tampered = _run(dist, "locked-sdist", output_file=tmp_path / "tamper.txt")
    assert tampered.returncode != 0
    assert "digest mismatch" in tampered.stderr
    assert not (tmp_path / "tamper.txt").exists()
    sdist.write_bytes(original)
    wrong_commit = _run(dist, "locked-sdist", commit="b" * 40, output_file=tmp_path / "wrong.txt")
    assert wrong_commit.returncode != 0
    assert "source context" in wrong_commit.stderr
    assert not (tmp_path / "wrong.txt").exists()
    in_dist = _run(dist, "locked-sdist", output_file=dist / "untrusted.txt")
    assert in_dist.returncode != 0
    assert "must not contaminate" in in_dist.stderr
