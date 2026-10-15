"""Classify actual OpenSSF Scorecard SARIF without suppressing or rewriting any finding.

This is a *post-merge posture regression monitor*, not a vulnerability-clearance
attestation, an independent scanner, or an authentication authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

# Observed in genuine Scorecard v5.5.0 SARIF on accepted main ac0680f1... .
# The formerly open FuzzingID was cleared by a real Atheris campaign.
# Counts are *maxima*, not assurances of acceptable residual risk.
MAX_EXISTING: dict[str, int] = {
    "BranchProtectionID": 1,
    "CIIBestPracticesID": 1,
    "CodeReviewID": 1,
    "FuzzingID": 0,
    "MaintainedID": 1,
    "PinnedDependenciesID": 0,
    "SASTID": 1,
}
BASELINE_COMMIT = "c134d3bd2c15d3d5213aa72b7c3be7f2b192a990"

# Genuine accepted-main Scorecard run 38673527580 reports ZERO pip warnings.
# Previously reviewed sdist command identities are now retired, not allowed.
REVIEWED_PINNED_FINDING_IDENTITIES: dict[tuple[str, str], int] = {}


class ScorecardError(ValueError):
    """Unreliable SARIF evidence or a newly observed posture finding."""


def _pinned_finding_identity(result: dict[str, Any]) -> tuple[str, str]:
    """Require authentic Scorecard evidence identifying *which* pip command."""
    locations = result.get("locations")
    if not isinstance(locations, list) or len(locations) != 1 or not isinstance(locations[0], dict):
        raise ScorecardError("PinnedDependencies finding must have one source location")
    physical = locations[0].get("physicalLocation")
    if not isinstance(physical, dict):
        raise ScorecardError("PinnedDependencies source location is missing")
    artifact = physical.get("artifactLocation")
    region = physical.get("region")
    if not isinstance(artifact, dict) or not isinstance(region, dict):
        raise ScorecardError("PinnedDependencies path or source region is missing")
    snippet = region.get("snippet")
    path = artifact.get("uri")
    source = snippet.get("text") if isinstance(snippet, dict) else None
    if not isinstance(path, str) or not isinstance(source, str) or not path or not source:
        raise ScorecardError("PinnedDependencies lacks exact source path or pip command")
    return path, source


def classify(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("version") != "2.1.0":
        raise ScorecardError("expected a SARIF 2.1.0 object")
    runs = raw.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ScorecardError("Scorecard SARIF must contain at least one run")
    if sum(REVIEWED_PINNED_FINDING_IDENTITIES.values()) != MAX_EXISTING["PinnedDependenciesID"]:
        raise ScorecardError("reviewed local-install inventory and rule maxima disagree")
    counts: Counter[str] = Counter()
    pinned_identities: Counter[tuple[str, str]] = Counter()
    declared: set[str] = set()
    observed_runs = 0
    for run in runs:
        if not isinstance(run, dict):
            raise ScorecardError("SARIF run must be an object")
        driver = run.get("tool", {}).get("driver") if isinstance(run.get("tool"), dict) else None
        if not isinstance(driver, dict) or driver.get("name") != "Scorecard":
            raise ScorecardError("unexpected SARIF scanner identity")
        version = driver.get("semanticVersion")
        if not isinstance(version, str) or not version.startswith("v"):
            raise ScorecardError("missing Scorecard scanner version")
        rules = driver.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ScorecardError("missing Scorecard check inventory")
        in_run: set[str] = set()
        for rule in rules:
            rid = rule.get("id") if isinstance(rule, dict) else None
            if not isinstance(rid, str) or not rid or rid in in_run:
                raise ScorecardError("invalid or duplicate declared SARIF rule")
            in_run.add(rid)
            declared.add(rid)
        results = run.get("results")
        if not isinstance(results, list):
            raise ScorecardError("missing Scorecard SARIF results array")
        for result in results:
            if not isinstance(result, dict):
                raise ScorecardError("malformed Scorecard finding")
            rid = result.get("ruleId")
            if not isinstance(rid, str) or rid not in in_run:
                raise ScorecardError("finding has unknown or undeclared Scorecard rule")
            msg = result.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("text"), str) or not msg["text"]:
                raise ScorecardError("finding has no authentic scanner message")
            index = result.get("ruleIndex")
            if index is not None and (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(rules)
                or rules[index].get("id") != rid
            ):
                raise ScorecardError("Scorecard finding rule index does not match declared rule")
            if rid == "PinnedDependenciesID":
                identity = _pinned_finding_identity(result)
                pinned_identities[identity] += 1
                if pinned_identities[identity] > REVIEWED_PINNED_FINDING_IDENTITIES.get(
                    identity, 0
                ):
                    raise ScorecardError(
                        f"new or increased PinnedDependenciesID pipCommand identity: {identity!r}"
                    )
            counts[rid] += 1
        observed_runs += 1
    if not set(MAX_EXISTING).issubset(declared):
        raise ScorecardError("SARIF dropped one or more expected scanner rule definitions")
    unexpected = set(counts) - set(MAX_EXISTING)
    increased = {k: v for k, v in counts.items() if v > MAX_EXISTING.get(k, -1)}
    if unexpected or increased:
        raise ScorecardError(
            f"new or increased genuine Scorecard findings: unknown={sorted(unexpected)}, "
            f"increased={dict(sorted(increased.items()))}"
        )
    total = sum(counts.values())
    return {
        "schema_version": "agent-evals/scorecard-posture/v1",
        "classification": "FINDINGS_OPEN" if total else "NO_REPORTED_FINDINGS",
        "baseline_commit": BASELINE_COMMIT,
        "scanner": "OpenSSF Scorecard (SARIF, not an authenticated vulnerability attestation)",
        "sarif_runs": observed_runs,
        "reported_findings": total,
        "counts": dict(sorted(counts.items())),
        "baseline_maxima": dict(sorted(MAX_EXISTING.items())),
        "reviewed_pip_identity_maxima": len(REVIEWED_PINNED_FINDING_IDENTITIES),
        "observed_pip_identities": len(pinned_identities),
        "non_claims": [
            "Workflow success does not imply zero vulnerabilities.",
            "Known Scorecard warnings remain genuine and are neither dismissed nor filtered.",
            "A reduced count is an observation to independently verify against live Code Scanning.",
            "SHA-256 binds bytes, not publisher identity or provenance.",
        ],
    }


def self_test() -> None:
    import copy

    expected = set(MAX_EXISTING)
    former_pips = (
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
        (
            ".github/workflows/security.yml",
            "python -m pip install --no-deps --no-build-isolation .",
        ),
        (".github/workflows/unreviewed.yml", "python -m pip install malware==99.0"),
    )

    def make(counts: dict[str, int], *, source: tuple[str, str] = former_pips[0]) -> dict[str, Any]:
        rules = sorted(expected | set(counts))

        def result(rid: str) -> dict[str, Any]:
            row: dict[str, Any] = {
                "ruleId": rid,
                "ruleIndex": rules.index(rid),
                "message": {"text": "synthetic negative-test finding"},
            }
            if rid == "PinnedDependenciesID":
                path, snippet = source
                row["locations"] = [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": path},
                            "region": {"snippet": {"text": snippet}},
                        }
                    }
                ]
            return row

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
                        result(rid) for rid, amount in counts.items() for _ in range(amount)
                    ],
                }
            ],
        }

    if BASELINE_COMMIT != "c134d3bd2c15d3d5213aa72b7c3be7f2b192a990":
        raise ScorecardError("independently verified five-finding commit drifted")
    if MAX_EXISTING.get("PinnedDependenciesID") != 0 or MAX_EXISTING.get("FuzzingID") != 0:
        raise ScorecardError("previously cleared pip/fuzz findings lost their zero maxima")
    if REVIEWED_PINNED_FINDING_IDENTITIES or sum(MAX_EXISTING.values()) != 5:
        raise ScorecardError("five-finding zero-pip maximum drifted")
    baseline = make(MAX_EXISTING)
    if classify(baseline)["reported_findings"] != 5:
        raise ScorecardError("accepted-main five-finding reference classification failed")
    if classify(make({}))["classification"] != "NO_REPORTED_FINDINGS":
        raise ScorecardError("empty SARIF result classification failed")
    smaller = dict(MAX_EXISTING)
    smaller["SASTID"] = 0
    if classify(make(smaller))["reported_findings"] != 4:
        raise ScorecardError("genuine improvement was not represented as a lower count")

    malicious: list[dict[str, Any]] = [
        make({"PinnedDependenciesID": 1}, source=s) for s in former_pips
    ]
    malicious.extend((make({"FuzzingID": 1}), make({"SASTID": 2}), make({"UnknownRuleID": 1})))
    for rid in ("PinnedDependenciesID", "FuzzingID"):
        split = copy.deepcopy(baseline)
        split["runs"].extend(make({rid: 1})["runs"])
        malicious.append(split)
    missing_location = make({"PinnedDependenciesID": 1})
    missing_location["runs"][0]["results"][0].pop("locations")
    malicious.append(missing_location)
    for kind in (
        "no-runs",
        "no-results",
        "wrong-scanner",
        "wrong-rules",
        "bad-index",
        "missing-message",
        "old-sarif",
    ):
        bad = copy.deepcopy(baseline)
        if kind == "no-runs":
            bad["runs"] = []
        elif kind == "no-results":
            bad["runs"][0].pop("results")
        elif kind == "wrong-scanner":
            bad["runs"][0]["tool"]["driver"]["name"] = "NotScorecard"
        elif kind == "wrong-rules":
            bad["runs"][0]["tool"]["driver"]["rules"] = [{"id": "SASTID"}]
        elif kind == "bad-index":
            bad["runs"][0]["results"][0]["ruleIndex"] = 999
        elif kind == "missing-message":
            bad["runs"][0]["results"][0].pop("message")
        else:
            bad["version"] = "2.0.0"
        malicious.append(bad)
    for number, fixture in enumerate(malicious):
        try:
            classify(fixture)
        except ScorecardError:
            continue
        raise ScorecardError(f"malformed or unsafe scanner fixture accepted: {number}")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "triage.json"
        emit_report(output, baseline)
        if json.loads(output.read_text(encoding="utf-8"))["classification"] != "FINDINGS_OPEN":
            raise ScorecardError("genuine findings were not reported")
        try:
            emit_report(output, malicious[0])
        except ScorecardError:
            pass
        else:
            raise ScorecardError("reintroduced pip warning did not fail closed")
        if json.loads(output.read_text(encoding="utf-8"))["classification"] != "FAIL":
            raise ScorecardError("failure report did not retain FAIL")
    print("Scorecard five-finding zero-pip regression fixtures passed")


def emit_report(path: Path, raw: Any, *, input_sha256: str | None = None) -> dict[str, Any]:
    try:
        report = classify(raw)
    except ScorecardError as exc:
        report = {
            "schema_version": "agent-evals/scorecard-posture/v1",
            "classification": "FAIL",
            "baseline_commit": BASELINE_COMMIT,
            "error": str(exc),
            "non_claim": "Failed classification cannot be represented as zero findings.",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    report["input_sha256"] = input_sha256
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sarif", nargs="?", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.sarif is None or args.report is None:
        parser.error("SARIF path and --report are required")
    try:
        content = args.sarif.read_bytes()
        raw = json.loads(content)
        report = emit_report(
            args.report,
            raw,
            input_sha256=hashlib.sha256(content).hexdigest(),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ScorecardError) as exc:
        if not args.report.exists():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(
                    {
                        "schema_version": "agent-evals/scorecard-posture/v1",
                        "classification": "FAIL",
                        "error": f"{type(exc).__name__}: {exc}",
                        "non_claim": "Missing or invalid SARIF must not be called clean.",
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        print(f"Scorecard SARIF posture gate: FAIL: {exc}")
        return 1
    print(
        f"Scorecard SARIF: {report['classification']}, "
        f"real findings={report['reported_findings']}, "
        f"baseline maxima={sum(MAX_EXISTING.values())}; "
        "no alerts were suppressed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
