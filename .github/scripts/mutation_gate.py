from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_POLICY_PATH = _ROOT / "mutation-policy.json"
_PYPROJECT_PATH = _ROOT / "pyproject.toml"
_REQUIREMENTS_PATH = _ROOT / "requirements-mutation.txt"
_SCHEMA = "agent-evals/mutation-policy/v1"
_EXPORTED_STATUSES = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)
_FATAL_STATUSES = (
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
    "unclassified",
)
_EXPECTED_TRUST_CLASSES = {
    "authority",
    "preconditions",
    "evaluator",
    "oracle",
    "receipt",
    "store",
    "release_gate",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read valid JSON from {path.relative_to(_ROOT)}") from exc
    if type(value) is not dict:
        raise ValueError(f"{path.relative_to(_ROOT)} must contain one JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _noncomment_requirement_lines() -> list[str]:
    return [
        line.strip()
        for line in _REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_policy(*, check_installed: bool) -> dict[str, Any]:
    policy = _load_json(_POLICY_PATH)
    errors: list[str] = []

    if policy.get("schema_version") != _SCHEMA:
        errors.append(f"schema_version must be {_SCHEMA!r}")

    tool = policy.get("tool")
    if type(tool) is not dict or tool.get("name") != "mutmut":
        errors.append("tool must name mutmut")
        tool_version = None
    else:
        tool_version = tool.get("version")
        if type(tool_version) is not str or not tool_version:
            errors.append("tool.version must be a non-empty exact version")

    if policy.get("python_version") != "3.12":
        errors.append("mutation policy Python must remain the audited 3.12 lane")

    threshold = policy.get("minimum_score_percent")
    if type(threshold) not in {int, float} or isinstance(threshold, bool):
        errors.append("minimum_score_percent must be numeric")
    elif not 0 < float(threshold) <= 100:
        errors.append("minimum_score_percent must be in (0, 100]")

    minimum_total = policy.get("minimum_total_mutants")
    if type(minimum_total) is not int or minimum_total <= 0:
        errors.append("minimum_total_mutants must be a positive integer")

    score_policy = policy.get("score_policy")
    expected_score_policy = {
        "numerator": "killed",
        "denominator": "total",
        "penalized_statuses": ["survived", "no_tests"],
        "fatal_statuses": list(_FATAL_STATUSES),
        "allow_hidden_exclusions": False,
    }
    if score_policy != expected_score_policy:
        errors.append("score_policy must use the fail-closed v1 killed/total contract")

    targets = policy.get("targets")
    target_paths: list[str] = []
    trust_classes: set[str] = set()
    if type(targets) is not list or not targets:
        errors.append("targets must be a non-empty list")
    else:
        for index, target in enumerate(targets):
            if type(target) is not dict:
                errors.append(f"targets[{index}] must be an object")
                continue
            path = target.get("path")
            trust_class = target.get("trust_class")
            reason = target.get("reason")
            if type(path) is not str or not path:
                errors.append(f"targets[{index}].path must be a non-empty string")
                continue
            target_paths.append(path)
            if type(trust_class) is not str or not trust_class:
                errors.append(f"targets[{index}].trust_class must be a non-empty string")
            else:
                trust_classes.add(trust_class)
            if type(reason) is not str or not reason.strip():
                errors.append(f"targets[{index}].reason must be a non-empty explanation")

            resolved = (_ROOT / path).resolve()
            source_root = (_ROOT / "src" / "agent_evals").resolve()
            if not resolved.is_relative_to(source_root) or resolved.suffix != ".py":
                errors.append(f"mutation target must be a Python file under src/agent_evals: {path}")
            elif not resolved.is_file():
                errors.append(f"mutation target does not exist: {path}")

    if len(target_paths) != len(set(target_paths)):
        errors.append("mutation target paths must be unique")
    missing_classes = _EXPECTED_TRUST_CLASSES - trust_classes
    if missing_classes:
        errors.append(f"mutation target manifest misses trust classes: {sorted(missing_classes)!r}")

    try:
        pyproject = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
        mutmut_config = pyproject["tool"]["mutmut"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        errors.append(f"could not read [tool.mutmut]: {exc}")
        mutmut_config = {}

    if mutmut_config.get("source_paths") != target_paths:
        errors.append("[tool.mutmut].source_paths must exactly match mutation-policy.json targets")
    if mutmut_config.get("pytest_add_cli_args_test_selection") != ["tests/unit"]:
        errors.append("mutation tests must remain scoped to deterministic unit tests")
    if mutmut_config.get("pytest_add_cli_args") != ["--hypothesis-seed=20260915"]:
        errors.append("mutation tests must pin the Hypothesis seed")
    if "type_check_command" in mutmut_config:
        errors.append("v1 mutation policy forbids hidden type-check filtering from the score")
    if "do_not_mutate" in mutmut_config or "do_not_mutate_patterns" in mutmut_config:
        errors.append("v1 mutation policy forbids blanket mutation exclusions")

    try:
        requirements = _noncomment_requirement_lines()
    except OSError as exc:
        errors.append(f"could not read requirements-mutation.txt: {exc}")
        requirements = []
    expected_requirement = f"mutmut=={tool_version}" if tool_version else None
    if requirements != [expected_requirement]:
        errors.append(
            "requirements-mutation.txt must contain only the exact policy mutmut pin "
            f"({expected_requirement!r})"
        )

    dev_dependencies = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    if any(str(dependency).split("=", 1)[0].strip().lower() == "mutmut" for dependency in dev_dependencies):
        errors.append("mutmut must remain isolated from the ordinary dev dependency set")

    if check_installed and tool_version:
        try:
            installed = importlib.metadata.version("mutmut")
        except importlib.metadata.PackageNotFoundError:
            errors.append("mutmut is not installed in the mutation environment")
        else:
            if installed != tool_version:
                errors.append(
                    f"installed mutmut version {installed!r} does not match policy {tool_version!r}"
                )

    if errors:
        raise ValueError("mutation policy validation failed:\n- " + "\n- ".join(errors))
    return policy


def evaluate_stats(stats: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    values: dict[str, int] = {}
    for key in (*_EXPORTED_STATUSES, "total"):
        value = stats.get(key)
        if type(value) is not int or value < 0:
            errors.append(f"stats field {key!r} must be a non-negative integer")
        else:
            values[key] = value

    if errors:
        return {"passed": False, "errors": errors}

    total = values["total"]
    classified = sum(values[key] for key in _EXPORTED_STATUSES)
    unclassified = total - classified
    if unclassified < 0:
        errors.append(
            f"exported mutation status counts exceed total: classified={classified} total={total}"
        )
        unclassified = 0

    minimum_total = int(policy["minimum_total_mutants"])
    if total < minimum_total:
        errors.append(f"only {total} mutants were classified; policy requires at least {minimum_total}")

    fatal_counts = {key: values[key] for key in _FATAL_STATUSES if key != "unclassified"}
    fatal_counts["unclassified"] = unclassified
    nonzero_fatal = {key: count for key, count in fatal_counts.items() if count}
    if nonzero_fatal:
        errors.append(f"mutation run has fatal/unclassified statuses: {nonzero_fatal!r}")

    score = 0.0 if total == 0 else values["killed"] / total * 100.0
    threshold = float(policy["minimum_score_percent"])
    if score < threshold:
        errors.append(f"mutation score {score:.2f}% is below required {threshold:.2f}%")

    return {
        "passed": not errors,
        "score_percent": round(score, 4),
        "threshold_percent": threshold,
        "counts": {**values, "unclassified": unclassified},
        "errors": errors,
    }


def _render_markdown(report: dict[str, Any], policy: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# Mutation assurance report",
        "",
        f"- Commit: `{report['commit_sha']}`",
        f"- Workflow run: `{report['run_id']}` attempt `{report['run_attempt']}`",
        f"- Tool: `mutmut=={policy['tool']['version']}` on Python `{policy['python_version']}`",
        f"- Mutation score: **{report['score_percent']:.2f}%** (required: **{report['threshold_percent']:.2f}%**)",
        f"- Gate: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "## Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for key in (*_EXPORTED_STATUSES, "unclassified", "total"):
        lines.append(f"| `{key}` | {counts[key]} |")
    lines.extend(
        [
            "",
            "## Target manifest",
            "",
        ]
    )
    for target in policy["targets"]:
        lines.append(
            f"- `{target['path']}` — `{target['trust_class']}` — {target['reason']}"
        )
    lines.extend(
        [
            "",
            "## Gate diagnostics",
            "",
        ]
    )
    if report["errors"]:
        lines.extend(f"- {error}" for error in report["errors"])
    else:
        lines.append("- No score-policy violations detected.")
    lines.extend(
        [
            "",
            "## Nonclaims",
            "",
            "This score is test-strength evidence for the checked-in target set only. It is not formal verification, provider/remote-system evidence, authentication, a security certification, or evidence that unmutated modules have equivalent assurance. Surviving mutants still require human review; the score must not be widened into grading or release authority.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(
    *,
    evaluation: dict[str, Any],
    policy: dict[str, Any],
    stats_path: Path,
    commit_sha: str,
    run_id: str,
    run_attempt: str,
    run_exit_code: int,
    output_json: Path,
    output_markdown: Path,
) -> dict[str, Any]:
    report = {
        **evaluation,
        "schema_version": "agent-evals/mutation-report/v1",
        "commit_sha": commit_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "mutmut_run_exit_code": run_exit_code,
        "policy_sha256": _sha256(_POLICY_PATH),
        "stats_sha256": _sha256(stats_path),
        "targets": [target["path"] for target in policy["targets"]],
        "tool": policy["tool"],
        "python_version": policy["python_version"],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_markdown.write_text(_render_markdown(report, policy), encoding="utf-8")
    return report


def _command_validate(args: argparse.Namespace) -> int:
    try:
        policy = validate_policy(check_installed=args.check_installed)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        "mutation policy valid: "
        f"{len(policy['targets'])} targets, mutmut=={policy['tool']['version']}, "
        f"score >= {policy['minimum_score_percent']}%"
    )
    return 0


def _command_evaluate(args: argparse.Namespace) -> int:
    try:
        policy = validate_policy(check_installed=args.check_installed)
        stats_path = Path(args.stats)
        stats = _load_json(stats_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    evaluation = evaluate_stats(stats, policy)
    if args.run_exit_code != 0:
        evaluation["passed"] = False
        evaluation["errors"].append(
            f"mutmut run exited with {args.run_exit_code}; a completed mutation run must exit zero"
        )

    report = _write_report(
        evaluation=evaluation,
        policy=policy,
        stats_path=stats_path,
        commit_sha=args.commit_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        run_exit_code=args.run_exit_code,
        output_json=Path(args.output_json),
        output_markdown=Path(args.output_markdown),
    )
    print(
        f"mutation score {report['score_percent']:.2f}% / "
        f"required {report['threshold_percent']:.2f}%"
    )
    if report["errors"]:
        for error in report["errors"]:
            print(f"mutation gate: {error}", file=sys.stderr)
    return 0 if report["passed"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and evaluate mutation assurance policy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--check-installed", action="store_true")
    validate.set_defaults(func=_command_validate)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--stats", required=True)
    evaluate.add_argument("--commit-sha", required=True)
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--run-attempt", required=True)
    evaluate.add_argument("--run-exit-code", required=True, type=int)
    evaluate.add_argument("--output-json", required=True)
    evaluate.add_argument("--output-markdown", required=True)
    evaluate.add_argument("--check-installed", action="store_true")
    evaluate.set_defaults(func=_command_evaluate)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
