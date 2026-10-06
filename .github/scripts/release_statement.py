from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "agent-evals/release-statement/v1"
EXPECTED_REF = "refs/heads/main"
EXPECTED_WORKFLOW = "CI"
GITHUB_RELEASE_MODE = "attested-retained-assets"
GITHUB_RELEASE_SIGNATURE_CLAIM = "not-claimed"
PYPI_TRUSTED_PUBLISHING_MODE = "not-enabled"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PYTHON_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (3\.\d+)$")

_COMPATIBILITY_LOCKS = (
    ("core", "minimum", "requirements/compatibility/core-minimum-py311.txt"),
    ("core", "latest", "requirements/compatibility/core-latest-py311.txt"),
    ("mcp", "minimum", "requirements/compatibility/mcp-minimum-py311.txt"),
    ("mcp", "latest", "requirements/compatibility/mcp-latest-py311.txt"),
    ("openai-mcp", "minimum", "requirements/compatibility/openai-mcp-minimum-py311.txt"),
    ("openai-mcp", "latest", "requirements/compatibility/openai-mcp-latest-py311.txt"),
)


class ReleaseStatementError(ValueError):
    """Release statement failed strict validation."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseStatementError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


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


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ReleaseStatementError(f"{label} must be non-empty normalized text")
    return value


def _require_repository(value: object) -> str:
    repository = _require_text(value, "repository")
    if _REPOSITORY.fullmatch(repository) is None:
        raise ReleaseStatementError("repository must be canonical owner/name text")
    return repository


def _require_sha(value: object, label: str = "commit_sha") -> str:
    if type(value) is not str or _SHA40.fullmatch(value) is None:
        raise ReleaseStatementError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ReleaseStatementError(f"{label} must be an integer >= 1")
    return value


def _require_regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ReleaseStatementError(f"{label} must be one regular file: {path}")
    return path


def _file_record(path: Path, *, role: str) -> dict[str, object]:
    _require_regular_file(path, role)
    data = path.read_bytes()
    return {
        "role": role,
        "filename": path.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _exact_files(directory: Path, expected_names: set[str], label: str) -> dict[str, Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseStatementError(f"{label} must be one real directory")
    entries = list(directory.iterdir())
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ReleaseStatementError(f"{label} must contain regular files only")
    actual = {entry.name for entry in entries}
    if actual != expected_names:
        raise ReleaseStatementError(
            f"{label} file set mismatch: missing={sorted(expected_names - actual)}, "
            f"extra={sorted(actual - expected_names)}"
        )
    return {entry.name: entry for entry in entries}


def _package_subjects(package_dir: Path) -> list[dict[str, object]]:
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise ReleaseStatementError("package_dir must be one real directory")
    entries = list(package_dir.iterdir())
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ReleaseStatementError("package_dir must contain regular files only")
    wheels = [entry for entry in entries if entry.name.endswith(".whl")]
    sdists = [entry for entry in entries if entry.name.endswith(".tar.gz")]
    manifests = [entry for entry in entries if entry.name == "artifact-manifest.json"]
    allowed = set(wheels + sdists + manifests)
    if len(wheels) != 1 or len(sdists) != 1 or len(manifests) != 1 or set(entries) != allowed:
        raise ReleaseStatementError(
            "package_dir must contain exactly one wheel, one sdist, and artifact-manifest.json"
        )
    return [
        _file_record(wheels[0], role="wheel"),
        _file_record(sdists[0], role="sdist"),
        _file_record(manifests[0], role="package-manifest"),
    ]


def _load_project(pyproject_path: Path) -> dict[str, object]:
    _require_regular_file(pyproject_path, "pyproject")
    try:
        parsed = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseStatementError("pyproject.toml must be valid UTF-8 TOML") from exc
    project = parsed.get("project")
    if type(project) is not dict:
        raise ReleaseStatementError("pyproject.toml must contain a [project] table")
    name = _require_text(project.get("name"), "project.name")
    version = _require_text(project.get("version"), "project.version")
    requires_python = _require_text(project.get("requires-python"), "project.requires-python")
    dependencies = project.get("dependencies")
    if (
        type(dependencies) is not list
        or not dependencies
        or any(type(item) is not str for item in dependencies)
    ):
        raise ReleaseStatementError("project.dependencies must be a non-empty string array")
    optional = project.get("optional-dependencies", {})
    if type(optional) is not dict:
        raise ReleaseStatementError("project.optional-dependencies must be a table")
    runtime_optional: dict[str, list[str]] = {}
    for group in sorted(optional):
        values = optional[group]
        if (
            type(group) is not str
            or type(values) is not list
            or any(type(item) is not str for item in values)
        ):
            raise ReleaseStatementError("optional dependency groups must be string arrays")
        if group != "dev":
            runtime_optional[group] = list(values)

    classifiers = project.get("classifiers", [])
    if type(classifiers) is not list or any(type(item) is not str for item in classifiers):
        raise ReleaseStatementError("project.classifiers must be a string array")
    supported_python = sorted(
        {
            match.group(1)
            for item in classifiers
            if (match := _PYTHON_CLASSIFIER.fullmatch(item)) is not None
        },
        key=lambda value: tuple(int(part) for part in value.split(".")),
    )
    if not supported_python:
        raise ReleaseStatementError("project classifiers must declare supported Python minors")
    expected_tag = f"v{version}"
    if not re.fullmatch(r"v[0-9A-Za-z][0-9A-Za-z._+-]{0,127}", expected_tag):
        raise ReleaseStatementError(
            "project.version cannot form the canonical expected release tag"
        )

    return {
        "name": name,
        "version": version,
        "expected_tag": expected_tag,
        "requires_python": requires_python,
        "supported_python": supported_python,
        "dependencies": list(dependencies),
        "optional_runtime_dependencies": runtime_optional,
        "pyproject_sha256": hashlib.sha256(pyproject_path.read_bytes()).hexdigest(),
    }


def _lock_headers(path: Path) -> dict[str, str]:
    _require_regular_file(path, "compatibility lock")
    headers: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        if not line.startswith("# ") or ": " not in line:
            continue
        key, value = line[2:].split(": ", 1)
        headers[key] = value
    required = {
        "Lock-Contract",
        "Profile",
        "Boundary",
        "Python",
        "Artifact-Selection",
        "Input-SHA256",
    }
    if not required <= set(headers):
        raise ReleaseStatementError(f"compatibility lock missing required headers: {path}")
    if headers["Lock-Contract"] != "agent-evals/dependency-compatibility-lock/v1":
        raise ReleaseStatementError(f"unsupported compatibility lock contract: {path}")
    if _SHA256.fullmatch(headers["Input-SHA256"]) is None:
        raise ReleaseStatementError(f"compatibility lock has invalid input digest: {path}")
    return headers


def _compatibility_records(repo_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for profile, boundary, relative in _COMPATIBILITY_LOCKS:
        path = repo_root / relative
        headers = _lock_headers(path)
        if headers["Profile"] != profile or headers["Boundary"] != boundary:
            raise ReleaseStatementError(f"compatibility lock identity mismatch: {relative}")
        if headers["Python"] != "3.11":
            raise ReleaseStatementError(f"compatibility lock Python boundary mismatch: {relative}")
        data = path.read_bytes()
        records.append(
            {
                "profile": profile,
                "boundary": boundary,
                "python": headers["Python"],
                "artifact_selection": headers["Artifact-Selection"],
                "path": relative,
                "input_sha256": headers["Input-SHA256"],
                "file_sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return records


def build_statement(
    *,
    repo_root: Path,
    package_dir: Path,
    supply_chain_dir: Path,
    qualification_dir: Path,
    repository: str,
    commit_sha: str,
    ref: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    repository = _require_repository(repository)
    commit_sha = _require_sha(commit_sha)
    if ref != EXPECTED_REF:
        raise ReleaseStatementError(f"ref must be exactly {EXPECTED_REF}")
    if workflow != EXPECTED_WORKFLOW:
        raise ReleaseStatementError(f"workflow must be exactly {EXPECTED_WORKFLOW}")
    run_id = _require_positive_int(run_id, "run_id")
    run_attempt = _require_positive_int(run_attempt, "run_attempt")
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise ReleaseStatementError("repo_root must be one real directory")

    package_contract = _load_project(repo_root / "pyproject.toml")
    subjects = _package_subjects(package_dir)

    supply = _exact_files(
        supply_chain_dir,
        {"release-sbom.spdx.json", "release-supply-chain-evidence.json"},
        "supply_chain_dir",
    )
    subjects.extend(
        [
            _file_record(supply["release-sbom.spdx.json"], role="spdx-sbom"),
            _file_record(
                supply["release-supply-chain-evidence.json"],
                role="supply-chain-evidence",
            ),
        ]
    )
    qualification = _exact_files(
        qualification_dir,
        {"ci-qualification-evidence.json"},
        "qualification_dir",
    )
    subjects.append(
        _file_record(
            qualification["ci-qualification-evidence.json"],
            role="ci-qualification-evidence",
        )
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "repository": repository,
            "commit_sha": commit_sha,
            "ref": EXPECTED_REF,
            "workflow": EXPECTED_WORKFLOW,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "package_contract": package_contract,
        "compatibility": _compatibility_records(repo_root),
        "subjects": subjects,
        "publication": {
            "github_release": GITHUB_RELEASE_MODE,
            "github_release_object_signature": GITHUB_RELEASE_SIGNATURE_CLAIM,
            "pypi_trusted_publishing": PYPI_TRUSTED_PUBLISHING_MODE,
        },
    }


def load_statement(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        decoded = raw.decode("utf-8")
        parsed = json.loads(
            decoded,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ReleaseStatementError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseStatementError("release statement must be valid UTF-8 JSON") from exc
    if type(parsed) is not dict:
        raise ReleaseStatementError("release statement root must be an object")
    if parsed.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseStatementError("unsupported release statement schema")
    if raw != _canonical_bytes(parsed):
        raise ReleaseStatementError("release statement is not canonical JSON")
    return parsed


def create_statement(*, output: Path, **kwargs: Any) -> None:
    statement = build_statement(**kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(statement))


def verify_statement(
    *,
    statement_path: Path,
    expected_tag: str | None = None,
    **kwargs: Any,
) -> dict[str, object]:
    actual = load_statement(statement_path)
    expected = build_statement(**kwargs)
    if actual != expected:
        raise ReleaseStatementError("release statement does not match exact retained inputs")
    tag = expected["package_contract"]["expected_tag"]  # type: ignore[index]
    if expected_tag is not None and expected_tag != tag:
        raise ReleaseStatementError(
            f"requested release tag {expected_tag!r} does not match statement tag {tag!r}"
        )
    return actual


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo_root = root / "repo"
        package = root / "package"
        supply = root / "supply"
        qualification = root / "qualification"
        for path in (repo_root / "requirements/compatibility", package, supply, qualification):
            path.mkdir(parents=True, exist_ok=True)
        (repo_root / "pyproject.toml").write_text(
            (
                "[project]\n"
                'name = "qa-automation-ai-agent-evals"\n'
                'version = "1.2.3"\n'
                'requires-python = ">=3.11,<3.15"\n'
                'dependencies = ["pydantic>=2,<3"]\n'
                "classifiers = [\n"
                '  "Programming Language :: Python :: 3.11",\n'
                '  "Programming Language :: Python :: 3.14",\n'
                "]\n"
                "[project.optional-dependencies]\n"
                'openai = ["openai-agents==0.22.3"]\n'
                'dev = ["pytest>=9,<10"]\n'
            ),
            encoding="utf-8",
        )
        for profile, boundary, relative in _COMPATIBILITY_LOCKS:
            path = repo_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(
                    (
                        "# Generated for self-test",
                        "# Lock-Contract: agent-evals/dependency-compatibility-lock/v1",
                        f"# Profile: {profile}",
                        f"# Boundary: {boundary}",
                        "# Python: 3.11",
                        "# Artifact-Selection: linux-x86_64",
                        f"# Input-SHA256: {'a' * 64}",
                        "example==1.0 --hash=sha256:" + "b" * 64,
                        "",
                    )
                ),
                encoding="utf-8",
            )
        (package / "example.whl").write_bytes(b"wheel")
        (package / "example.tar.gz").write_bytes(b"sdist")
        (package / "artifact-manifest.json").write_bytes(b"{}\n")
        (supply / "release-sbom.spdx.json").write_bytes(b"{}\n")
        (supply / "release-supply-chain-evidence.json").write_bytes(b"{}\n")
        (qualification / "ci-qualification-evidence.json").write_bytes(b"{}\n")
        statement_path = root / "release-statement.json"
        args = {
            "repo_root": repo_root,
            "package_dir": package,
            "supply_chain_dir": supply,
            "qualification_dir": qualification,
            "repository": "owner/repo",
            "commit_sha": "a" * 40,
            "ref": EXPECTED_REF,
            "workflow": EXPECTED_WORKFLOW,
            "run_id": 7,
            "run_attempt": 2,
        }
        create_statement(output=statement_path, **args)
        loaded = verify_statement(
            statement_path=statement_path,
            expected_tag="v1.2.3",
            **args,
        )
        publication = loaded["publication"]
        assert isinstance(publication, dict)
        assert publication["github_release_object_signature"] == "not-claimed"
        try:
            verify_statement(
                statement_path=statement_path,
                expected_tag="v9.9.9",
                **args,
            )
        except ReleaseStatementError:
            pass
        else:
            raise ReleaseStatementError("self-test accepted a mismatched release tag")

        mutated = statement_path.read_text(encoding="utf-8").replace(
            '"schema_version":"agent-evals/release-statement/v1"',
            '"schema_version":"agent-evals/release-statement/v0"',
        )
        statement_path.write_text(mutated, encoding="utf-8")
        try:
            verify_statement(statement_path=statement_path, **args)
        except ReleaseStatementError:
            pass
        else:
            raise ReleaseStatementError("self-test accepted a mutated schema")

    print("release statement self-test: ok")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--supply-chain-dir", type=Path, required=True)
    parser.add_argument("--qualification-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    _common(create)
    create.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify")
    _common(verify)
    verify.add_argument("--statement", type=Path, required=True)
    verify.add_argument("--expected-tag")

    sub.add_parser("self-test")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "self-test":
        self_test()
        return
    kwargs = {
        "repo_root": args.repo_root,
        "package_dir": args.package_dir,
        "supply_chain_dir": args.supply_chain_dir,
        "qualification_dir": args.qualification_dir,
        "repository": args.repository,
        "commit_sha": args.commit_sha,
        "ref": args.ref,
        "workflow": args.workflow,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
    }
    if args.command == "create":
        create_statement(output=args.output, **kwargs)
        return
    verify_statement(
        statement_path=args.statement,
        expected_tag=args.expected_tag,
        **kwargs,
    )


if __name__ == "__main__":
    main()
