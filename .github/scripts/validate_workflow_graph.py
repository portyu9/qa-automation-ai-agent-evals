"""Semantic GitHub Actions workflow graph validation.

This validator parses workflow YAML as data, rejects duplicate keys, checks job dependency
graphs for dangling references/cycles, and enforces immutable third-party action identities.
It intentionally complements runtime/release policy checks rather than interpreting workflow
text with regexes.
"""

from __future__ import annotations

import argparse
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
_SHA = re.compile(r"^[0-9a-f]{40}$")

# Validator-owned exceptions: narrowly scoped writes needed by trusted workflows.
# This is not a permission granted by the workflow declaring itself trusted.
# Any new entry requires review of triggers, source trust, and allowed API effects.
_TRUSTED_JOB_WRITES: dict[str, dict[str, frozenset[str]]] = {
    "ci.yml": {
        "release-provenance": frozenset({"id-token", "attestations", "artifact-metadata"}),
    },
    "codeql.yml": {"codeql": frozenset({"security-events"})},
    "security-scorecard.yml": {"scorecard": frozenset({"security-events"})},
    "dependency-governance.yml": {
        "govern": frozenset({"actions", "contents", "issues", "pull-requests"}),
    },
    "dependency-lock-publisher.yml": {"publish": frozenset({"contents"})},
    "publish-release.yml": {"publish": frozenset({"contents"})},
    "publish-pypi.yml": {"publish": frozenset({"id-token"})},
}

# Exact guards protect the trust transitions that justify the elevated tokens.
_TRUSTED_JOB_GUARDS: dict[tuple[str, str], str] = {
    ("ci.yml", "release-provenance"): (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    ),
    ("dependency-governance.yml", "govern"): "github.event_name != 'pull_request'",
    ("publish-release.yml", "publish"): "github.ref == 'refs/heads/main'",
}


class WorkflowPolicyError(ValueError):
    """Raised when a workflow violates the repository semantic graph contract."""


class _WorkflowLoader(yaml.SafeLoader):
    """Safe loader with GitHub-style 'on' semantics and duplicate-key rejection."""


