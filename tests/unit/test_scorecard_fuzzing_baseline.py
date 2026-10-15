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
CURRENT_MAIN = "43cd171a2fec3ac6d3ae16d222a527ecef779887"

SOURCE_PIP = "python -m pip install --disable-pip-version-check --no-deps --no-build-isolation ."
DIST_PIP = (
    "python -m pip install --disable-pip-version-check --no-deps --no-build-isolation dist/*.tar.gz"
)
RETAINED_PIP = (
    "python -m pip install --disable-pip-version-check "
    "--no-deps --no-build-isolation retained-dist/*.tar.gz"
)
# Independent observed Scanner SARIF inventory from accepted main; do not take
# these values from the classifier under test and let it self-justify new risk.
REVIEWED_PIP_IDENTITIES = {
    (".github/workflows/ci.yml", DIST_PIP): 1,
    (".github/workflows/ci.yml", RETAINED_PIP): 1,
    (".github/workflows/publish-release.yml", RETAINED_PIP): 1,
}


def _sarif(counts: dict[str, int], rule_ids: set[str]) -> dict[str, Any]:
    rules = sorted(rule_ids)
    pip_locations = [
        identity for identity, quantity in REVIEWED_PIP_IDENTITIES.items() for _ in range(quantity)
    ]

    def finding(rid: str, index: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ruleId": rid,
            "ruleIndex": rules.index(rid),
            "message": {"text": "synthetic negative-test finding"},
        }
        if rid == "PinnedDependenciesID":
            path, snippet = pip_locations[index % len(pip_locations)]
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
                        "rules": [{"id": rid} for rid in rules],
                    }
                },
                "results": [
                    finding(rid, index)
                    for rid, quantity in counts.items()
                    for index in range(quantity)
                ],
            }
        ],
    }


def test_accepted_baseline_is_8_and_fuzzing_cannot_return() -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = scanner["MAX_EXISTING"]
    assert scanner["BASELINE_COMMIT"] == CURRENT_MAIN
    assert sum(counts.values()) == 8
    assert counts["FuzzingID"] == 0
    assert scanner["REVIEWED_PINNED_FINDING_IDENTITIES"] == REVIEWED_PIP_IDENTITIES
    assert sum(REVIEWED_PIP_IDENTITIES.values()) == 3
    result = scanner["classify"](_sarif(counts, set(counts)))
    assert result["classification"] == "FINDINGS_OPEN"
    assert result["reported_findings"] == 8
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
    counts["PinnedDependenciesID"] = 2
    result = scanner["classify"](_sarif(counts, set(counts)))
    assert result["reported_findings"] == 7
    assert result["classification"] == "FINDINGS_OPEN"
    counts["PinnedDependenciesID"] = 4
    with pytest.raises(scanner["ScorecardError"], match="PinnedDependenciesID"):
        scanner["classify"](_sarif(counts, set(counts)))


@pytest.mark.parametrize("mutation", ["path", "snippet", "missing", "excess", "retired-source"])
def test_same_total_new_pip_command_cannot_replace_reviewed_warning(mutation: str) -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = scanner["MAX_EXISTING"]
    document = _sarif(counts, set(counts))
    original = document["runs"][0]["results"]
    pip = [row for row in original if row["ruleId"] == "PinnedDependenciesID"]
    assert len(pip) == 3
    if mutation == "path":
        pip[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
            ".github/workflows/unreviewed-third-party.yml"
        )
    elif mutation == "snippet":
        pip[0]["locations"][0]["physicalLocation"]["region"]["snippet"]["text"] = (
            "python -m pip install suspicious==99.0"
        )
    elif mutation == "retired-source":
        # The cleared 15 local-source warnings can no longer hide in the
        # eight-finding ceiling, even with the same scanner total.
        pip[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
            ".github/workflows/security.yml"
        )
        pip[0]["locations"][0]["physicalLocation"]["region"]["snippet"]["text"] = (
            SOURCE_PIP
        )
    elif mutation == "missing":
        pip[0].pop("locations")
    else:
        # Move one existing warning to another already saturated reviewed
        # identity, retaining 3 total warnings and a superficially green score.
        pip[-1]["locations"] = pip[0]["locations"]

    assert len(original) == 8
    with pytest.raises(scanner["ScorecardError"], match="PinnedDependencies"):
        scanner["classify"](document)


def test_cross_run_growth_of_local_warning_identity_is_rejected() -> None:
    scanner = runpy.run_path(str(CLASSIFIER))
    counts = scanner["MAX_EXISTING"]
    document = _sarif(counts, set(counts))
    another = _sarif({"PinnedDependenciesID": 1}, set(counts))
    document["runs"].extend(another["runs"])
    with pytest.raises(scanner["ScorecardError"], match="PinnedDependencies"):
        scanner["classify"](document)
