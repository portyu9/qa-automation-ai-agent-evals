from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_PROFILE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SOURCE_PATH = re.compile(r"^src/agent_evals/.+\.py$")


class CoveragePolicyError(ValueError):
    """Coverage policy or measured coverage is malformed or below the required floor."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoveragePolicyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise CoveragePolicyError(f"non-finite JSON number is not allowed: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except FileNotFoundError as exc:
        raise CoveragePolicyError(f"required JSON file is missing: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoveragePolicyError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc
    if type(payload) is not dict:
        raise CoveragePolicyError(f"{path} root must be an exact JSON object")
    return payload


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise CoveragePolicyError(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _number(value: object, *, label: str, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        raise CoveragePolicyError(f"{label} must be an exact JSON number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= 100.0:
        raise CoveragePolicyError(f"{label} must be finite and between {minimum} and 100")
    return number


def _positive_int(value: object, *, label: str, allow_zero: bool = True) -> int:
    if type(value) is not int:
        raise CoveragePolicyError(f"{label} must be an exact JSON integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise CoveragePolicyError(f"{label} must be >= {minimum}")
    return value


def _load_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    payload = _load_json(path)
    _exact_keys(
        payload,
        {"schema_version", "mutation_manifest", "profiles"},
        label="coverage manifest",
    )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CoveragePolicyError(f"schema_version must be exact integer {SCHEMA_VERSION}")

    mutation_manifest = payload["mutation_manifest"]
    if (
        type(mutation_manifest) is not str
        or not mutation_manifest.startswith(".github/")
        or Path(mutation_manifest).is_absolute()
        or ".." in Path(mutation_manifest).parts
    ):
        raise CoveragePolicyError("mutation_manifest must be a canonical repository .github path")

    profiles = payload["profiles"]
    if type(profiles) is not dict or not profiles:
        raise CoveragePolicyError("profiles must be a non-empty exact JSON object")

    seen_paths: set[str] = set()
    for profile_id, profile in profiles.items():
        if type(profile_id) is not str or _PROFILE_ID.fullmatch(profile_id) is None:
            raise CoveragePolicyError(f"invalid coverage profile id: {profile_id!r}")
        if type(profile) is not dict:
            raise CoveragePolicyError(f"profile {profile_id} must be an exact JSON object")
        _exact_keys(
            profile,
            {
                "description",
                "require_mutation",
                "minimum_mutation_score",
                "minimum_group_percent",
                "files",
            },
            label=f"profile {profile_id}",
        )
        description = profile["description"]
        if type(description) is not str or not description.strip() or description != description.strip():
            raise CoveragePolicyError(f"profile {profile_id}.description must be trimmed text")
        require_mutation = profile["require_mutation"]
        if type(require_mutation) is not bool:
            raise CoveragePolicyError(f"profile {profile_id}.require_mutation must be boolean")
        minimum_mutation_score = profile["minimum_mutation_score"]
        if require_mutation:
            _number(
                minimum_mutation_score,
                label=f"profile {profile_id}.minimum_mutation_score",
                minimum=95.0,
            )
        elif minimum_mutation_score is not None:
            raise CoveragePolicyError(
                f"profile {profile_id}.minimum_mutation_score must be null when mutation is not required"
            )
        _number(profile["minimum_group_percent"], label=f"profile {profile_id}.minimum_group_percent")
        files = profile["files"]
        if type(files) is not dict or not files:
            raise CoveragePolicyError(f"profile {profile_id}.files must be non-empty")
        for source, threshold in files.items():
            if type(source) is not str or _SOURCE_PATH.fullmatch(source) is None:
                raise CoveragePolicyError(
                    f"profile {profile_id} has non-canonical source path: {source!r}"
                )
            if not (repository_root / source).is_file():
                raise CoveragePolicyError(
                    f"profile {profile_id} references missing source file: {source}"
                )
            _number(threshold, label=f"profile {profile_id}.files[{source}]")
            seen_paths.add(source)

    if not seen_paths:
        raise CoveragePolicyError("coverage manifest contains no source paths")
    return payload


def _coverage_units(summary: dict[str, Any], *, label: str) -> tuple[int, int, str]:
    required = {"num_statements", "covered_lines", "num_branches", "covered_branches"}
    missing = required - set(summary)
    if missing:
        raise CoveragePolicyError(f"{label} coverage summary missing fields: {sorted(missing)}")
    num_branches = _positive_int(summary["num_branches"], label=f"{label}.num_branches")
    covered_branches = _positive_int(
        summary["covered_branches"], label=f"{label}.covered_branches"
    )
    if covered_branches > num_branches:
        raise CoveragePolicyError(f"{label}.covered_branches exceeds num_branches")
    if num_branches > 0:
        return covered_branches, num_branches, "branch"

    num_statements = _positive_int(
        summary["num_statements"], label=f"{label}.num_statements", allow_zero=False
    )
    covered_lines = _positive_int(summary["covered_lines"], label=f"{label}.covered_lines")
    if covered_lines > num_statements:
        raise CoveragePolicyError(f"{label}.covered_lines exceeds num_statements")
    return covered_lines, num_statements, "line"


def _percentage(covered: int, total: int) -> float:
    if total <= 0:
        raise CoveragePolicyError("coverage denominator must be positive")
    return covered * 100.0 / total


def _mutation_sources(path: Path, *, required_score: float) -> set[str]:
    payload = _load_json(path)
    minimum_score = _number(payload.get("minimum_score"), label="mutation minimum_score")
    if minimum_score < required_score:
        raise CoveragePolicyError(
            f"mutation minimum score {minimum_score:.2f}% is below required {required_score:.2f}%"
        )
    campaigns = payload.get("campaigns")
    if type(campaigns) is not list or not campaigns:
        raise CoveragePolicyError("mutation campaigns must be a non-empty exact JSON array")
    sources: set[str] = set()
    for index, campaign in enumerate(campaigns):
        if type(campaign) is not dict:
            raise CoveragePolicyError(f"mutation campaigns[{index}] must be an object")
        raw_sources = campaign.get("sources")
        if type(raw_sources) is not list or not raw_sources:
            raise CoveragePolicyError(f"mutation campaigns[{index}].sources must be non-empty")
        for source in raw_sources:
            if type(source) is not str or _SOURCE_PATH.fullmatch(source) is None:
                raise CoveragePolicyError(
                    f"mutation campaigns[{index}] has invalid source path: {source!r}"
                )
            sources.add(source)
    return sources


def evaluate(
    manifest_path: Path,
    coverage_path: Path,
    *,
    profile_id: str,
    repository_root: Path,
) -> list[str]:
    manifest = _load_manifest(manifest_path, repository_root=repository_root)
    profiles = manifest["profiles"]
    profile = profiles.get(profile_id)
    if type(profile) is not dict:
        raise CoveragePolicyError(f"unknown coverage profile: {profile_id}")

    coverage = _load_json(coverage_path)
    files = coverage.get("files")
    if type(files) is not dict:
        raise CoveragePolicyError("coverage JSON files must be an exact object")

    configured_files = profile["files"]
    group_covered = 0
    group_total = 0
    messages: list[str] = []
    failures: list[str] = []
    for source, threshold_raw in configured_files.items():
        measured = files.get(source)
        if type(measured) is not dict:
            raise CoveragePolicyError(
                f"profile {profile_id} source is absent from measured coverage: {source}"
            )
        summary = measured.get("summary")
        if type(summary) is not dict:
            raise CoveragePolicyError(f"coverage summary is missing for {source}")
        covered, total, metric = _coverage_units(summary, label=source)
        percent = _percentage(covered, total)
        threshold = float(threshold_raw)
        if percent + 1e-12 < threshold:
            failures.append(
                f"{profile_id} {source} {metric} coverage {percent:.2f}% "
                f"is below required {threshold:.2f}%"
            )
        group_covered += covered
        group_total += total
        messages.append(
            f"{profile_id}: {source} {metric}={percent:.2f}% minimum={threshold:.2f}%"
        )

    group_percent = _percentage(group_covered, group_total)
    group_minimum = float(profile["minimum_group_percent"])
    if group_percent + 1e-12 < group_minimum:
        failures.append(
            f"{profile_id} aggregate decision coverage {group_percent:.2f}% "
            f"is below required {group_minimum:.2f}%"
        )
    messages.append(
        f"{profile_id}: aggregate decision coverage={group_percent:.2f}% "
        f"minimum={group_minimum:.2f}%"
    )

    if profile["require_mutation"]:
        mutation_score = float(profile["minimum_mutation_score"])
        mutation_path = repository_root / manifest["mutation_manifest"]
        mutation_sources = _mutation_sources(mutation_path, required_score=mutation_score)
        missing_mutation = sorted(set(configured_files) - mutation_sources)
        if missing_mutation:
            failures.append(
                f"{profile_id} coverage sources lack required mutation campaigns: {missing_mutation}"
            )
        else:
            messages.append(
                f"{profile_id}: all {len(configured_files)} coverage sources are mutation-targeted "
                f"with manifest minimum >= {mutation_score:.2f}%"
            )
    if failures:
        detail = "\n".join([*messages, *(f"VIOLATION: {failure}" for failure in failures)])
        raise CoveragePolicyError(detail)
    return messages


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "src/agent_evals/authority.py"
        source.parent.mkdir(parents=True)
        source.write_text("def allowed(x: bool) -> bool:\n    return x\n", encoding="utf-8")
        optional = root / "src/agent_evals/adapters/optional.py"
        optional.parent.mkdir(parents=True)
        optional.write_text("VALUE = 1\n", encoding="utf-8")
        mutation_dir = root / ".github/mutation"
        mutation_dir.mkdir(parents=True)
        _write_json(
            mutation_dir / "deep_targets.json",
            {
                "minimum_score": 95,
                "campaigns": [{"sources": ["src/agent_evals/authority.py"]}],
            },
        )
        coverage_dir = root / ".github/coverage"
        coverage_dir.mkdir(parents=True)
        manifest_path = coverage_dir / "thresholds.json"
        _write_json(
            manifest_path,
            {
                "schema_version": 1,
                "mutation_manifest": ".github/mutation/deep_targets.json",
                "profiles": {
                    "core-trust": {
                        "description": "core",
                        "require_mutation": True,
                        "minimum_mutation_score": 95,
                        "minimum_group_percent": 95,
                        "files": {"src/agent_evals/authority.py": 95},
                    },
                    "optional": {
                        "description": "optional",
                        "require_mutation": False,
                        "minimum_mutation_score": None,
                        "minimum_group_percent": 90,
                        "files": {"src/agent_evals/adapters/optional.py": 90},
                    },
                },
            },
        )
        coverage_path = root / "coverage.json"
        _write_json(
            coverage_path,
            {
                "files": {
                    "src/agent_evals/authority.py": {
                        "summary": {
                            "num_statements": 2,
                            "covered_lines": 2,
                            "num_branches": 20,
                            "covered_branches": 19,
                        }
                    },
                    "src/agent_evals/adapters/optional.py": {
                        "summary": {
                            "num_statements": 10,
                            "covered_lines": 9,
                            "num_branches": 0,
                            "covered_branches": 0,
                        }
                    },
                }
            },
        )
        evaluate(
            manifest_path,
            coverage_path,
            profile_id="core-trust",
            repository_root=root,
        )
        evaluate(
            manifest_path,
            coverage_path,
            profile_id="optional",
            repository_root=root,
        )

        broken = _load_json(coverage_path)
        broken["files"]["src/agent_evals/authority.py"]["summary"]["covered_branches"] = 18
        broken_path = root / "broken.json"
        _write_json(broken_path, broken)
        try:
            evaluate(
                manifest_path,
                broken_path,
                profile_id="core-trust",
                repository_root=root,
            )
        except CoveragePolicyError:
            pass
        else:
            raise CoveragePolicyError("self-test accepted below-threshold branch coverage")

        mutation = _load_json(mutation_dir / "deep_targets.json")
        mutation["minimum_score"] = 94
        _write_json(mutation_dir / "deep_targets.json", mutation)
        try:
            evaluate(
                manifest_path,
                coverage_path,
                profile_id="core-trust",
                repository_root=root,
            )
        except CoveragePolicyError:
            pass
        else:
            raise CoveragePolicyError("self-test accepted insufficient mutation policy")
    print("coverage policy self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".github/coverage/thresholds.json"),
    )
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--repository-root", type=Path, default=Path())
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.coverage is None or args.profile is None:
        parser.error("--coverage and --profile are required unless --self-test is used")
    try:
        messages = evaluate(
            args.manifest,
            args.coverage,
            profile_id=args.profile,
            repository_root=args.repository_root,
        )
    except CoveragePolicyError as exc:
        parser.exit(1, f"coverage policy failed: {exc}\n")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
