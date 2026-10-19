from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github/workflows/live-provider-canary.yml"
_APPROVED_ACTION_IDENTITIES = {
    "actions/checkout",
    "actions/setup-python",
    "actions/upload-artifact",
}


def _only_canonical_immutable_actions(source: str) -> bool:
    """Guard read-only canary action identity and full immutable SHA, not a stale release."""
    uses = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", source)
    parsed = [
        re.fullmatch(r"([a-z0-9._-]+/[a-z0-9._/-]+)@([0-9a-f]{40})", ref)
        for ref in uses
    ]
    return (
        len(uses) == len(_APPROVED_ACTION_IDENTITIES)
        and all(item is not None for item in parsed)
        and {item.group(1) for item in parsed if item is not None}
        == _APPROVED_ACTION_IDENTITIES
    )


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
    assert _only_canonical_immutable_actions(source)


def test_live_provider_action_integrity_rejects_mutable_and_foreign_refs() -> None:
    source = _WORKFLOW.read_text(encoding="utf-8")
    upload = re.search(r"actions/upload-artifact@[0-9a-f]{40}", source)
    assert upload is not None

    for bad_ref in (
        "actions/upload-artifact@main",
        "actions/upload-artifact@" + "A" * 40,
        "attacker/upload-artifact@" + "c" * 40,
    ):
        assert not _only_canonical_immutable_actions(source.replace(upload.group(), bad_ref, 1))
    assert not _only_canonical_immutable_actions(
        source + "\n        uses: attacker/extra@" + "b" * 40 + "\n"
    )
