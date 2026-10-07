"""Require append-only ADRs for governed assurance-semantic pull-request changes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "semantic-adr-policy.json"
_POLICY_SCHEMA = "agent-evals/semantic-adr-policy/v1"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ADR_NAME = re.compile(r"^docs/adr/([0-9]{4})-[a-z0-9][a-z0-9-]*\.md$")
_ACTION_LINE = re.compile(
    r"^\s*(?:-\s+)?uses:\s+(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)"
    r"@(?P<sha>[0-9a-f]{40})\s+#\s+v(?P<version>\d+(?:\.\d+){0,2})\s*$"
)
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
    automation_actor: str
    automation_path_prefix: str

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
        "automation_exemption",
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
    automation = raw["automation_exemption"]
    if type(automation) is not dict or set(automation) != {
        "actor",
        "kind",
        "path_prefix",
    }:
        raise AdrPolicyError("automation_exemption must match the versioned schema exactly")
    if automation["actor"] != "dependabot[bot]":
        raise AdrPolicyError("automation exemption actor must remain exact Dependabot identity")
    if automation["kind"] != "github-actions-immutable-pin-only":
        raise AdrPolicyError("automation exemption kind is unsupported")
    if automation["path_prefix"] != ".github/workflows/":
        raise AdrPolicyError("automation exemption path must remain GitHub workflows")
    if not all(item.endswith("/") and not item.startswith("/") for item in prefixes):
        raise AdrPolicyError("governed prefixes must be repository-relative directories")
    if not all(not item.endswith("/") and not item.startswith("/") for item in exact_paths):
        raise AdrPolicyError("governed exact paths must be repository-relative files")
    return Policy(
        adr_directory="docs/adr",
        governed_prefixes=prefixes,
        governed_exact_paths=exact_paths,
        automation_actor="dependabot[bot]",
        automation_path_prefix=".github/workflows/",
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


def _parse_action_change(line: str) -> tuple[str, str, tuple[int, ...]] | None:
    match = _ACTION_LINE.fullmatch(line)
    if match is None:
        return None
    return (
        match.group("action"),
        match.group("sha"),
        tuple(int(part) for part in match.group("version").split(".")),
    )


def _action_pin_patch_is_safe(patch: str) -> bool:
    removed: list[tuple[str, str, tuple[int, ...]]] = []
    added: list[tuple[str, str, tuple[int, ...]]] = []
    for raw in patch.splitlines():
        if not raw or raw.startswith(("diff --git ", "index ", "--- ", "+++ ", "@@ ", "\\")):
            continue
        if raw[0] not in {"+", "-"}:
            return False
        parsed = _parse_action_change(raw[1:])
        if parsed is None:
            return False
        (added if raw[0] == "+" else removed).append(parsed)

    if not removed or len(removed) != len(added):
        return False
    if Counter(item[0] for item in removed) != Counter(item[0] for item in added):
        return False
    for action in sorted({item[0] for item in removed}):
        old = [item for item in removed if item[0] == action]
        new = [item for item in added if item[0] == action]
        old_versions = {item[2] for item in old}
        new_versions = {item[2] for item in new}
        old_shas = {item[1] for item in old}
        new_shas = {item[1] for item in new}
        if (
            len(old_versions) != 1
            or len(new_versions) != 1
            or len(old_shas) != 1
            or len(new_shas) != 1
        ):
            return False
        if next(iter(new_versions)) <= next(iter(old_versions)):
            return False
        if next(iter(new_shas)) == next(iter(old_shas)):
            return False
    return True


def _dependabot_action_pin_exempt(
    policy: Policy,
    changes: tuple[Change, ...],
    *,
    actor: str,
    base_sha: str,
    head_sha: str,
) -> bool:
    if actor != policy.automation_actor:
        return False
    if _SHA.fullmatch(base_sha) is None or _SHA.fullmatch(head_sha) is None:
        raise AdrPolicyError("automation exemption requires canonical base/head SHAs")

    if not changes:
        return False
    workflow_paths: list[str] = []
    for change in changes:
        if (
            change.status != "M"
            or len(change.paths) != 1
            or not change.paths[0].startswith(policy.automation_path_prefix)
        ):
            return False
        workflow_paths.append(change.paths[0])

    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--unified=0",
                "--no-ext-diff",
                "--no-renames",
                f"{base_sha}...{head_sha}",
                "--",
                *sorted(set(workflow_paths)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdrPolicyError(
            f"cannot verify Dependabot workflow patch: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        raise AdrPolicyError("git diff failed while verifying Dependabot workflow patch")
    return _action_pin_patch_is_safe(result.stdout)


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
    automation_exempt: bool = False,
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
            "modifying, deleting, renaming, or copying: " + ", ".join(mutated_adrs)
        )

    governed = tuple(
        sorted({path for change in changes for path in change.paths if policy.governs(path)})
    )
    if not governed:
        return

    new_adrs = _new_adr_paths(changes, policy)
    if not new_adrs and automation_exempt:
        return
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
    old_sha = "a" * 40
    new_sha = "b" * 40
    safe_patch = (
        "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
        "index 1111111..2222222 100644\n"
        "--- a/.github/workflows/ci.yml\n"
        "+++ b/.github/workflows/ci.yml\n"
        "@@ -1 +1 @@\n"
        f"-uses: actions/checkout@{old_sha} # v7.0.0\n"
        f"+uses: actions/checkout@{new_sha} # v7.0.1\n"
    )
    if not _action_pin_patch_is_safe(safe_patch):
        raise AdrPolicyError("canonical action-pin update was not recognized")
    if _action_pin_patch_is_safe(safe_patch + "+run: echo bypass\n"):
        raise AdrPolicyError("non-action workflow change bypassed action-pin policy")
    workflow_change = (Change(status="M", paths=(".github/workflows/ci.yml",)),)
    if _dependabot_action_pin_exempt(
        policy,
        workflow_change,
        actor="portyu9",
        base_sha="0" * 40,
        head_sha="1" * 40,
    ):
        raise AdrPolicyError("non-Dependabot actor bypassed the ADR requirement")
    mixed_change = (*workflow_change, Change(status="M", paths=("pyproject.toml",)))
    if _dependabot_action_pin_exempt(
        policy,
        mixed_change,
        actor=policy.automation_actor,
        base_sha="0" * 40,
        head_sha="1" * 40,
    ):
        raise AdrPolicyError("mixed Dependabot change bypassed the ADR requirement")

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
        raise AdrPolicyError("new ADR incorrectly authorized mutation of an accepted ADR")

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
    parser.add_argument("--actor")
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
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
        if args.actor is None or args.base_sha is None or args.head_sha is None:
            raise AdrPolicyError("PR ADR validation requires actor and exact base/head SHAs")
        try:
            diff_text = args.changed_files.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AdrPolicyError(
                f"cannot read changed-file inventory: {type(exc).__name__}"
            ) from exc
        changes = parse_name_status(diff_text)
        automation_exempt = _dependabot_action_pin_exempt(
            policy,
            changes,
            actor=args.actor,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
        evaluate(
            policy,
            changes,
            validate_files=True,
            automation_exempt=automation_exempt,
        )
    except AdrPolicyError as exc:
        fail(str(exc))

    print("Semantic ADR policy: governed changes have an append-only accepted decision record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
