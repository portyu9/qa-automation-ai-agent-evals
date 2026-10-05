from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "agent-evals/release-request/v1"
CANDIDATE_SCHEMA = "agent-evals/release-candidate/v1"
REQUEST_WORKFLOW_NAME = "Release request"
REQUEST_WORKFLOW_PATH = ".github/workflows/release-request.yml"
CI_WORKFLOW_NAME = "CI"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
DEFAULT_BRANCH = "main"
PROJECT_NAME = "qa-automation-ai-agent-evals"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TAG = re.compile(r"^v[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$")


class ReleaseCandidateError(RuntimeError):
    """A release request or candidate failed closed validation."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseCandidateError(f"duplicate JSON object key: {key}")
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


def _load_canonical_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError(f"{path} is not valid UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ReleaseCandidateError(f"{path} root must be an object")
    if raw != _canonical_bytes(value):
        raise ReleaseCandidateError(f"{path} JSON must be canonical")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ReleaseCandidateError(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ReleaseCandidateError(f"{label} must be an integer >= 1")
    return value


def require_sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA40.fullmatch(value) is None:
        raise ReleaseCandidateError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def require_repository(value: object, label: str = "repository") -> str:
    if type(value) is not str or _REPOSITORY.fullmatch(value) is None:
        raise ReleaseCandidateError(f"{label} must be canonical owner/name text")
    return value


def require_tag(value: object) -> str:
    if type(value) is not str or _TAG.fullmatch(value) is None:
        raise ReleaseCandidateError("version_tag must be a canonical v-prefixed tag")
    return value


def validate_request_workflow_event(event: dict[str, Any], *, repository: str) -> tuple[int, int]:
    if event.get("action") != "completed":
        raise ReleaseCandidateError("workflow_run event action must be completed")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseCandidateError("workflow_run repository does not match expected repository")
    run = event.get("workflow_run")
    if type(run) is not dict:
        raise ReleaseCandidateError("workflow_run event is missing workflow_run object")
    if run.get("name") != REQUEST_WORKFLOW_NAME or run.get("path") != REQUEST_WORKFLOW_PATH:
        raise ReleaseCandidateError("triggering workflow is not the canonical Release request workflow")
    if run.get("event") != "workflow_dispatch":
        raise ReleaseCandidateError("Release request must originate from workflow_dispatch")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ReleaseCandidateError("Release request workflow must be completed successfully")
    run_id = require_positive_int(run.get("id"), "request workflow run id")
    run_attempt = require_positive_int(run.get("run_attempt"), "request workflow run attempt")
    return run_id, run_attempt


def validate_request_payload(
    payload: dict[str, Any],
    *,
    repository: str,
    request_run_id: int,
    request_run_attempt: int,
) -> tuple[str, int]:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "repository",
            "version_tag",
            "ci_run_id",
            "request_run_id",
            "request_run_attempt",
        },
        "release request",
    )
    if payload["schema_version"] != REQUEST_SCHEMA:
        raise ReleaseCandidateError("unsupported release request schema_version")
    if require_repository(payload["repository"]) != repository:
        raise ReleaseCandidateError("release request repository does not match workflow repository")
    tag = require_tag(payload["version_tag"])
    ci_run_id = require_positive_int(payload["ci_run_id"], "ci_run_id")
    if require_positive_int(payload["request_run_id"], "request_run_id") != request_run_id:
        raise ReleaseCandidateError("release request run id does not match triggering workflow")
    if (
        require_positive_int(payload["request_run_attempt"], "request_run_attempt")
        != request_run_attempt
    ):
        raise ReleaseCandidateError("release request run attempt does not match triggering workflow")
    return tag, ci_run_id


def validate_ci_run(run: dict[str, Any], *, repository: str, expected_run_id: int) -> tuple[str, int]:
    if require_positive_int(run.get("id"), "CI run id") != expected_run_id:
        raise ReleaseCandidateError("CI run id does not match requested run")
    repo = run.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseCandidateError("CI run repository does not match expected repository")
    if run.get("name") != CI_WORKFLOW_NAME or run.get("path") != CI_WORKFLOW_PATH:
        raise ReleaseCandidateError("requested run is not the canonical CI workflow")
    if run.get("event") != "push":
        raise ReleaseCandidateError("release CI evidence must come from a push run")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ReleaseCandidateError("release CI run must be completed successfully")
    if run.get("head_branch") != DEFAULT_BRANCH:
        raise ReleaseCandidateError("release CI run must qualify the default branch")
    sha = require_sha(run.get("head_sha"), "CI head_sha")
    attempt = require_positive_int(run.get("run_attempt"), "CI run attempt")
    return sha, attempt


def validate_version_binding(
    *,
    version_tag: str,
    ci_sha: str,
    tag_sha: str,
    pyproject_bytes: bytes,
) -> str:
    version_tag = require_tag(version_tag)
    ci_sha = require_sha(ci_sha, "CI head_sha")
    tag_sha = require_sha(tag_sha, "tag target SHA")
    if tag_sha != ci_sha:
        raise ReleaseCandidateError("version tag does not resolve to the CI-qualified commit")
    try:
        project = tomllib.loads(pyproject_bytes.decode("utf-8")).get("project")
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseCandidateError("candidate pyproject.toml is not valid UTF-8 TOML") from exc
    if type(project) is not dict:
        raise ReleaseCandidateError("candidate pyproject.toml is missing [project]")
    if project.get("name") != PROJECT_NAME:
        raise ReleaseCandidateError("candidate project name does not match repository package")
    version = project.get("version")
    if type(version) is not str or not version or version != version.strip() or len(version) > 127:
        raise ReleaseCandidateError("candidate project.version must be non-empty trimmed text")
    if version_tag != f"v{version}":
        raise ReleaseCandidateError("version tag must equal v<project.version>")
    return version


def _request_json(url: str, token: str, *, not_found_ok: bool = False) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "qa-automation-retained-release",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"), object_pairs_hook=_strict_object)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not_found_ok:
            return None
        raise ReleaseCandidateError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseCandidateError(f"GitHub API transport failure: {exc.reason}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError("GitHub API returned malformed JSON") from exc
    if type(payload) is not dict:
        raise ReleaseCandidateError("GitHub API response must be an object")
    return payload


def _api_url(api_url: str, repository: str, suffix: str) -> str:
    api_url = api_url.rstrip("/")
    if not api_url.startswith("https://"):
        raise ReleaseCandidateError("GitHub API URL must use HTTPS")
    repository = require_repository(repository)
    return f"{api_url}/repos/{repository}/{suffix.lstrip('/')}"


def fetch_ci_run(api_url: str, repository: str, run_id: int, token: str) -> dict[str, Any]:
    result = _request_json(
        _api_url(api_url, repository, f"actions/runs/{require_positive_int(run_id, 'ci_run_id')}"),
        token,
    )
    assert result is not None
    return result


def resolve_tag_commit(api_url: str, repository: str, version_tag: str, token: str) -> str:
    version_tag = require_tag(version_tag)
    encoded = urllib.parse.quote(version_tag, safe="")
    ref = _request_json(_api_url(api_url, repository, f"git/ref/tags/{encoded}"), token)
    assert ref is not None
    if ref.get("ref") != f"refs/tags/{version_tag}":
        raise ReleaseCandidateError("GitHub tag ref does not match requested version tag")
    obj = ref.get("object")
    if type(obj) is not dict:
        raise ReleaseCandidateError("GitHub tag ref is missing object metadata")
    obj_type = obj.get("type")
    obj_sha = require_sha(obj.get("sha"), "tag object SHA")
    if obj_type == "commit":
        return obj_sha
    if obj_type != "tag":
        raise ReleaseCandidateError("version tag must point to a commit or annotated tag")
    annotated = _request_json(_api_url(api_url, repository, f"git/tags/{obj_sha}"), token)
    assert annotated is not None
    if annotated.get("tag") != version_tag:
        raise ReleaseCandidateError("annotated tag name does not match requested version tag")
    target = annotated.get("object")
    if type(target) is not dict or target.get("type") != "commit":
        raise ReleaseCandidateError("annotated version tag must point directly to a commit")
    return require_sha(target.get("sha"), "annotated tag commit SHA")


def fetch_pyproject(api_url: str, repository: str, commit_sha: str, token: str) -> bytes:
    commit_sha = require_sha(commit_sha, "candidate commit SHA")
    encoded_ref = urllib.parse.quote(commit_sha, safe="")
    payload = _request_json(
        _api_url(api_url, repository, f"contents/pyproject.toml?ref={encoded_ref}"), token
    )
    assert payload is not None
    if payload.get("type") != "file" or payload.get("path") != "pyproject.toml":
        raise ReleaseCandidateError("candidate pyproject.toml API response is not the expected file")
    if payload.get("encoding") != "base64" or type(payload.get("content")) is not str:
        raise ReleaseCandidateError("candidate pyproject.toml content is not base64 encoded")
    try:
        encoded = "".join(payload["content"].split())
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ReleaseCandidateError("candidate pyproject.toml has invalid base64 content") from exc
    if len(data) > 1024 * 1024:
        raise ReleaseCandidateError("candidate pyproject.toml exceeds 1 MiB")
    return data


def require_release_absent(api_url: str, repository: str, version_tag: str, token: str) -> None:
    encoded = urllib.parse.quote(require_tag(version_tag), safe="")
    existing = _request_json(
        _api_url(api_url, repository, f"releases/tags/{encoded}"),
        token,
        not_found_ok=True,
    )
    if existing is not None:
        raise ReleaseCandidateError("GitHub Release already exists for requested version tag")


def write_outputs(
    *,
    version_tag: str,
    ci_run_id: int,
    ci_run_attempt: int,
    commit_sha: str,
    output_path: Path,
) -> None:
    values = {
        "version_tag": require_tag(version_tag),
        "ci_run_id": str(require_positive_int(ci_run_id, "ci_run_id")),
        "ci_run_attempt": str(require_positive_int(ci_run_attempt, "ci_run_attempt")),
        "commit_sha": require_sha(commit_sha, "commit_sha"),
    }
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    candidate = {
        "schema_version": CANDIDATE_SCHEMA,
        "version_tag": values["version_tag"],
        "ci_run_id": int(values["ci_run_id"]),
        "ci_run_attempt": int(values["ci_run_attempt"]),
        "commit_sha": values["commit_sha"],
    }
    output_path.write_bytes(_canonical_bytes(candidate))


def validate_candidate(
    *,
    request_path: Path,
    event_path: Path,
    repository: str,
    api_url: str,
    token: str,
    output_path: Path,
) -> None:
    repository = require_repository(repository)
    if not token:
        raise ReleaseCandidateError("GITHUB_TOKEN is required for release candidate validation")
    if not request_path.is_file() or request_path.is_symlink():
        raise ReleaseCandidateError("release request artifact must be a regular file")
    try:
        siblings = list(request_path.parent.iterdir())
    except OSError as exc:
        raise ReleaseCandidateError("cannot inspect release request artifact directory") from exc
    if (
        len(siblings) != 1
        or siblings[0].name != request_path.name
        or not siblings[0].is_file()
        or siblings[0].is_symlink()
    ):
        raise ReleaseCandidateError(
            "release request artifact must contain exactly one regular JSON file"
        )
    try:
        event_raw = event_path.read_bytes()
        event_value = json.loads(event_raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError("workflow event file is not valid UTF-8 JSON") from exc
    if type(event_value) is not dict:
        raise ReleaseCandidateError("workflow event root must be an object")
    request_run_id, request_run_attempt = validate_request_workflow_event(
        event_value, repository=repository
    )
    payload = _load_canonical_json(request_path)
    version_tag, ci_run_id = validate_request_payload(
        payload,
        repository=repository,
        request_run_id=request_run_id,
        request_run_attempt=request_run_attempt,
    )
    ci_run = fetch_ci_run(api_url, repository, ci_run_id, token)
    commit_sha, ci_run_attempt = validate_ci_run(
        ci_run, repository=repository, expected_run_id=ci_run_id
    )
    tag_sha = resolve_tag_commit(api_url, repository, version_tag, token)
    pyproject_bytes = fetch_pyproject(api_url, repository, commit_sha, token)
    validate_version_binding(
        version_tag=version_tag,
        ci_sha=commit_sha,
        tag_sha=tag_sha,
        pyproject_bytes=pyproject_bytes,
    )
    require_release_absent(api_url, repository, version_tag, token)
    write_outputs(
        version_tag=version_tag,
        ci_run_id=ci_run_id,
        ci_run_attempt=ci_run_attempt,
        commit_sha=commit_sha,
        output_path=output_path,
    )


def self_test() -> None:
    repo = "owner/repo"
    sha = "a" * 40
    event = {
        "action": "completed",
        "repository": {"full_name": repo},
        "workflow_run": {
            "id": 11,
            "run_attempt": 2,
            "name": REQUEST_WORKFLOW_NAME,
            "path": REQUEST_WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        },
    }
    assert validate_request_workflow_event(event, repository=repo) == (11, 2)
    for field, bad in (
        ("name", "Other"),
        ("path", ".github/workflows/other.yml"),
        ("event", "push"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
    ):
        mutated = json.loads(json.dumps(event))
        mutated["workflow_run"][field] = bad
        try:
            validate_request_workflow_event(mutated, repository=repo)
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError(f"self-test accepted invalid request workflow {field}")

    request = {
        "schema_version": REQUEST_SCHEMA,
        "repository": repo,
        "version_tag": "v1.2.3",
        "ci_run_id": 22,
        "request_run_id": 11,
        "request_run_attempt": 2,
    }
    assert validate_request_payload(
        request, repository=repo, request_run_id=11, request_run_attempt=2
    ) == ("v1.2.3", 22)
    for field, bad in (
        ("schema_version", "wrong"),
        ("repository", "other/repo"),
        ("version_tag", "1.2.3"),
        ("ci_run_id", 0),
        ("request_run_id", 12),
        ("request_run_attempt", 3),
    ):
        mutated = dict(request, **{field: bad})
        try:
            validate_request_payload(
                mutated, repository=repo, request_run_id=11, request_run_attempt=2
            )
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError(f"self-test accepted invalid request field {field}")

    ci = {
        "id": 22,
        "repository": {"full_name": repo},
        "name": CI_WORKFLOW_NAME,
        "path": CI_WORKFLOW_PATH,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_branch": DEFAULT_BRANCH,
        "head_sha": sha,
        "run_attempt": 3,
    }
    assert validate_ci_run(ci, repository=repo, expected_run_id=22) == (sha, 3)
    for field, bad in (
        ("name", "Other"),
        ("path", ".github/workflows/other.yml"),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_branch", "feature"),
        ("head_sha", "bad"),
        ("run_attempt", 0),
    ):
        mutated = dict(ci, **{field: bad})
        try:
            validate_ci_run(mutated, repository=repo, expected_run_id=22)
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError(f"self-test accepted invalid CI field {field}")

    pyproject = b'[project]\nname = "qa-automation-ai-agent-evals"\nversion = "1.2.3"\n'
    assert (
        validate_version_binding(
            version_tag="v1.2.3", ci_sha=sha, tag_sha=sha, pyproject_bytes=pyproject
        )
        == "1.2.3"
    )
    for kwargs in (
        {"version_tag": "v9.9.9", "ci_sha": sha, "tag_sha": sha, "pyproject_bytes": pyproject},
        {"version_tag": "v1.2.3", "ci_sha": sha, "tag_sha": "b" * 40, "pyproject_bytes": pyproject},
        {
            "version_tag": "v1.2.3",
            "ci_sha": sha,
            "tag_sha": sha,
            "pyproject_bytes": b'[project]\nname="other"\nversion="1.2.3"\n',
        },
    ):
        try:
            validate_version_binding(**kwargs)
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError("self-test accepted invalid version/tag/SHA binding")

    print("release candidate self-test: ok")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--event", type=Path, required=True)
    validate.add_argument("--repository", required=True)
    validate.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    validate.add_argument("--output", type=Path, default=Path("validated-release.json"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "self-test":
            self_test()
        else:
            validate_candidate(
                request_path=args.request,
                event_path=args.event,
                repository=args.repository,
                api_url=args.api_url,
                token=os.environ.get("GITHUB_TOKEN", ""),
                output_path=args.output,
            )
    except (ReleaseCandidateError, OSError) as exc:
        raise SystemExit(f"release candidate validation failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
