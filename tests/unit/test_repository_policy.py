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
    (workspace / "src/agent_evals").mkdir(parents=True)
    shutil.copy2(_PROJECT_ROOT / "pyproject.toml", workspace / "pyproject.toml")
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/ci.yml",
        workspace / ".github/workflows/ci.yml",
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
    assert "workflows=2" in result.stdout
