"""Independent unit guards for the accepted Scorecard fuzzing-clearance baseline.

These synthetic fixtures test the classifier logic, not the authenticity of a
GitHub Code Scanning export or the completeness of any fuzzing campaign.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / ".github/scripts/classify_scorecard_sarif.py"
CURRENT_MAIN = "ac0680f130e5ce17fd85de587d95b8728347ba4e"


def _sarif(counts: dict[str, int], rule_ids: set[str]) -> dict[str, Any]:
    rules = sorted(rule_ids)
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Scorecard",
                        "semanticVersion": "v5.5.0",
                        "rules": [{"id": rid} for rid in rules],
                    }
                },
                "results": [
                    {
                        "ruleId": rid,
                        "ruleIndex": rules.index(rid),
                        "message": {"text": "synthetic negative-test finding"},
                    }
                    for rid, quantity in counts.items()
                    for _ in range(quantity)
                ],
            }
        ],
    }


def test_accepted_baseline_is_23_and_fuzzing_cannot_return() -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = scanner["MAX_EXISTING"]
    assert scanner["BASELINE_COMMIT"] == CURRENT_MAIN
    assert sum(counts.values()) == 23
    assert counts["FuzzingID"] == 0
    result = scanner["classify"](_sarif(counts, set(counts)))
    assert result["classification"] == "FINDINGS_OPEN"
    assert result["reported_findings"] == 23
    assert result["baseline_maxima"]["FuzzingID"] == 0
    assert result["counts"].get("FuzzingID", 0) == 0


@pytest.mark.parametrize("separate_run", [False, True])
def test_any_reintroduced_fuzzing_fails_closed(separate_run: bool) -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = scanner["MAX_EXISTING"]
    document = _sarif(counts, set(counts))
    recurrence = _sarif({"FuzzingID": 1}, set(counts))
    if separate_run:
        document["runs"].extend(recurrence["runs"])
    else:
        document["runs"][0]["results"].extend(recurrence["runs"][0]["results"])
    with pytest.raises(scanner["ScorecardError"], match="FuzzingID"):
        scanner["classify"](document)


def test_only_genuinely_lower_counts_are_allowed() -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = dict(scanner["MAX_EXISTING"])
    counts["PinnedDependenciesID"] = 17
    result = scanner["classify"](_sarif(counts, set(counts)))
    assert result["reported_findings"] == 22
    assert result["classification"] == "FINDINGS_OPEN"
    counts["PinnedDependenciesID"] = 19
    with pytest.raises(scanner["ScorecardError"], match="PinnedDependenciesID"):
        scanner["classify"](_sarif(counts, set(counts)))
