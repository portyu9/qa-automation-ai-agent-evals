from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

DISPATCH_TYPE = "release-preparation"
DEFAULT_BRANCH = "main"
SCHEMA_VERSION = "agent-evals/release-version-plan/v1"
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ReleaseVersionError(ValueError):
    """Release-version preparation failed closed."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseVersionError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def require_version(value: object, label: str = "version") -> str:
    if type(value) is not str or _VERSION.fullmatch(value) is None:
        raise ReleaseVersionError(f"{label} must be canonical stable SemVer X.Y.Z")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    version = require_version(value)
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def load_project_version(pyproject: Path) -> str:
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseVersionError("pyproject.toml must be valid UTF-8 TOML") from exc
    if type(project) is not dict:
        raise ReleaseVersionError("pyproject.toml must contain [project]")
    return require_version(project.get("version"), "project.version")


def apply_version(pyproject: Path, target_version: str) -> bool:
    target_version = require_version(target_version, "target version")
    current = load_project_version(pyproject)
    if version_tuple(target_version) < version_tuple(current):
        raise ReleaseVersionError("target version must not move backwards")
    if target_version == current:
        return False

    text = pyproject.read_text(encoding="utf-8")
    pattern = re.compile(r'(?ms)^(\[project\]\n(?:(?!^\[).)*?^version = ")[^"]+(")$')
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ReleaseVersionError("pyproject.toml must contain exactly one [project] version line")
    updated = pattern.sub(rf"\g<1>{target_version}\g<2>", text, count=1)
    pyproject.write_text(updated, encoding="utf-8")
    if load_project_version(pyproject) != target_version:
        raise ReleaseVersionError("version rewrite did not produce the requested project.version")
    return True


def validate_event(
    event: dict[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
) -> str:
    if type(repository) is not str or _REPOSITORY.fullmatch(repository) is None:
        raise ReleaseVersionError("repository must be canonical owner/name text")
    if event.get("action") != DISPATCH_TYPE:
        raise ReleaseVersionError("repository_dispatch action must be release-preparation")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseVersionError("event repository does not match expected repository")
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseVersionError("release preparation must execute on the default branch")
    if _SHA40.fullmatch(workflow_sha) is None:
        raise ReleaseVersionError("workflow SHA must be a lowercase 40-character Git SHA")
    payload = event.get("client_payload")
    if type(payload) is not dict or set(payload) != {"version"}:
        raise ReleaseVersionError("release-preparation payload must contain exactly version")
    return require_version(payload["version"], "requested version")


def prepare(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
    pyproject: Path,
    output_path: Path,
) -> dict[str, object]:
    try:
        event = json.loads(
            event_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVersionError("event file must be valid UTF-8 JSON") from exc
    if type(event) is not dict:
        raise ReleaseVersionError("event root must be an object")

    target = validate_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
    )
    current = load_project_version(pyproject)
    if version_tuple(target) < version_tuple(current):
        raise ReleaseVersionError("requested version must not move backwards")
    changed = apply_version(pyproject, target)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": workflow_sha,
        "current_version": current,
        "target_version": target,
        "version_tag": f"v{target}",
        "mode": "bump" if changed else "release-current",
        "changed_files": ["pyproject.toml"] if changed else [],
    }
    output_path.write_bytes(_canonical_bytes(plan))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"target_version={target}\n")
            stream.write(f"version_tag=v{target}\n")
            stream.write(f"mode={plan['mode']}\n")
    return plan


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="release-version-") as raw:
        root = Path(raw)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        assert load_project_version(pyproject) == "0.1.0"
        assert apply_version(pyproject, "0.2.0") is True
        assert load_project_version(pyproject) == "0.2.0"
        assert apply_version(pyproject, "0.2.0") is False
        try:
            apply_version(pyproject, "0.1.9")
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted a backwards version")

        event = {
            "action": DISPATCH_TYPE,
            "repository": {"full_name": "owner/repo"},
            "client_payload": {"version": "1.2.3"},
        }
        assert (
            validate_event(
                event,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
            == "1.2.3"
        )
        bad = dict(event, client_payload={"version": "1.2.3", "extra": True})
        try:
            validate_event(
                bad,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted extra release-preparation payload data")
    print("release version preparation self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--event", type=Path, required=True)
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--workflow-ref", required=True)
    prepare_parser.add_argument("--workflow-sha", required=True)
    prepare_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    prepare_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return
        prepare(
            event_path=args.event,
            repository=args.repository,
            workflow_ref=args.workflow_ref,
            workflow_sha=args.workflow_sha,
            pyproject=args.pyproject,
            output_path=args.output,
        )
    except ReleaseVersionError as exc:
        raise SystemExit(f"release version preparation failed: {exc}") from exc


if __name__ == "__main__":
    main()
)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ReleaseVersionError("pyproject.toml must contain exactly one [project] version line")
    updated = pattern.sub(rf'\g<1>{target_version}\g<2>', text, count=1)
    pyproject.write_text(updated, encoding="utf-8")
    if load_project_version(pyproject) != target_version:
        raise ReleaseVersionError("version rewrite did not produce the requested project.version")
    return True


def validate_event(
    event: dict[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
) -> str:
    if type(repository) is not str or _REPOSITORY.fullmatch(repository) is None:
        raise ReleaseVersionError("repository must be canonical owner/name text")
    if event.get("action") != DISPATCH_TYPE:
        raise ReleaseVersionError("repository_dispatch action must be release-preparation")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseVersionError("event repository does not match expected repository")
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseVersionError("release preparation must execute on the default branch")
    if _SHA40.fullmatch(workflow_sha) is None:
        raise ReleaseVersionError("workflow SHA must be a lowercase 40-character Git SHA")
    payload = event.get("client_payload")
    if type(payload) is not dict or set(payload) != {"version"}:
        raise ReleaseVersionError("release-preparation payload must contain exactly version")
    return require_version(payload["version"], "requested version")


def prepare(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
    pyproject: Path,
    output_path: Path,
) -> dict[str, object]:
    try:
        event = json.loads(
            event_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVersionError("event file must be valid UTF-8 JSON") from exc
    if type(event) is not dict:
        raise ReleaseVersionError("event root must be an object")

    target = validate_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
    )
    current = load_project_version(pyproject)
    if version_tuple(target) < version_tuple(current):
        raise ReleaseVersionError("requested version must not move backwards")
    changed = apply_version(pyproject, target)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": workflow_sha,
        "current_version": current,
        "target_version": target,
        "version_tag": f"v{target}",
        "mode": "bump" if changed else "release-current",
        "changed_files": ["pyproject.toml"] if changed else [],
    }
    output_path.write_bytes(_canonical_bytes(plan))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"target_version={target}\n")
            stream.write(f"version_tag=v{target}\n")
            stream.write(f"mode={plan['mode']}\n")
    return plan


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="release-version-") as raw:
        root = Path(raw)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        assert load_project_version(pyproject) == "0.1.0"
        assert apply_version(pyproject, "0.2.0") is True
        assert load_project_version(pyproject) == "0.2.0"
        assert apply_version(pyproject, "0.2.0") is False
        try:
            apply_version(pyproject, "0.1.9")
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted a backwards version")

        event = {
            "action": DISPATCH_TYPE,
            "repository": {"full_name": "owner/repo"},
            "client_payload": {"version": "1.2.3"},
        }
        assert (
            validate_event(
                event,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
            == "1.2.3"
        )
        bad = dict(event, client_payload={"version": "1.2.3", "extra": True})
        try:
            validate_event(
                bad,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted extra release-preparation payload data")
    print("release version preparation self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--event", type=Path, required=True)
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--workflow-ref", required=True)
    prepare_parser.add_argument("--workflow-sha", required=True)
    prepare_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    prepare_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return
        prepare(
            event_path=args.event,
            repository=args.repository,
            workflow_ref=args.workflow_ref,
            workflow_sha=args.workflow_sha,
            pyproject=args.pyproject,
            output_path=args.output,
        )
    except ReleaseVersionError as exc:
        raise SystemExit(f"release version preparation failed: {exc}") from exc


if __name__ == "__main__":
    main()
)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ReleaseVersionError("pyproject.toml must contain exactly one [project] version line")
    updated = pattern.sub(rf"\g<1>{target_version}\g<2>", text, count=1)
    pyproject.write_text(updated, encoding="utf-8")
    if load_project_version(pyproject) != target_version:
        raise ReleaseVersionError("version rewrite did not produce the requested project.version")
    return True


def validate_event(
    event: dict[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
) -> str:
    if type(repository) is not str or _REPOSITORY.fullmatch(repository) is None:
        raise ReleaseVersionError("repository must be canonical owner/name text")
    if event.get("action") != DISPATCH_TYPE:
        raise ReleaseVersionError("repository_dispatch action must be release-preparation")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseVersionError("event repository does not match expected repository")
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseVersionError("release preparation must execute on the default branch")
    if _SHA40.fullmatch(workflow_sha) is None:
        raise ReleaseVersionError("workflow SHA must be a lowercase 40-character Git SHA")
    payload = event.get("client_payload")
    if type(payload) is not dict or set(payload) != {"version"}:
        raise ReleaseVersionError("release-preparation payload must contain exactly version")
    return require_version(payload["version"], "requested version")


def prepare(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
    pyproject: Path,
    output_path: Path,
) -> dict[str, object]:
    try:
        event = json.loads(
            event_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVersionError("event file must be valid UTF-8 JSON") from exc
    if type(event) is not dict:
        raise ReleaseVersionError("event root must be an object")

    target = validate_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
    )
    current = load_project_version(pyproject)
    if version_tuple(target) < version_tuple(current):
        raise ReleaseVersionError("requested version must not move backwards")
    changed = apply_version(pyproject, target)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": workflow_sha,
        "current_version": current,
        "target_version": target,
        "version_tag": f"v{target}",
        "mode": "bump" if changed else "release-current",
        "changed_files": ["pyproject.toml"] if changed else [],
    }
    output_path.write_bytes(_canonical_bytes(plan))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"target_version={target}\n")
            stream.write(f"version_tag=v{target}\n")
            stream.write(f"mode={plan['mode']}\n")
    return plan


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="release-version-") as raw:
        root = Path(raw)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        assert load_project_version(pyproject) == "0.1.0"
        assert apply_version(pyproject, "0.2.0") is True
        assert load_project_version(pyproject) == "0.2.0"
        assert apply_version(pyproject, "0.2.0") is False
        try:
            apply_version(pyproject, "0.1.9")
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted a backwards version")

        event = {
            "action": DISPATCH_TYPE,
            "repository": {"full_name": "owner/repo"},
            "client_payload": {"version": "1.2.3"},
        }
        assert (
            validate_event(
                event,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
            == "1.2.3"
        )
        bad = dict(event, client_payload={"version": "1.2.3", "extra": True})
        try:
            validate_event(
                bad,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted extra release-preparation payload data")
    print("release version preparation self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--event", type=Path, required=True)
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--workflow-ref", required=True)
    prepare_parser.add_argument("--workflow-sha", required=True)
    prepare_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    prepare_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return
        prepare(
            event_path=args.event,
            repository=args.repository,
            workflow_ref=args.workflow_ref,
            workflow_sha=args.workflow_sha,
            pyproject=args.pyproject,
            output_path=args.output,
        )
    except ReleaseVersionError as exc:
        raise SystemExit(f"release version preparation failed: {exc}") from exc


if __name__ == "__main__":
    main()
)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ReleaseVersionError("pyproject.toml must contain exactly one [project] version line")
    updated = pattern.sub(rf'\g<1>{target_version}\g<2>', text, count=1)
    pyproject.write_text(updated, encoding="utf-8")
    if load_project_version(pyproject) != target_version:
        raise ReleaseVersionError("version rewrite did not produce the requested project.version")
    return True


def validate_event(
    event: dict[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
) -> str:
    if type(repository) is not str or _REPOSITORY.fullmatch(repository) is None:
        raise ReleaseVersionError("repository must be canonical owner/name text")
    if event.get("action") != DISPATCH_TYPE:
        raise ReleaseVersionError("repository_dispatch action must be release-preparation")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseVersionError("event repository does not match expected repository")
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseVersionError("release preparation must execute on the default branch")
    if _SHA40.fullmatch(workflow_sha) is None:
        raise ReleaseVersionError("workflow SHA must be a lowercase 40-character Git SHA")
    payload = event.get("client_payload")
    if type(payload) is not dict or set(payload) != {"version"}:
        raise ReleaseVersionError("release-preparation payload must contain exactly version")
    return require_version(payload["version"], "requested version")


def prepare(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
    pyproject: Path,
    output_path: Path,
) -> dict[str, object]:
    try:
        event = json.loads(
            event_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVersionError("event file must be valid UTF-8 JSON") from exc
    if type(event) is not dict:
        raise ReleaseVersionError("event root must be an object")

    target = validate_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
    )
    current = load_project_version(pyproject)
    if version_tuple(target) < version_tuple(current):
        raise ReleaseVersionError("requested version must not move backwards")
    changed = apply_version(pyproject, target)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": workflow_sha,
        "current_version": current,
        "target_version": target,
        "version_tag": f"v{target}",
        "mode": "bump" if changed else "release-current",
        "changed_files": ["pyproject.toml"] if changed else [],
    }
    output_path.write_bytes(_canonical_bytes(plan))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"target_version={target}\n")
            stream.write(f"version_tag=v{target}\n")
            stream.write(f"mode={plan['mode']}\n")
    return plan


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="release-version-") as raw:
        root = Path(raw)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        assert load_project_version(pyproject) == "0.1.0"
        assert apply_version(pyproject, "0.2.0") is True
        assert load_project_version(pyproject) == "0.2.0"
        assert apply_version(pyproject, "0.2.0") is False
        try:
            apply_version(pyproject, "0.1.9")
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted a backwards version")

        event = {
            "action": DISPATCH_TYPE,
            "repository": {"full_name": "owner/repo"},
            "client_payload": {"version": "1.2.3"},
        }
        assert (
            validate_event(
                event,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
            == "1.2.3"
        )
        bad = dict(event, client_payload={"version": "1.2.3", "extra": True})
        try:
            validate_event(
                bad,
                repository="owner/repo",
                workflow_ref="refs/heads/main",
                workflow_sha="a" * 40,
            )
        except ReleaseVersionError:
            pass
        else:
            raise ReleaseVersionError("self-test accepted extra release-preparation payload data")
    print("release version preparation self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--event", type=Path, required=True)
    prepare_parser.add_argument("--repository", required=True)
    prepare_parser.add_argument("--workflow-ref", required=True)
    prepare_parser.add_argument("--workflow-sha", required=True)
    prepare_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    prepare_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return
        prepare(
            event_path=args.event,
            repository=args.repository,
            workflow_ref=args.workflow_ref,
            workflow_sha=args.workflow_sha,
            pyproject=args.pyproject,
            output_path=args.output,
        )
    except ReleaseVersionError as exc:
        raise SystemExit(f"release version preparation failed: {exc}") from exc


if __name__ == "__main__":
    main()
