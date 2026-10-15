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
    "PinnedDependenciesID": 3,
    "SASTID": 1,
}
BASELINE_COMMIT = "43cd171a2fec3ac6d3ae16d222a527ecef779887"

# Reviewed unresolved identities confirmed in genuine accepted-main Scorecard
# job 116209456072 (8 SARIF findings, 3 sdist pip warnings). The 15 first-party
# local-source installs cleared by PR #375 are deliberately NOT allowlisted here.
# These are warning ceilings, never waivers or permissions for script execution.
_PREVIOUS_LOCAL_SOURCE_PIP = (
    "python -m pip install --disable-pip-version-check --no-deps --no-build-isolation ."
)
_LOCAL_SDIST_PIP = (
    "python -m pip install --disable-pip-version-check --no-deps --no-build-isolation dist/*.tar.gz"
)
_RETAINED_SDIST_PIP = (
    "python -m pip install --disable-pip-version-check "
    "--no-deps --no-build-isolation retained-dist/*.tar.gz"
)
REVIEWED_PINNED_FINDING_IDENTITIES: dict[tuple[str, str], int] = {
    (".github/workflows/ci.yml", _LOCAL_SDIST_PIP): 1,
    (".github/workflows/ci.yml", _RETAINED_SDIST_PIP): 1,
    (".github/workflows/publish-release.yml", _RETAINED_SDIST_PIP): 1,
}


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
    expected = set(MAX_EXISTING)
    reviewed_sources = [
        identity
        for identity, count in REVIEWED_PINNED_FINDING_IDENTITIES.items()
        for _ in range(count)
    ]
    if len(reviewed_sources) != 3:
        raise ScorecardError("reviewed sdist pip warning identities must be exactly three")

    def make_result(name: str, index: int, rule_ids: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ruleId": name,
            "ruleIndex": rule_ids.index(name),
            "message": {"text": "genuine finding fixture"},
        }
        if name == "PinnedDependenciesID":
            path, snippet = reviewed_sources[index % len(reviewed_sources)]
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": path},
                        "region": {"snippet": {"text": snippet}},
                    }
                }
            ]
        return result

    def make(counts: dict[str, int]) -> dict[str, Any]:
        rule_ids = sorted(expected | set(counts))
        return {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Scorecard",
                            "semanticVersion": "v5.5.0",
                            "rules": [{"id": name} for name in rule_ids],
                        }
                    },
                    "results": [
                        make_result(name, index, rule_ids)
                        for name, qty in counts.items()
                        for index in range(qty)
                    ],
                }
            ],
        }

    baseline = make(MAX_EXISTING)
    if BASELINE_COMMIT != "43cd171a2fec3ac6d3ae16d222a527ecef779887":
        raise ScorecardError("independently verified 8-finding main commit drifted")
    if MAX_EXISTING.get("FuzzingID") != 0:
        raise ScorecardError("previously cleared Fuzzing finding is no longer fail-closed")
    if classify(baseline)["reported_findings"] != 8:
        raise ScorecardError("accepted-main 8-finding reference classification failed")
    if classify(make({}))["classification"] != "NO_REPORTED_FINDINGS":
        raise ScorecardError("empty result classification failed")
    if classify(make({"PinnedDependenciesID": 2}))["classification"] != "FINDINGS_OPEN":
        raise ScorecardError("reduced-count reference classification failed")
    import copy

    malicious: list[dict[str, Any]] = []
    malicious.append(make({"PinnedDependenciesID": 4}))
    # Replacing one of three audited sdist warnings with a new third-party
    # command must fail even when the total SARIF count stays at eight.
    new_path = copy.deepcopy(baseline)
    first_pip = next(
        result
        for result in new_path["runs"][0]["results"]
        if result["ruleId"] == "PinnedDependenciesID"
    )
    first_pip["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
        ".github/workflows/unreviewed.yml"
    )
    malicious.append(new_path)
    changed_snippet = copy.deepcopy(baseline)
    first_pip = next(
        result
        for result in changed_snippet["runs"][0]["results"]
        if result["ruleId"] == "PinnedDependenciesID"
    )
    first_pip["locations"][0]["physicalLocation"]["region"]["snippet"]["text"] = (
        "python -m pip install malicious==99.0"
    )
    malicious.append(changed_snippet)
    # A previously resolved first-party source installer warning is now
    # UNREVIEWED. Its reintroduction must be a regression, even with 8 total.
    retired = copy.deepcopy(baseline)
    first_pip = next(
        result
        for result in retired["runs"][0]["results"]
        if result["ruleId"] == "PinnedDependenciesID"
    )
    first_pip["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
        ".github/workflows/security.yml"
    )
    first_pip["locations"][0]["physicalLocation"]["region"]["snippet"]["text"] = (
        _PREVIOUS_LOCAL_SOURCE_PIP
    )
    malicious.append(retired)
    absent_location = copy.deepcopy(baseline)
    first_pip = next(
        result
        for result in absent_location["runs"][0]["results"]
        if result["ruleId"] == "PinnedDependenciesID"
    )
    first_pip.pop("locations")
    malicious.append(absent_location)
    excess_identity = copy.deepcopy(baseline)
    pip_results = [
        result
        for result in excess_identity["runs"][0]["results"]
        if result["ruleId"] == "PinnedDependenciesID"
    ]
    pip_results[-1]["locations"] = copy.deepcopy(pip_results[0]["locations"])
    malicious.append(excess_identity)
    malicious.append(make({"FuzzingID": 1}))
    # A previously fixed warning must also fail when it reappears in a
    # separate SARIF run, even if the initial run matches accepted main.
    split_run = copy.deepcopy(baseline)
    split_run["runs"].extend(make({"FuzzingID": 1})["runs"])
    malicious.append(split_run)
    malicious.append(make({"UnknownNewCheckID": 1}))
    bad = copy.deepcopy(baseline)
    bad["runs"] = []
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    del bad["runs"][0]["results"]
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    bad["runs"][0]["tool"]["driver"]["name"] = "NotScorecard"
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    bad["runs"][0]["tool"]["driver"]["rules"] = [{"id": "SASTID"}]
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    bad["runs"][0]["results"][0]["ruleIndex"] = 999
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    del bad["runs"][0]["results"][0]["message"]
    malicious.append(bad)
    bad = copy.deepcopy(baseline)
    bad["version"] = "2.0.0"
    malicious.append(bad)
    for i, fixture in enumerate(malicious):
        try:
            classify(fixture)
        except ScorecardError:
            continue
        raise ScorecardError(f"unsafe scanner evidence fixture accepted: {i}")
    # Exercise the real report-serialization path with both PASS and FAIL.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "triage.json"
        emit_report(path, baseline)
        if json.loads(path.read_text(encoding="utf-8"))["classification"] != "FINDINGS_OPEN":
            raise ScorecardError("reported-finding evidence was lost")
        try:
            emit_report(path, malicious[0])
        except ScorecardError:
            pass
        else:
            raise ScorecardError("increased findings were not a failing signal")
        if json.loads(path.read_text(encoding="utf-8"))["classification"] != "FAIL":
            raise ScorecardError("failed classification did not retain fail-closed evidence")
    print("Scorecard SARIF posture negative fixtures passed")


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
