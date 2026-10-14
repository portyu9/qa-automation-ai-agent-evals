"""Regression contracts for independently retained OpenSSF Scorecard results."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/security-scorecard.yml"
SARIF_PATH = "reports/security/scorecard.sarif"


def test_scorecard_container_has_prepared_output_directory() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = (
        "      - name: Prepare Scorecard SARIF destination\n"
        "        run: mkdir -p reports/security\n"
    )
    scan = "      - name: Run OpenSSF Scorecard\n"
    assert workflow.count(prepare) == 1
    assert workflow.count(scan) == 1
    assert (
        workflow.index("      - name: Checkout exact monitored subject\n")
        < workflow.index(prepare)
        < workflow.index(scan)
    )
    assert f"          results_file: {SARIF_PATH}\n" in workflow


def test_scorecard_missing_evidence_still_fails_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    scan = workflow.index("      - name: Run OpenSSF Scorecard\n")
    upload = workflow.index("      - name: Upload Scorecard SARIF to code scanning\n")
    classify = workflow.index(
        "      - name: Classify genuine SARIF against accepted security posture baseline\n"
    )
    retention = workflow.index("      - name: Retain Scorecard evidence\n")
    assert scan < upload < classify < retention
    assert "        if: always()\n" in workflow[classify:retention]
    assert f"          sarif_file: {SARIF_PATH}\n" in workflow
    assert (
        "          path: |\n"
        f"            {SARIF_PATH}\n"
        "            reports/security/scorecard-triage.json\n"
    ) in workflow
    assert "          if-no-files-found: error\n" in workflow
    assert '          publish_results: "false"\n' in workflow


def test_every_accepted_main_push_triggers_scorecard_monitoring() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # Every merged change must be monitored, not only modifications to this workflow.
    # Untrusted pull_request code must not inherit security-events: write.
    assert workflow.startswith("name: OpenSSF Scorecard\n\non:\n")
    assert "  push:\n    branches: [main]\n" in workflow
    # Do not introduce a path filter that silently suppresses ordinary merges.
    assert "    paths:\n" not in workflow
    assert "    paths-ignore:\n" not in workflow
    assert '  schedule:\n    - cron: "41 8 * * 2"\n' in workflow
    assert "  workflow_dispatch:\n" in workflow
    assert "  pull_request:\n" not in workflow
    assert "      security-events: write\n" in workflow
