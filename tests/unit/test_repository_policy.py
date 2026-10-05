from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLICY_SCRIPT = _PROJECT_ROOT / ".github/scripts/validate_runtime_policy.py"
_PINNED_CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def _policy_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    (workspace / ".github/workflows").mkdir(parents=True)
    (workspace / ".github/coverage").mkdir(parents=True)
    (workspace / "src/agent_evals").mkdir(parents=True)
    shutil.copy2(_PROJECT_ROOT / "pyproject.toml", workspace / "pyproject.toml")
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/ci.yml",
        workspace / ".github/workflows/ci.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/publish-release.yml",
        workspace / ".github/workflows/publish-release.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/deep-fuzz.yml",
        workspace / ".github/workflows/deep-fuzz.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/coverage/thresholds.json",
        workspace / ".github/coverage/thresholds.json",
    )
    shutil.copy2(_PROJECT_ROOT / "src/agent_evals/py.typed", workspace / "src/agent_evals/py.typed")
    return workspace


def _run_policy(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_POLICY_SCRIPT)],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )


def _secondary_workflow(action: str) -> str:
    return f"""name: Secondary\non: workflow_dispatch\njobs:\n  check:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: {action}\n"""


def test_policy_rejects_floating_action_in_second_workflow(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    (workspace / ".github/workflows/release.yml").write_text(
        _secondary_workflow("actions/checkout@v7"),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "release.yml" in result.stderr
    assert "pinned to a full commit SHA" in result.stderr


def test_policy_accepts_pinned_action_in_second_workflow(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    (workspace / ".github/workflows/release.yaml").write_text(
        _secondary_workflow(_PINNED_CHECKOUT),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode == 0, result.stderr
    assert "workflows=4" in result.stdout


def test_policy_rejects_missing_reproducible_package_comparison(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "python .github/scripts/package_artifact_manifest.py compare"
    assert required in source
    workflow.write_text(
        source.replace(required, "python .github/scripts/package_artifact_manifest.py verify", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "package-reproduce must compare rebuilt bytes against the retained manifest" in result.stderr


def test_policy_rejects_package_build_without_source_bound_epoch(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = 'export SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"'
    assert source.count(required) >= 2
    workflow.write_text(source.replace(required, "export SOURCE_DATE_EPOCH=0", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "package build must derive SOURCE_DATE_EPOCH from the exact source commit" in result.stderr

