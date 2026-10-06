"""Fail closed when first-party code exists without a security scanner."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEQL_WORKFLOW = ROOT / ".github" / "workflows" / "codeql.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SCORECARD_WORKFLOW = ROOT / ".github" / "workflows" / "security-scorecard.yml"
SCANNER_POLICY = ROOT / ".github" / "security-scanners.json"

CODEQL_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
}
KNOWN_CODE_SUFFIXES = set(CODEQL_BY_SUFFIX) | {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".sh",
    ".bash",
    ".zsh",
    ".ksh",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".cs",
    ".java",
    ".kt",
    ".kts",
    ".rb",
    ".rs",
    ".swift",
    ".php",
    ".scala",
    ".lua",
    ".ps1",
}
SHELL_SHEBANG = re.compile(r"^#!.*\b(?:ba|da|k|z)?sh\b")


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\x00") if item]


def main() -> int:
    errors: list[str] = []
    files = tracked_files()
    workflow_text = CODEQL_WORKFLOW.read_text(encoding="utf-8")
    ci_workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    scorecard_workflow_text = SCORECARD_WORKFLOW.read_text(encoding="utf-8")
    discovered_codeql: set[str] = set()

    try:
        scanner_policy = json.loads(SCANNER_POLICY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load mandatory scanner policy: {type(exc).__name__}")
        scanner_policy = {}

    expected_scanners = {
        "bandit": ("python-source", "ci-gate"),
        "pip-audit": ("installed-dependency-graph", "ci-gate"),
        "actionlint": ("github-actions-syntax-semantics", "ci-gate"),
        "zizmor": ("github-actions-security", "ci-gate"),
        "dependency-review": (
            "pull-request-dependency-delta",
            "ci-gate-when-precondition-satisfied",
        ),
        "scorecard": ("repository-security-posture", "scheduled-monitor"),
        "codeql": ("python-and-actions-sast", "protected-gate"),
    }
    if scanner_policy.get("schema_version") != "agent-evals/security-scanners/v1":
        errors.append("mandatory scanner policy has an unsupported schema_version")
    scanners = scanner_policy.get("required_scanners")
    if not isinstance(scanners, list):
        errors.append("mandatory scanner policy required_scanners must be a list")
        scanners = []
    normalized_scanners: dict[str, tuple[str, str]] = {}
    for item in scanners:
        if not isinstance(item, dict):
            errors.append("mandatory scanner policy contains a non-object scanner entry")
            continue
        scanner_id = item.get("id")
        scope = item.get("scope")
        enforcement = item.get("enforcement")
        if not all(isinstance(value, str) and value for value in (scanner_id, scope, enforcement)):
            errors.append("mandatory scanner policy scanner entries require id/scope/enforcement")
            continue
        if scanner_id in normalized_scanners:
            errors.append(f"mandatory scanner policy duplicates scanner {scanner_id!r}")
            continue
        normalized_scanners[scanner_id] = (scope, enforcement)
    if normalized_scanners != expected_scanners:
        errors.append(
            "mandatory scanner policy mismatch: "
            f"found={normalized_scanners!r}, expected={expected_scanners!r}"
        )

    feature_policy = scanner_policy.get("repository_security_features")
    if not isinstance(feature_policy, dict):
        errors.append("mandatory scanner policy must declare repository_security_features")
    else:
        for feature in ("dependency_graph", "secret_scanning", "push_protection"):
            entry = feature_policy.get(feature)
            if not isinstance(entry, dict) or entry.get("required") is not True:
                errors.append(f"repository security feature {feature!r} must remain required")
            elif entry.get("verification") not in {
                "verified-enabled",
                "verified-disabled",
                "unverified-admin-surface",
            }:
                errors.append(
                    f"repository security feature {feature!r} has unsupported verification state"
                )

    ci_scanner_contracts = {
        "Bandit": "bandit -q -r src",
        "pip-audit": "pip-audit",
        "actionlint": "actionlint_1.7.12_linux_amd64.tar.gz",
        "zizmor": "zizmorcore/zizmor-action@cc914d7f3750a2d13d75c7f184a1060aa0e9d482",
        "zizmor version": 'version: "1.30.1"',
        "Actions security gate": "- actions-security",
        "dependency review": "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294",
        "dependency review gate": "- dependency-review",
        "dependency review BLOCKED classifier": "blocked-admin-prerequisite",
        "dependency graph capability probe": "dependency-graph/compare/",
    }
    for name, needle in ci_scanner_contracts.items():
        if needle not in ci_workflow_text:
            errors.append(f"CI workflow is missing mandatory {name} scanner contract")

    scorecard_contracts = {
        "pinned Scorecard action": "ossf/scorecard-action@2d1146689b8cda280b9bc96326124645441f03bc",
        "scheduled Scorecard trigger": 'cron: "41 8 * * 2"',
        "Scorecard SARIF upload": "github/codeql-action/upload-sarif@2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2",
    }
    for name, needle in scorecard_contracts.items():
        if needle not in scorecard_workflow_text:
            errors.append(f"Scorecard workflow is missing {name}")

    for path in files:
        suffix = path.suffix.lower()
        relative = path.relative_to(ROOT)
        if suffix in CODEQL_BY_SUFFIX:
            discovered_codeql.add(CODEQL_BY_SUFFIX[suffix])
        elif suffix in KNOWN_CODE_SUFFIXES:
            errors.append(
                f"tracked source {relative} has no scanner mapping; extend the CodeQL gate before merging"
            )

        if path.is_file():
            try:
                first_line = path.open("r", encoding="utf-8").readline().rstrip("\n")
            except UnicodeDecodeError:
                first_line = ""
            if SHELL_SHEBANG.search(first_line):
                errors.append(
                    f"tracked shell entrypoint {relative} is outside the repository's declared Python/Actions scanner stack"
                )

    expected_codeql = {"python"}
    if discovered_codeql != expected_codeql:
        errors.append(
            "first-party CodeQL language inventory mismatch: "
            f"found {sorted(discovered_codeql)}, expected {sorted(expected_codeql)}"
        )

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    if not workflows:
        errors.append("no GitHub Actions workflows found for CodeQL Actions analysis")

    required_contracts = {
        "Python and Actions analysis": "languages: python,actions",
        "security-extended queries": "queries: security-extended",
        "zero-alert enforcement": "python3 .github/scripts/validate_codeql_sarif.py",
        "SARIF retention": "Upload CodeQL SARIF evidence",
        "SARIF self-check": "python3 .github/scripts/validate_codeql_sarif_selfcheck.py",
        "stack inventory self-check": "python3 .github/scripts/validate_security_stack.py",
    }
    for name, needle in required_contracts.items():
        if needle not in workflow_text:
            errors.append(f"CodeQL workflow is missing {name}")

    sarif_gate = (ROOT / ".github" / "scripts" / "validate_codeql_sarif.py").read_text(
        encoding="utf-8"
    )
    if "CodeQL zero-alert gate rejected" not in sarif_gate:
        errors.append("CodeQL SARIF gate must reject every code-scanning result")

    if errors:
        print("Security stack coverage contract failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    security_features = scanner_policy.get("repository_security_features", {})
    unverified = [
        name
        for name, value in security_features.items()
        if isinstance(value, dict) and value.get("verification") != "verified-enabled"
    ]
    suffix = f"; admin prerequisites outstanding={sorted(unverified)}" if unverified else ""
    print(
        "Security stack coverage contract: mandatory Bandit/pip-audit/actionlint/zizmor/dependency-review/CodeQL "
        "gates plus scheduled Scorecard monitoring "
        f"gates are declared and bound{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
