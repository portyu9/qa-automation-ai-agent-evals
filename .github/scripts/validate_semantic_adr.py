"""Require append-only ADRs for governed assurance-semantic pull-request changes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "semantic-adr-policy.json"
_POLICY_SCHEMA = "agent-evals/semantic-adr-policy/v1"
_ADR_NAME = re.compile(r"^docs/adr/([0-9]{4})-[a-z0-9][a-z0-9-]*\.md$")
_REQUIRED_ADR_MARKERS = (
    "**Status:** Accepted",
    "## Context",
    "## Decision",
    "## Consequences",
    "## Assurance impact",
    "## Non-claims",
)


class AdrPolicyError(ValueError):
    """The ADR policy or a proposed change cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class Policy:
    adr_directory: str
    governed_prefixes: tuple[str, ...]
    governed_exact_paths: tuple[str, ...]

    def governs(self, path: str) -> bool:
        return path in self.governed_exact_paths or any(
            path.startswith(prefix) for prefix in self.governed_prefixes
        )


@dataclass(frozen=True, slots=True)
class Change:
    status: str
    paths: tuple[str, ...]


def fail(message: str) -> NoReturn:
    raise SystemExit(f"semantic ADR policy failed: {message}")


def _string_list(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AdrPolicyError(f"{label} must be a non-empty list")
    if not all(type(item) is str and item for item in value):
        raise AdrPolicyError(f"{label} must contain exact non-empty strings")
    items = tuple(value)
    if tuple(sorted(items)) != items or len(set(items)) != len(items):
        raise AdrPolicyError(f"{label} must be unique and lexicographically sorted")
    return items


def load_policy(path: Path = POLICY_PATH) -> Policy:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdrPolicyError(f"cannot load ADR policy: {type(exc).__name__}") from exc
    if type(raw) is not dict:
        raise AdrPolicyError("ADR policy root must be an exact object")
    expected_keys = {
        "schema_version",
        "adr_directory",
        "governed_prefixes",
        "governed_exact_paths",
    }
    if set(raw) != expected_keys:
        raise AdrPolicyError("ADR policy fields must match the versioned schema exactly")
    if raw["schema_version"] != _POLICY_SCHEMA:
        raise AdrPolicyError("unsupported ADR policy schema_version")
    if raw["adr_directory"] != "docs/adr":
        raise AdrPolicyError("ADR directory must remain docs/adr")

    prefixes = _string_list(raw["governed_prefixes"], label="governed_prefixes")
    exact_paths = _string_list(
        raw["governed_exact_paths"],
        label="governed_exact_paths",
    )
    if not all(item.endswith("/") and not item.startswith("/") for item in prefixes):
        raise AdrPolicyError("governed prefixes must be repository-relative directories")
    if not all(not item.endswith("/") and not item.startswith("/") for item in exact_paths):
        raise AdrPolicyError("governed exact paths must be repository-relative files")
    return Policy(
        adr_directory="docs/adr",
        governed_prefixes=prefixes,
        governed_exact_paths=exact_paths,
    )


def parse_name_status(text: str) -> tuple[Change, ...]:
    changes: list[Change] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise AdrPolicyError(f"blank diff record at line {line_number}")
        fields = line.split("\t")
        status = fields[0]
        kind = status[:1]
        if kind in {"A", "M", "D", "T"}:
            if len(fields) != 2 or len(status) != 1:
                raise AdrPolicyError(f"malformed diff record at line {line_number}")
            paths = (fields[1],)
        elif kind in {"R", "C"}:
            if len(fields) != 3 or not status[1:].isdigit():
                raise AdrPolicyError(f"malformed rename/copy record at line {line_number}")
            paths = (fields[1], fields[2])
        else:
            raise AdrPolicyError(f"unsupported diff status at line {line_number}: {status!r}")
        if any(not path or path.startswith("/") or "\x00" in path for path in paths):
            raise AdrPolicyError(f"invalid repository path at line {line_number}")
        changes.append(Change(status=status, paths=paths))
    return tuple(changes)


def _is_accepted_adr(path: str, policy: Policy) -> bool:
    prefix = f"{policy.adr_directory}/"
    if not path.startswith(prefix):
        return False
    match = _ADR_NAME.fullmatch(path)
    return match is not None and int(match.group(1)) >= 1


def _new_adr_paths(
    changes: tuple[Change, ...],
    policy: Policy,
) -> tuple[str, ...]:
    paths: list[str] = []
    prefix = f"{policy.adr_directory}/"
    for change in changes:
        if change.status != "A":
            continue
        path = change.paths[0]
        if not path.startswith(prefix):
            continue
        match = _ADR_NAME.fullmatch(path)
        if match is None or int(match.group(1)) < 1:
            continue
        paths.append(path)
    return tuple(sorted(paths))


def _validate_adr_document(path: str) -> None:
    match = _ADR_NAME.fullmatch(path)
    if match is None:
        raise AdrPolicyError(f"new ADR has a noncanonical filename: {path}")
    expected_number = match.group(1)
    try:
        content = (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AdrPolicyError(f"cannot read new ADR {path}: {type(exc).__name__}") from exc
    if not content.startswith(f"# ADR {expected_number}: "):
        raise AdrPolicyError(f"ADR {path} title must bind filename number {expected_number}")
    for marker in _REQUIRED_ADR_MARKERS:
        if marker not in content:
            raise AdrPolicyError(f"ADR {path} is missing required marker {marker!r}")


def evaluate(
    policy: Policy,
    changes: tuple[Change, ...],
    *,
    validate_files: bool,
) -> None:
    mutated_adrs = tuple(
        sorted(
            {
                path
                for change in changes
                if change.status != "A"
                for path in change.paths
                if _is_accepted_adr(path, policy)
            }
        )
    )
    if mutated_adrs:
        raise AdrPolicyError(
            "accepted ADRs are append-only; add a superseding ADR instead of "
            "modifying, deleting, renaming, or copying: "
            + ", ".join(mutated_adrs)
        )

    governed = tuple(
        sorted({path for change in changes for path in change.paths if policy.governs(path)})
    )
    if not governed:
        return

    new_adrs = _new_adr_paths(changes, policy)
    if not new_adrs:
        preview = ", ".join(governed[:5])
        suffix = "" if len(governed) <= 5 else ", ..."
        raise AdrPolicyError(
            "governed assurance-semantic changes require a newly added "
            f"numbered ADR; changed: {preview}{suffix}"
        )
    if validate_files:
        for path in new_adrs:
            _validate_adr_document(path)


def self_test(policy: Policy) -> None:
    evaluate(
        policy,
        parse_name_status("M\tdocs/README.md\n"),
        validate_files=False,
    )

    try:
        evaluate(
            policy,
            parse_name_status("M\tsrc/agent_evals/evidence/models.py\n"),
            validate_files=False,
        )
    except AdrPolicyError:
        pass
    else:
        raise AdrPolicyError("semantic change without a new ADR did not fail closed")

    evaluate(
        policy,
        parse_name_status(
            "M\tsrc/agent_evals/evidence/models.py\n"
            "A\tdocs/adr/0042-explicit-evidence-transition.md\n"
        ),
        validate_files=False,
    )

    try:
        evaluate(
            policy,
            parse_name_status("M\tdocs/adr/0001-existing-decision.md\n"),
            validate_files=False,
        )
    except AdrPolicyError:
        pass
    else:
        raise AdrPolicyError("ADR-only rewrite incorrectly bypassed append-only policy")

    try:
        evaluate(
            policy,
            parse_name_status(
                "M\tsrc/agent_evals/evidence/models.py\n"
                "M\tdocs/adr/0001-existing-decision.md\n"
                "A\tdocs/adr/0043-superseding-decision.md\n"
            ),
            validate_files=False,
        )
    except AdrPolicyError:
        pass
    else:
        raise AdrPolicyError(
            "new ADR incorrectly authorized mutation of an accepted ADR"
        )

    try:
        evaluate(
            policy,
            parse_name_status("R100\tdocs/old.md\tsrc/agent_evals/evidence/new.py\n"),
            validate_files=False,
        )
    except AdrPolicyError:
        pass
    else:
        raise AdrPolicyError("rename into a governed path did not require a new ADR")

    try:
        parse_name_status("X\tsrc/agent_evals/evidence/models.py\n")
    except AdrPolicyError:
        pass
    else:
        raise AdrPolicyError("unknown diff status did not fail closed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--changed-files", type=Path)
    args = parser.parse_args()

    try:
        policy = load_policy()
        if args.self_test:
            if args.changed_files is not None:
                raise AdrPolicyError("--self-test and --changed-files are mutually exclusive")
            self_test(policy)
            print("Semantic ADR policy self-test: PASS")
            return 0
        if args.changed_files is None:
            raise AdrPolicyError("--changed-files is required outside --self-test")
        try:
            diff_text = args.changed_files.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AdrPolicyError(
                f"cannot read changed-file inventory: {type(exc).__name__}"
            ) from exc
        changes = parse_name_status(diff_text)
        evaluate(policy, changes, validate_files=True)
    except AdrPolicyError as exc:
        fail(str(exc))

    print("Semantic ADR policy: governed changes have an append-only accepted decision record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
