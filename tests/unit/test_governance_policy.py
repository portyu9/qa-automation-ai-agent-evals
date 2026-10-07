from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR = _PROJECT_ROOT / ".github/scripts/validate_governance_policy.py"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    (workspace / ".github/scripts").mkdir(parents=True)
    (workspace / "docs").mkdir(parents=True)
    shutil.copy2(_VALIDATOR, workspace / ".github/scripts/validate_governance_policy.py")
    shutil.copy2(
        _PROJECT_ROOT / ".github/repository-governance.json",
        workspace / ".github/repository-governance.json",
    )
    shutil.copy2(_PROJECT_ROOT / ".github/CODEOWNERS", workspace / ".github/CODEOWNERS")
    shutil.copy2(
        _PROJECT_ROOT / "docs/REPOSITORY_GOVERNANCE.md",
        workspace / "docs/REPOSITORY_GOVERNANCE.md",
    )
    return workspace


def _run(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(workspace / ".github/scripts/validate_governance_policy.py")],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )


def _load_policy(workspace: Path) -> tuple[Path, dict[str, object]]:
    path = workspace / ".github/repository-governance.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return path, raw


def test_governance_policy_accepts_single_codeowner_ci_authority(tmp_path: Path) -> None:
    result = _run(_workspace(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "one CODEOWNER, zero required approvals" in result.stdout


def test_governance_policy_rejects_required_approval(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path, policy = _load_policy(workspace)
    review = policy["review_policy"]
    assert isinstance(review, dict)
    review["required_approvals"] = 1
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result = _run(workspace)

    assert result.returncode != 0
    assert "must not require approving reviews" in result.stderr


def test_governance_policy_rejects_mandatory_codeowner_review(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path, policy = _load_policy(workspace)
    review = policy["review_policy"]
    assert isinstance(review, dict)
    review["require_code_owner_review"] = True
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result = _run(workspace)

    assert result.returncode != 0
    assert "must not be a mandatory merge approver" in result.stderr


def test_governance_policy_rejects_disabled_thread_resolution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path, policy = _load_policy(workspace)
    review = policy["review_policy"]
    assert isinstance(review, dict)
    review["require_review_thread_resolution"] = False
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result = _run(workspace)

    assert result.returncode != 0
    assert "review threads must remain resolved before merge" in result.stderr


def test_governance_policy_rejects_required_signed_commits(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path, policy = _load_policy(workspace)
    signed = policy["signed_history_policy"]
    assert isinstance(signed, dict)
    signed["required"] = True
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result = _run(workspace)

    assert result.returncode != 0
    assert "signed commits must not be required" in result.stderr


def test_governance_policy_rejects_codeowner_drift(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    codeowners = workspace / ".github/CODEOWNERS"
    source = codeowners.read_text(encoding="utf-8")
    assert "/.github/ @portyu9" in source
    codeowners.write_text(
        source.replace("/.github/ @portyu9", "/.github/ @different-owner", 1),
        encoding="utf-8",
    )

    result = _run(workspace)

    assert result.returncode != 0
    assert "CODEOWNERS mismatch for /.github/" in result.stderr
