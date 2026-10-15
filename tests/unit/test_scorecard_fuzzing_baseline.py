"""Independent synthetic SARIF guards for the genuine five-finding Scorecard baseline.

These fixtures do not constitute independent scanner execution or Code Scanning
UI evidence. Refer to accepted main Scorecard run 38673527580.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / ".github/scripts/classify_scorecard_sarif.py"
ACCEPTED_MAIN = "c134d3bd2c15d3d5213aa72b7c3be7f2b192a990"

RETIRED_PIPS = (
    (
        ".github/workflows/ci.yml",
        "python -m pip install --no-deps --no-build-isolation dist/*.tar.gz",
    ),
    (
        ".github/workflows/ci.yml",
        "python -m pip install --no-deps --no-build-isolation retained-dist/*.tar.gz",
    ),
    (
        ".github/workflows/publish-release.yml",
        "python -m pip install --no-deps --no-build-isolation retained-dist/*.tar.gz",
    ),
    (".github/workflows/security.yml", "python -m pip install --no-deps --no-build-isolation ."),
    (".github/workflows/unknown.yml", "python -m pip install malicious==99.0"),
)


def _sarif(
    counts: dict[str, int],
    rules: set[str],
    *,
    source: tuple[str, str] = RETIRED_PIPS[0],
) -> dict[str, Any]:
    declared = sorted(rules | set(counts))

    def finding(rid: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ruleId": rid,
            "ruleIndex": declared.index(rid),
            "message": {"text": "synthetic negative-test finding"},
        }
        if rid == "PinnedDependenciesID":
            path, snippet = source
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": path},
                        "region": {"snippet": {"text": snippet}},
                    }
                }
            ]
        return result

    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Scorecard",
                        "semanticVersion": "v5.5.0",
                        "rules": [{"id": rule} for rule in declared],
                    }
                },
                "results": [
                    finding(rule) for rule, amount in counts.items() for _ in range(amount)
                ],
            }
        ],
    }


def test_accepted_five_finding_baseline_has_no_pip_or_fuzz_allowance() -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = classifier["MAX_EXISTING"]
    assert classifier["BASELINE_COMMIT"] == ACCEPTED_MAIN
    assert sum(limits.values()) == 5
    assert limits["FuzzingID"] == 0
    assert limits["PinnedDependenciesID"] == 0
    assert classifier["REVIEWED_PINNED_FINDING_IDENTITIES"] == {}
    report = classifier["classify"](_sarif(limits, set(limits)))
    assert report["classification"] == "FINDINGS_OPEN"
    assert report["reported_findings"] == 5
    assert report["reviewed_pip_identity_maxima"] == 0
    assert report["observed_pip_identities"] == 0


@pytest.mark.parametrize("source", RETIRED_PIPS)
@pytest.mark.parametrize("split_run", [False, True])
def test_cleared_pip_commands_cannot_reappear(source: tuple[str, str], split_run: bool) -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = classifier["MAX_EXISTING"]
    document = _sarif(limits, set(limits))
    relapse = _sarif({"PinnedDependenciesID": 1}, set(limits), source=source)
    if split_run:
        document["runs"].extend(relapse["runs"])
    else:
        document["runs"][0]["results"].extend(relapse["runs"][0]["results"])
    with pytest.raises(classifier["ScorecardError"], match="PinnedDependencies"):
        classifier["classify"](document)


@pytest.mark.parametrize("rule", ["FuzzingID", "PinnedDependenciesID"])
def test_every_cleared_rule_reintroduces_a_failure(rule: str) -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = classifier["MAX_EXISTING"]
    document = _sarif(limits, set(limits))
    document["runs"].extend(_sarif({rule: 1}, set(limits))["runs"])
    with pytest.raises(classifier["ScorecardError"], match=rule.replace("ID", "")):
        classifier["classify"](document)


def test_five_finding_monitor_allows_real_decreases_and_vetoes_growth() -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = dict(classifier["MAX_EXISTING"])
    limits["SASTID"] = 0
    actual = classifier["classify"](_sarif(limits, set(limits)))
    assert actual["reported_findings"] == 4
    assert actual["classification"] == "FINDINGS_OPEN"
    limits["SASTID"] = 2
    with pytest.raises(classifier["ScorecardError"], match="SASTID"):
        classifier["classify"](_sarif(limits, set(limits)))


@pytest.mark.parametrize("mutation", ["missing", "empty", "invalid-path"])
def test_pip_findings_cannot_hide_behind_malformed_identity(mutation: str) -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = classifier["MAX_EXISTING"]
    doc = _sarif({"PinnedDependenciesID": 1}, set(limits))
    row = doc["runs"][0]["results"][0]
    if mutation == "missing":
        del row["locations"]
    elif mutation == "empty":
        row["locations"] = []
    else:
        row["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = ""
    with pytest.raises(classifier["ScorecardError"], match="PinnedDependencies"):
        classifier["classify"](doc)


def test_empty_real_results_are_not_the_same_as_missing_scanner_evidence() -> None:
    classifier = runpy.run_path(str(CLASSIFIER))
    limits = classifier["MAX_EXISTING"]
    empty = _sarif({}, set(limits))
    assert classifier["classify"](empty)["classification"] == "NO_REPORTED_FINDINGS"
    del empty["runs"][0]["results"]
    with pytest.raises(classifier["ScorecardError"], match="missing Scorecard SARIF results"):
        classifier["classify"](empty)