# Copy resolver tables before changing bool resolution so importing this module never mutates
# PyYAML's global SafeLoader behavior. YAML 1.1 treats "on"/"off" as booleans, while GitHub
# Actions treats "on" as a literal mapping key.
_WorkflowLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for first, resolvers in list(_WorkflowLoader.yaml_implicit_resolvers.items()):
    _WorkflowLoader.yaml_implicit_resolvers[first] = [
        (tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
_WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"),
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: _WorkflowLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise WorkflowPolicyError("workflow mapping contains an unhashable key") from exc
        if duplicate:
            raise WorkflowPolicyError(f"workflow mapping contains duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_WorkflowLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_workflow(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_WorkflowLoader)
    except (OSError, UnicodeError, yaml.YAMLError, WorkflowPolicyError) as exc:
        raise WorkflowPolicyError(f"{path}: cannot parse workflow: {exc}") from exc
    if not isinstance(loaded, dict):
        raise WorkflowPolicyError(f"{path}: workflow root must be a mapping")
    return loaded


def _needs(value: Any, *, path: Path, job_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise WorkflowPolicyError(
        f"{path}: job {job_id!r} needs must be a string or non-empty string list"
    )


def _validate_uses(value: Any, *, path: Path, location: str) -> None:
    if not isinstance(value, str) or not value:
        raise WorkflowPolicyError(f"{path}: {location} uses must be a non-empty string")
    if value.startswith("./") or value.startswith("docker://"):
        return
    if "@" not in value:
        raise WorkflowPolicyError(
            f"{path}: {location} third-party uses must be pinned to a full commit SHA: {value!r}"
        )
    target, ref = value.rsplit("@", 1)
    if not target or _SHA.fullmatch(ref) is None:
        raise WorkflowPolicyError(
            f"{path}: {location} third-party uses must end in @<40 lowercase hex SHA>: {value!r}"
        )


def _validate_runner(value: Any, *, path: Path, job_id: str) -> None:
    def reject_floating(item: str) -> None:
        if item.endswith("-latest"):
            raise WorkflowPolicyError(f"{path}: job {job_id!r} uses floating runner label {item!r}")

    if isinstance(value, str):
        reject_floating(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                reject_floating(item)


def _validate_permissions(workflow: dict[str, Any], *, path: Path) -> None:
    """Require workflow-wide read-only authority and audited job-specific write exceptions."""
    permissions = workflow.get("permissions")
    if not isinstance(permissions, dict) or permissions.get("contents") != "read":
        raise WorkflowPolicyError(f"{path}: workflow must default to explicit contents: read")
    for name, level in permissions.items():
        if not isinstance(name, str) or level not in {"read", "none"}:
            raise WorkflowPolicyError(
                f"{path}: workflow-wide permission {name!r} must not have write access"
            )

    jobs = workflow["jobs"]
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue  # The job-shape validator reports this separately.
        job_permissions = job.get("permissions", {})
        if not isinstance(job_permissions, dict):
            raise WorkflowPolicyError(
                f"{path}: job {job_id!r} permissions must be an explicit mapping"
            )
        for name, level in job_permissions.items():
            if not isinstance(name, str) or level not in {"read", "write", "none"}:
                raise WorkflowPolicyError(
                    f"{path}: job {job_id!r} has an invalid permission declaration"
                )
        writes = frozenset(name for name, level in job_permissions.items() if level == "write")
        if not writes:
            continue

        allowed = _TRUSTED_JOB_WRITES.get(path.name, {}).get(job_id, frozenset())
        if not writes.issubset(allowed):
            raise WorkflowPolicyError(
                f"{path}: job {job_id!r} requests unapproved write capabilities "
                f"{sorted(writes - allowed)}"
            )
        triggers = workflow.get("on")
        if not isinstance(triggers, dict) or "pull_request_target" in triggers:
            raise WorkflowPolicyError(f"{path}: privileged job must have explicit safe triggers")
        expected_guard = _TRUSTED_JOB_GUARDS.get((path.name, job_id))
        if expected_guard is not None and job.get("if") != expected_guard:
            raise WorkflowPolicyError(
                f"{path}: privileged job {job_id!r} lost its accepted trust guard"
            )
        if "pull_request" in triggers and path.name in {
            "security-scorecard.yml",
            "publish-pypi.yml",
            "publish-release.yml",
            "dependency-lock-publisher.yml",
        }:
            raise WorkflowPolicyError(
                f"{path}: trusted publication or SARIF job may not run on PR code"
            )
        if path.name == "dependency-lock-publisher.yml":
            if set(triggers) != {"workflow_run"}:
                raise WorkflowPolicyError(
                    f"{path}: privileged lock publisher must use only workflow_run"
                )
            condition = str(job.get("if", ""))
            for required in (
                "workflow_run.conclusion == 'success'",
                "workflow_run.event == 'pull_request'",
                "workflow_run.head_branch, 'dependabot/pip/'",
            ):
                if required not in condition:
                    raise WorkflowPolicyError(
                        f"{path}: privileged lock publisher lost source filtering"
                    )
        if path.name == "publish-release.yml" and set(triggers) != {"repository_dispatch"}:
            raise WorkflowPolicyError(
                f"{path}: privileged release publication must use only repository_dispatch"
            )


def _validate_scorecard_read_contract(workflow: dict[str, Any], *, path: Path) -> None:
    """Protect the exact trusted-main Scorecard evidence visibility grant."""
    if path.name != "security-scorecard.yml":
        return
    triggers = workflow.get("on")
    if not isinstance(triggers, dict) or set(triggers) != {
        "push", "schedule", "workflow_dispatch"
    }:
        raise WorkflowPolicyError(
            f"{path}: Scorecard must stay on trusted-main push/schedule/dispatch"
        )
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {"scorecard"}:
        raise WorkflowPolicyError(f"{path}: one Scorecard observation job required")
    job = jobs["scorecard"]
    if not isinstance(job, dict) or "if" in job:
        raise WorkflowPolicyError(f"{path}: Scorecard job cannot be conditionally skipped")
    # Missing read permission silently downgrades an absent check to a missing
    # observation. Unreviewed reads and all extra writes must also be rejected.
    if job.get("permissions") != {
        "contents": "read",
        "checks": "read",
        "issues": "read",
        "pull-requests": "read",
        "security-events": "write",
    }:
        raise WorkflowPolicyError(f"{path}: Scorecard read-evidence authority drift")
    if "secrets." in path.read_text(encoding="utf-8"):
        raise WorkflowPolicyError(f"{path}: Scorecard must not use privileged PAT secrets")


def _validate_codeql_fork_contract(workflow: dict[str, Any], *, path: Path) -> None:
    """Prevent untrusted fork PR code gaining authority or evading the zero-alert scan."""
    if path.name != "codeql.yml":
        return
    triggers = workflow.get("on")
    if (
        not isinstance(triggers, dict)
        or "pull_request" not in triggers
        or "pull_request_target" in triggers
        or "workflow_run" in triggers
    ):
        raise WorkflowPolicyError(f"{path}: fork CodeQL must use unprivileged pull_request")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {"codeql"}:
        raise WorkflowPolicyError(f"{path}: expected one CodeQL analysis job")
    job = jobs["codeql"]
    if not isinstance(job, dict) or "if" in job:
        raise WorkflowPolicyError(f"{path}: CodeQL job must never skip external fork PRs")
    if job.get("permissions") != {
        "actions": "read",
        "contents": "read",
        "security-events": "write",
    }:
        raise WorkflowPolicyError(f"{path}: CodeQL job token authority drift")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise WorkflowPolicyError(f"{path}: CodeQL analysis steps are missing")
    named = {
        step.get("name"): step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }
    if len(named) != len(steps):
        raise WorkflowPolicyError(f"{path}: CodeQL analysis steps must be uniquely named")
    expected = {
        "Checkout exact analysis subject",
        "Validate zero-alert gate implementation",
        "Initialize CodeQL",
        "Analyze",
        "Enforce zero CodeQL alerts",
        "Upload CodeQL SARIF evidence",
    }
    if set(named) != expected:
        raise WorkflowPolicyError(f"{path}: CodeQL analysis step inventory drift")
    if named["Checkout exact analysis subject"].get("with") != {"persist-credentials": False}:
        raise WorkflowPolicyError(f"{path}: untrusted CodeQL checkout must not persist token")
    if named["Analyze"].get("with", {}).get("upload") != (
        "${{ github.event_name == 'pull_request' && 'never' || 'always' }}"
    ):
        raise WorkflowPolicyError(f"{path}: fork and internal PR CodeQL uploads must be disabled")
    if named["Analyze"].get("id") != "analyze-source":
        raise WorkflowPolicyError(f"{path}: CodeQL SARIF output binding drift")
    if "if" in named["Analyze"] or "if" in named["Enforce zero CodeQL alerts"]:
        raise WorkflowPolicyError(f"{path}: CodeQL scan/gate steps must never be skipped")
    if named["Enforce zero CodeQL alerts"].get("run") != (
        'python3 .github/scripts/validate_codeql_sarif.py "$SARIF_DIR"'
    ):
        raise WorkflowPolicyError(f"{path}: local zero-alert CodeQL veto cannot be bypassed")
    if named["Enforce zero CodeQL alerts"].get("env", {}).get("SARIF_DIR") != (
        "${{ steps.analyze-source.outputs.sarif-output }}"
    ):
        raise WorkflowPolicyError(f"{path}: CodeQL verifier must consume current run SARIF")
    if named["Upload CodeQL SARIF evidence"].get("if") != "always()":
        raise WorkflowPolicyError(f"{path}: forensic CodeQL SARIF must be retained on failure")
    if "secrets." in path.read_text(encoding="utf-8"):
        raise WorkflowPolicyError(f"{path}: untrusted fork CodeQL must never access secrets")


def validate_workflow(path: Path) -> None:
    workflow = _load_workflow(path)
    if not isinstance(workflow.get("name"), str) or not workflow["name"].strip():
        raise WorkflowPolicyError(f"{path}: workflow must declare a non-empty name")
    if "on" not in workflow:
        raise WorkflowPolicyError(f"{path}: workflow must declare an on trigger")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise WorkflowPolicyError(f"{path}: workflow must declare at least one job")

    _validate_codeql_fork_contract(workflow, path=path)
    _validate_scorecard_read_contract(workflow, path=path)
    _validate_permissions(workflow, path=path)

    graph: dict[str, tuple[str, ...]] = {}
    job_ids = set(jobs)
    if not all(isinstance(job_id, str) and job_id for job_id in job_ids):
        raise WorkflowPolicyError(f"{path}: every job id must be a non-empty string")

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            raise WorkflowPolicyError(f"{path}: job {job_id!r} must be a mapping")
        dependencies = _needs(job.get("needs"), path=path, job_id=job_id)
        for dependency in dependencies:
            if dependency not in job_ids:
                raise WorkflowPolicyError(
                    f"{path}: job {job_id!r} needs unknown job {dependency!r}"
                )
            if dependency == job_id:
                raise WorkflowPolicyError(f"{path}: job {job_id!r} cannot need itself")
        graph[job_id] = dependencies

        if "uses" in job:
            _validate_uses(job["uses"], path=path, location=f"job {job_id!r}")
        if "runs-on" in job:
            _validate_runner(job["runs-on"], path=path, job_id=job_id)

        steps = job.get("steps", [])
        if not isinstance(steps, list):
            raise WorkflowPolicyError(f"{path}: job {job_id!r} steps must be a list")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise WorkflowPolicyError(f"{path}: job {job_id!r} step {index} must be a mapping")
            if "uses" in step:
                _validate_uses(
                    step["uses"],
                    path=path,
                    location=f"job {job_id!r} step {index}",
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(job_id: str) -> None:
        if job_id in visited:
            return
        if job_id in visiting:
            raise WorkflowPolicyError(
                f"{path}: job dependency graph contains a cycle at {job_id!r}"
            )
        visiting.add(job_id)
        for dependency in graph[job_id]:
            visit(dependency)
        visiting.remove(job_id)
        visited.add(job_id)

    for job_id in graph:
        visit(job_id)


def validate_workflows(paths: Iterable[Path]) -> tuple[Path, ...]:
    checked = tuple(sorted(paths))
    if not checked:
        raise WorkflowPolicyError("no GitHub Actions workflows were found")
    for path in checked:
        validate_workflow(path)
    return checked


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-policy-") as directory:
        root = Path(directory)
        good = root / "good.yml"
        good.write_text(
            """
name: Good
on:
  pull_request:
permissions:
  contents: read
jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
  test:
    needs: lint
    runs-on: ubuntu-24.04
    steps:
      - run: python -m pytest
""".lstrip(),
            encoding="utf-8",
        )
        validate_workflow(good)
        # The actual pinned CodeQL workflow is a validated positive fixture;
        # each one-line trust regression must fail independently.
        source_codeql = (WORKFLOW_DIR / "codeql.yml").read_text(encoding="utf-8")
        candidate_codeql = root / "codeql.yml"
        candidate_codeql.write_text(source_codeql, encoding="utf-8")
        validate_workflow(candidate_codeql)
        changes = (
            (
                "    permissions:\n      actions: read",
                "    if: github.event_name != 'pull_request'\n    permissions:\n      actions: read",
            ),
            (
                "  pull_request:\n",
                "  pull_request_target:\n",
            ),
            (
                "          upload: ${{ github.event_name == 'pull_request' && 'never' || 'always' }}",
                "          upload: always",
            ),
            (
                "      - name: Enforce zero CodeQL alerts\n",
                "      - name: Enforce zero CodeQL alerts\n        if: github.event_name != 'pull_request'\n",
            ),
            (
                'run: python3 .github/scripts/validate_codeql_sarif.py "$SARIF_DIR"',
                "run: echo pretend-sarif-gate",
            ),
            (
                "          persist-credentials: false",
                "          persist-credentials: true",
            ),
            (
                "      - name: Analyze\n",
                "      - name: Analyze\n        if: github.event_name != 'pull_request'\n",
            ),
        )
        for original, malicious in changes:
            if source_codeql.count(original) != 1:
                raise WorkflowPolicyError("CodeQL negative-test fixture drift")
            candidate_codeql.write_text(
                source_codeql.replace(original, malicious), encoding="utf-8"
            )
            try:
                validate_workflow(candidate_codeql)
            except WorkflowPolicyError:
                continue
            raise WorkflowPolicyError("fork CodeQL privilege or bypass mutation was accepted")

        # A Scorecard run with no read access to checks can produce misleading
        # 0/N SAST history; disallow that invisible regression (and new writes).
        source_scorecard = (WORKFLOW_DIR / "security-scorecard.yml").read_text(
            encoding="utf-8"
        )
        candidate_scorecard = root / "security-scorecard.yml"
        candidate_scorecard.write_text(source_scorecard, encoding="utf-8")
        validate_workflow(candidate_scorecard)
        scorecard_mutations = (
            ("      checks: read", "      checks: none"),
            ("      checks: read", "      checks: write"),
            ("      issues: read", "      issues: none"),
            ("      pull-requests: read", "      pull-requests: none"),
            ("      security-events: write", "      security-events: read"),
            ("  push:\n    branches: [main]", "  pull_request:\n    branches: [main]"),
        )
        for original, malicious in scorecard_mutations:
            if source_scorecard.count(original) != 1:
                raise WorkflowPolicyError("Scorecard read-scope negative-test fixture drift")
            candidate_scorecard.write_text(
                source_scorecard.replace(original, malicious), encoding="utf-8"
            )
            try:
                validate_workflow(candidate_scorecard)
            except WorkflowPolicyError:
                continue
            raise WorkflowPolicyError(
                "Scorecard read visibility or privilege boundary mutation accepted"
            )

        fixtures = {
            "dangling.yml": """
name: Dangling
on: workflow_dispatch
jobs:
  test:
    needs: missing
    runs-on: ubuntu-24.04
    steps: []
""",
            "cycle.yml": """
name: Cycle
on: workflow_dispatch
jobs:
  one:
    needs: two
    runs-on: ubuntu-24.04
    steps: []
  two:
    needs: one
    runs-on: ubuntu-24.04
    steps: []
""",
            "unpinned.yml": """
name: Unpinned
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@main
""",
            "floating-runner.yml": """
name: Floating
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: []
""",
            "duplicate.yml": """
name: Duplicate
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-24.04
    runs-on: ubuntu-22.04
    steps: []
""",
        }
        fixtures.update(
            {
                "workflow-wide-write.yml": """
name: Unsafe workflow token
on: workflow_dispatch
permissions:
  contents: write
jobs:
  test:
    runs-on: ubuntu-24.04
    steps: []
""",
                "unapproved-job-write.yml": """
name: Unsafe job token
on: workflow_dispatch
permissions:
  contents: read
jobs:
  test:
    permissions:
      contents: write
    runs-on: ubuntu-24.04
    steps: []
""",
            }
        )
        trusted_release = root / "publish-release.yml"
        trusted_release.write_text(
            """name: Trusted release
on:
  repository_dispatch:
permissions:
  contents: read
jobs:
  publish:
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: write
    runs-on: ubuntu-24.04
    steps: []
""",
            encoding="utf-8",
        )
        validate_workflow(trusted_release)
        trusted_release.write_text(
            trusted_release.read_text(encoding="utf-8").replace(
                "github.ref == 'refs/heads/main'",
                "github.event_name == 'pull_request'",
            ),
            encoding="utf-8",
        )
        try:
            validate_workflow(trusted_release)
        except WorkflowPolicyError:
            pass
        else:
            raise AssertionError("privileged release without main guard unexpectedly passed")

        for name, source in fixtures.items():
            path = root / name
            # Preserve the intended negative test rather than rejecting only a missing default.
            if "permissions:" not in source:
                source = source.replace("jobs:", "permissions:\n  contents: read\njobs:", 1)
            path.write_text(source.lstrip(), encoding="utf-8")
            try:
                validate_workflow(path)
            except WorkflowPolicyError:
                continue
            raise AssertionError(f"negative self-test fixture unexpectedly passed: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("Semantic workflow graph validator self-test passed")
        return 0

    checked = validate_workflows(WORKFLOW_DIR.glob("*.y*ml"))
    print(
        "Semantic workflow graph contract passed: "
        f"{len(checked)} workflows, immutable action refs, acyclic job dependencies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
