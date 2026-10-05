from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github/workflows/live-provider-canary.yml"


def test_live_provider_canary_is_never_required_on_ordinary_pr_or_push() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "schedule:" in source
    assert "\n  pull_request:" not in source
    assert "\n  push:" not in source


def test_live_provider_canary_declares_resource_and_cost_ceilings() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")

    for required in (
        'OPENAI_CANARY_MAX_ESTIMATED_COST_USD: "0.01"',
        'OPENAI_CANARY_MAX_REQUESTS_PER_MINUTE: "6"',
        'OPENAI_CANARY_MAX_ATTEMPTS: "3"',
        'OPENAI_CANARY_REQUEST_TIMEOUT_SECONDS: "15"',
        'OPENAI_CANARY_WALL_CLOCK_SECONDS: "45"',
        'OPENAI_CANARY_MAX_INPUT_TOKENS: "256"',
        'OPENAI_CANARY_MAX_OUTPUT_TOKENS: "32"',
        "continue-on-error: true",
        "if: always()",
        "live-provider-canary-${{ github.run_id }}",
    ):
        assert required in source


def test_live_provider_canary_uses_immutable_actions_and_no_write_permission() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in source
    assert "id-token: write" not in source
    assert "attestations: write" not in source
    assert "contents: write" not in source
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in source
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in source
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in source
