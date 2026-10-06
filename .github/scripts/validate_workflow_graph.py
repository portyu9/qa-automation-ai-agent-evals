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
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
_SHA = re.compile(r"^[0-9a-f]{40}$")


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
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:bool"
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
            raise WorkflowPolicyError(
                f"{path}: job {job_id!r} uses floating runner label {item!r}"
            )

    if isinstance(value, str):
        reject_floating(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                reject_floating(item)


def validate_workflow(path: Path) -> None:
    workflow = _load_workflow(path)
    if not isinstance(workflow.get("name"), str) or not workflow["name"].strip():
        raise WorkflowPolicyError(f"{path}: workflow must declare a non-empty name")
    if "on" not in workflow:
        raise WorkflowPolicyError(f"{path}: workflow must declare an on trigger")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise WorkflowPolicyError(f"{path}: workflow must declare at least one job")

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
                raise WorkflowPolicyError(
                    f"{path}: job {job_id!r} step {index} must be a mapping"
                )
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
            raise WorkflowPolicyError(f"{path}: job dependency graph contains a cycle at {job_id!r}")
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
        for name, source in fixtures.items():
            path = root / name
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
