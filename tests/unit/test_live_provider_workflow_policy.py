from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIRECTORY = _REPO_ROOT / ".github/workflows"
_RETIRED_WORKFLOW = _WORKFLOW_DIRECTORY / "live-provider-canary.yml"
_RETIRED_RUNNER = _REPO_ROOT / ".github/scripts/run_live_provider_canary.py"
_FORBIDDEN_WORKFLOW_MARKERS = (
    "OPENAI_API_KEY",
    "OPENAI_CANARY_",
    "run_live_provider_canary.py",
    "live-provider-canary",
    "api.openai.com/v1/responses",
)


def test_credentialed_live_provider_entry_points_are_absent_by_design() -> None:
    assert not _RETIRED_WORKFLOW.exists()
    assert not _RETIRED_RUNNER.exists()


def test_no_workflow_requires_provider_credentials_or_schedules_live_canary() -> None:
    workflows = sorted(
        (*_WORKFLOW_DIRECTORY.glob("*.yml"), *_WORKFLOW_DIRECTORY.glob("*.yaml"))
    )
    assert workflows
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert not any(marker in source for marker in _FORBIDDEN_WORKFLOW_MARKERS), workflow


def test_credential_free_provider_contracts_remain_executable_offline() -> None:
    assert (_REPO_ROOT / "src/agent_evals/live_provider.py").is_file()
    assert (_REPO_ROOT / "tests/unit/test_live_provider_canary.py").is_file()
