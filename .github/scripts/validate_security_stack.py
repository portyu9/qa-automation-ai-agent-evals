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
GOVERNANCE_DRIFT_WORKFLOW = ROOT / ".github" / "workflows" / "governance-drift.yml"
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


# Dependabot may update the immutable *action* source independently of the
# hash-pinned zizmor CLI. Require the complete unchanged scanner invocation,
# not an obsolete action SHA. Native Dependabot release/commit provenance and
# one-for-one workflow mutation checks remain separately mandatory.
ZIZMOR_USES = re.compile(r"(?m)^\s+uses:\s+zizmorcore/zizmor-action@")
ZIZMOR_STEP = re.compile(
    r"(?m)^      - name: Audit GitHub Actions with pinned zizmor\n"
    r"        uses: zizmorcore/zizmor-action@(?P<sha>[0-9a-f]{40})"
    r" # v(?P<release>[0-9]+\.[0-9]+\.[0-9]+)\n"
    r"        with:\n"
    r'          version: "1.30.1"\n'
    r'          online-audits: "false"\n'
    r'          advanced-security: "false"\n'
    r'          annotations: "true"\n'
    r'          persona: "regular"\n'
    r'          min-severity: "medium"\n'
    r'          min-confidence: "medium"(?=\n|$)'
)


def zizmor_contract_is_secure(source: str) -> bool:
    """Require exactly one immutable-SHA scanner step and all secure options."""
    return len(ZIZMOR_USES.findall(source)) == 1 and len(
        ZIZMOR_STEP.findall(source)
    ) == 1


def zizmor_adversarial_self_test(source: str) -> None:
    """Prove mutable, duplicate, substituted and weakened steps are rejected."""
    if not zizmor_contract_is_secure(source):
        raise ValueError("canonical zizmor scanner fixture was not accepted")
    matched = ZIZMOR_STEP.search(source)
    if matched is None:
        raise ValueError("canonical zizmor scanner fixture disappeared")
    mutations = {
        "untrusted publisher": source.replace(
            "zizmorcore/zizmor-action@", "attacker/zizmor-action@", 1
        ),
        "mutable action ref": source.replace(matched.group("sha"), "main", 1),
        "abbreviated SHA": source.replace(
            matched.group("sha"), matched.group("sha")[:12], 1
        ),
        "unversioned action": source.replace(
            " # v" + matched.group("release"), "", 1
        ),
        "missing scanner": source.replace(matched.group(0), "", 1),
        "duplicate scanner": source
        + "\n        uses: zizmorcore/zizmor-action@" + matched.group("sha"),
        "online audits enabled": source.replace(
            '          online-audits: "false"', '          online-audits: "true"', 1
        ),
        "scanner severity weakened": source.replace(
            '          min-severity: "medium"', '          min-severity: "none"', 1
        ),
    }
    for label, changed in mutations.items():
        if zizmor_contract_is_secure(changed):
            raise ValueError(f"unsafe zizmor mutation accepted: {label}")


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
    governance_drift_workflow_text = GOVERNANCE_DRIFT_WORKFLOW.read_text(encoding="utf-8")
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
        "zizmor version": 'version: "1.30.1"',
        "Actions security gate": "- actions-security",
        "dependency review": "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294",
        "semantic workflow security gate": "python .github/scripts/validate_workflow_graph.py",
        "workflow security gate self-test": "python .github/scripts/validate_workflow_graph.py --self-test",
        "workflow pip install integrity gate": "python .github/scripts/validate_workflow_pip_installs.py",
        "workflow pip install negative tests": "python .github/scripts/validate_workflow_pip_installs.py --self-test",
        "live governance negative fixtures": "python .github/scripts/audit_live_repo_controls.py --self-test",
        "independent Security success bridge": "--workflow security",
        "protected Security gate": "Require independent exact-subject Security workflow and job success",
        "compiler bootstrap policy": "python .github/scripts/validate_compiler_bootstrap.py",
        "compiler bootstrap negative tests": "python .github/scripts/validate_compiler_bootstrap.py --self-test",
        "dependency review gate": "- dependency-review",
        "dependency review BLOCKED classifier": "blocked-admin-prerequisite",
        "dependency graph capability probe": "dependency-graph/compare/",
    }
    for name, needle in ci_scanner_contracts.items():
        if needle not in ci_workflow_text:
            errors.append(f"CI workflow is missing mandatory {name} scanner contract")

    if not zizmor_contract_is_secure(ci_workflow_text):
        errors.append("CI workflow is missing mandatory zizmor scanner contract")
    else:
        try:
            zizmor_adversarial_self_test(ci_workflow_text)
        except ValueError as exc:
            errors.append(f"zizmor scanner integrity self-test failed: {exc}")

    scorecard_contracts = {
        "pinned Scorecard action": "ossf/scorecard-action@",
        "scheduled Scorecard trigger": 'cron: "41 8 * * 2"',
        "Scorecard SARIF upload": "github/codeql-action/upload-sarif@",
        "post-merge genuine SARIF posture regression gate": "python3 .github/scripts/classify_scorecard_sarif.py reports/security/scorecard.sarif --report reports/security/scorecard-triage.json",
        "retained triage evidence": "reports/security/scorecard-triage.json",
    }
    for name, needle in scorecard_contracts.items():
        if needle not in scorecard_workflow_text:
            errors.append(f"Scorecard workflow is missing {name}")
    for label, action in (
        ("Scorecard action", "ossf/scorecard-action"),
        ("Scorecard SARIF upload", "github/codeql-action/upload-sarif"),
    ):
        if (
            re.search(
                r"^\s*uses:\s*" + re.escape(action) + r"@[0-9a-f]{40}(?:\s+#.*)?$",
                scorecard_workflow_text,
                flags=re.MULTILINE,
            )
            is None
        ):
            errors.append(f"Scorecard workflow lost immutable SHA for {label}")

    governance_drift_contracts = {
        "trusted main push trigger": "branches: [main]",
        "scheduled governance recheck": 'cron: "23 7 * * *"',
        "read-only token": "  contents: read",
        "no credential persistence": "persist-credentials: false",
        "dedicated monitor self-test": "python3 .github/scripts/audit_live_repo_controls.py --self-test",
        "actual GitHub API attestation": "python3 .github/scripts/audit_live_repo_controls.py",
        "distinguish blocked admin controls": "--live --output reports/security/live-governance.json",
        "retained live settings evidence": "Retain live governance audit evidence",
        "read-only Github API token": "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
        "canonical owner-only monitor": "github.repository == 'portyu9/qa-automation-ai-agent-evals'",
    }
    for name, needle in governance_drift_contracts.items():
        if needle not in governance_drift_workflow_text:
            errors.append(f"governance monitor lost {name}")

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
