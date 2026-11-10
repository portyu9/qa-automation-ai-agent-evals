"""Regression contracts for factually bounded native dependency review diagnostics."""

from pathlib import Path

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _ci() -> str:
    return CI.read_text(encoding="utf-8")


def test_403_404_cannot_claim_dependency_graph_is_disabled() -> None:
    workflow = _ci()
    review = workflow.split("  dependency-review:\n", 1)[1].split("\n  quality:", 1)[0]
    assert "403|404)" in review
    assert 'echo "state=blocked-admin-prerequisite" >> "$GITHUB_OUTPUT"' in review
    assert "HTTP 403/404 alone cannot establish" in review
    assert "graph configuration, token authorization or feature entitlement" in review
    assert "active issue #440" in review
    assert "repository dependency graph is not enabled" not in review
    assert "dependency graph requires repository-administrator enablement" not in review
    assert "tracked by #193" not in review
    assert "not PASS or FAIL: native dependency comparison did not run" in review


def test_native_dependency_review_is_not_bypassed_or_mislabeled_green() -> None:
    workflow = _ci()
    review = workflow.split("  dependency-review:\n", 1)[1].split("\n  quality:", 1)[0]
    assert "200)" in review
    assert 'echo "state=available" >> "$GITHUB_OUTPUT"' in review
    assert (
        "if: github.event_name == 'pull_request' && "
        "steps.dependency_graph.outputs.state == 'available'"
    ) in review
    assert "uses: actions/dependency-review-action@" in review
    assert 'warn-only: "false"' in review
    assert 'echo "state=passed" >> "$GITHUB_OUTPUT"' in review
    assert 'elif [[ "$GRAPH_STATE" == "available" ]]' in review
    assert 'elif [[ "$GRAPH_STATE" == "blocked-admin-prerequisite" ]]' in review
    assert 'echo "state=blocked-admin-prerequisite" >> "$GITHUB_OUTPUT"' in review
    assert 'echo "::error::dependency-review precondition probe returned HTTP $status"' in review


def test_final_gate_preserves_degraded_coverage_notice() -> None:
    workflow = _ci()
    gate = workflow.split('case "$DEPENDENCY_REVIEW_STATE" in', 1)[1]
    assert "blocked-admin-prerequisite)" in gate
    assert "native change-aware review was not performed" in gate
    assert "issue #440" in gate
    assert "dependency graph is disabled; see #193" not in gate
    assert 'echo "::error::unrecognized dependency-review state=' in gate
