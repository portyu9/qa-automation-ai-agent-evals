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
    retention = workflow.index("      - name: Retain Scorecard evidence\n")
    assert scan < upload < retention
    assert f"          sarif_file: {SARIF_PATH}\n" in workflow
    assert f"          path: {SARIF_PATH}\n" in workflow
    assert "          if-no-files-found: error\n" in workflow
    assert '          publish_results: "false"\n' in workflow


def test_scorecard_workflow_change_triggers_live_main_scan() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # Post-merge self-changes must exercise the real Scorecard implementation;
    # untrusted pull_request code must not inherit security-events: write.
    assert workflow.startswith("name: OpenSSF Scorecard\n\non:\n")
    assert (
        '  push:\n'
        '    branches: [main]\n'
        '    paths:\n'
        '      - ".github/workflows/security-scorecard.yml"\n'
    ) in workflow
    assert '  schedule:\n    - cron: "41 8 * * 2"\n' in workflow
    assert "  workflow_dispatch:\n" in workflow
    assert "  pull_request:\n" not in workflow
    assert "      security-events: write\n" in workflow
