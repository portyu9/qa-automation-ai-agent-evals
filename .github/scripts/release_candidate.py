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

CANDIDATE_SCHEMA = "agent-evals/release-candidate/v1"
DISPATCH_TYPE = "release-request"
PYPI_DISPATCH_TYPE = "pypi-publish-request"
CI_WORKFLOW_NAME = "CI"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
REPRODUCIBILITY_JOB_NAME = "Reproduce package artifacts independently"
SUPPLY_CHAIN_JOB_NAME = "Reverify release supply-chain evidence"
QUALIFICATION_JOB_NAME = "Retain CI qualification evidence"
RELEASE_STATEMENT_JOB_NAME = "Retain release compatibility statement"
PROVENANCE_JOB_NAME = "Attest retained release artifacts"
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


def validate_dispatch_event(
    event: dict[str, Any], *, repository: str, workflow_ref: str, workflow_sha: str
) -> tuple[str, int]:
    if event.get("action") != DISPATCH_TYPE:
        raise ReleaseCandidateError("repository_dispatch action must be release-request")
    repo = event.get("repository")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseCandidateError(
            "repository_dispatch repository does not match expected repository"
        )
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseCandidateError("release publisher must execute on the default branch ref")
    require_sha(workflow_sha, "publisher workflow SHA")

    payload = event.get("client_payload")
    if type(payload) is not dict:
        raise ReleaseCandidateError("repository_dispatch client_payload must be an object")
    _require_exact_keys(payload, {"version_tag", "ci_run_id"}, "release request payload")
    version_tag = require_tag(payload["version_tag"])
    ci_run_id = require_positive_int(payload["ci_run_id"], "ci_run_id")
    return version_tag, ci_run_id


def validate_pypi_release_record(
    release: dict[str, Any], *, expected_tag: str | None = None
) -> str:
    if type(release) is not dict:
        raise ReleaseCandidateError("published release must be an object")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ReleaseCandidateError(
            "PyPI publication requires a non-draft non-prerelease GitHub Release"
        )
    version_tag = require_tag(release.get("tag_name"))
    if expected_tag is not None and version_tag != require_tag(expected_tag):
        raise ReleaseCandidateError("published release tag does not match requested version tag")
    assets = release.get("assets")
    if type(assets) is not list or not assets:
        raise ReleaseCandidateError("published release must contain retained release assets")
    names: list[str] = []
    for asset in assets:
        if type(asset) is not dict or type(asset.get("name")) is not str or not asset["name"]:
            raise ReleaseCandidateError("release assets must have non-empty names")
        names.append(asset["name"])
    if len(names) != len(set(names)):
        raise ReleaseCandidateError("release asset names must be unique")
    required = {
        "artifact-manifest.json",
        "release-sbom.spdx.json",
        "release-supply-chain-evidence.json",
        "ci-qualification-evidence.json",
        "release-statement.json",
        "release-provenance.sigstore.json",
        "subject-checksums.sha256",
        "bundle-checksum.sha256",
    }
    missing = sorted(required - set(names))
    if missing:
        raise ReleaseCandidateError(
            f"published release is missing retained evidence assets: {missing}"
        )
    if len([name for name in names if name.endswith(".whl")]) != 1:
        raise ReleaseCandidateError("published release must contain exactly one wheel")
    if len([name for name in names if name.endswith(".tar.gz")]) != 1:
        raise ReleaseCandidateError(
            "published release must contain exactly one source distribution"
        )
    return version_tag


def validate_pypi_release_event(
    event: dict[str, Any], *, repository: str, workflow_ref: str, event_sha: str
) -> tuple[str, str]:
    repo = event.get("repository")
    if event.get("action") != "published":
        raise ReleaseCandidateError("release event action must be published")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseCandidateError("release event repository does not match expected repository")
    release = event.get("release")
    if type(release) is not dict:
        raise ReleaseCandidateError("release event must contain a release object")
    version_tag = validate_pypi_release_record(release)
    if workflow_ref != f"refs/tags/{version_tag}":
        raise ReleaseCandidateError("release workflow ref must match the published version tag")
    return version_tag, require_sha(event_sha, "release event SHA")


def validate_pypi_dispatch_event(
    event: dict[str, Any], *, repository: str, workflow_ref: str, event_sha: str
) -> tuple[str, str]:
    repo = event.get("repository")
    if event.get("action") != PYPI_DISPATCH_TYPE:
        raise ReleaseCandidateError("repository_dispatch action must be pypi-publish-request")
    if type(repo) is not dict or repo.get("full_name") != repository:
        raise ReleaseCandidateError(
            "PyPI repository_dispatch repository does not match expected repository"
        )
    if workflow_ref != f"refs/heads/{DEFAULT_BRANCH}":
        raise ReleaseCandidateError(
            "PyPI repository_dispatch must execute on the default branch ref"
        )
    require_sha(event_sha, "PyPI dispatch workflow SHA")
    payload = event.get("client_payload")
    if type(payload) is not dict:
        raise ReleaseCandidateError("PyPI repository_dispatch client_payload must be an object")
    _require_exact_keys(
        payload,
        {"version_tag", "commit_sha"},
        "PyPI publication request payload",
    )
    return require_tag(payload["version_tag"]), require_sha(
        payload["commit_sha"], "PyPI requested commit SHA"
    )


def validate_ci_run(
    run: dict[str, Any], *, repository: str, expected_run_id: int
) -> tuple[str, int]:
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


def validate_release_qualification_jobs(
    payload: dict[str, Any], *, ci_sha: str, ci_run_attempt: int
) -> None:
    ci_sha = require_sha(ci_sha, "CI head_sha")
    ci_run_attempt = require_positive_int(ci_run_attempt, "CI run attempt")
    total_count = payload.get("total_count")
    jobs = payload.get("jobs")
    if type(total_count) is not int or total_count < 1 or type(jobs) is not list:
        raise ReleaseCandidateError("CI jobs response is malformed")
    if total_count != len(jobs):
        raise ReleaseCandidateError("CI jobs response is incomplete")

    for job_name, label in (
        (REPRODUCIBILITY_JOB_NAME, "reproducibility"),
        (SUPPLY_CHAIN_JOB_NAME, "supply-chain evidence"),
        (QUALIFICATION_JOB_NAME, "CI qualification evidence"),
        (RELEASE_STATEMENT_JOB_NAME, "release statement"),
        (PROVENANCE_JOB_NAME, "provenance attestation"),
    ):
        matches = [job for job in jobs if type(job) is dict and job.get("name") == job_name]
        if len(matches) != 1:
            raise ReleaseCandidateError(
                f"release CI run must contain exactly one {label} qualification job"
            )
        job = matches[0]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ReleaseCandidateError(f"release {label} qualification job must succeed")
        if require_sha(job.get("head_sha"), f"{label} job head_sha") != ci_sha:
            raise ReleaseCandidateError(
                f"{label} qualification job does not match CI-qualified commit"
            )
        if (
            require_positive_int(job.get("run_attempt"), f"{label} job run attempt")
            != ci_run_attempt
        ):
            raise ReleaseCandidateError(f"{label} qualification job does not match CI run attempt")


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
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not_found_ok:
            return None
        raise ReleaseCandidateError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseCandidateError(f"GitHub API transport failure: {exc.reason}") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ReleaseCandidateError("GitHub API response exceeds 2 MiB")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError("GitHub API returned malformed JSON") from exc
    if type(payload) is not dict:
        raise ReleaseCandidateError("GitHub API response must be an object")
    return payload


def _api_url(api_url: str, repository: str, suffix: str) -> str:
    api_url = api_url.rstrip("/")
    if api_url != "https://api.github.com":
        raise ReleaseCandidateError("release publication requires canonical https://api.github.com")
    repository = require_repository(repository)
    return f"{api_url}/repos/{repository}/{suffix.lstrip('/')}"


def fetch_ci_run(api_url: str, repository: str, run_id: int, token: str) -> dict[str, Any]:
    result = _request_json(
        _api_url(api_url, repository, f"actions/runs/{require_positive_int(run_id, 'ci_run_id')}"),
        token,
    )
    assert result is not None
    return result


def fetch_ci_jobs(api_url: str, repository: str, run_id: int, token: str) -> dict[str, Any]:
    result = _request_json(
        _api_url(
            api_url,
            repository,
            f"actions/runs/{require_positive_int(run_id, 'ci_run_id')}/jobs?filter=latest&per_page=100",
        ),
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
        raise ReleaseCandidateError(
            "candidate pyproject.toml API response is not the expected file"
        )
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


def fetch_release(api_url: str, repository: str, version_tag: str, token: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(require_tag(version_tag), safe="")
    release = _request_json(
        _api_url(api_url, repository, f"releases/tags/{encoded}"),
        token,
    )
    assert release is not None
    return release


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
    workflow_sha: str,
    output_path: Path,
) -> None:
    values = {
        "version_tag": require_tag(version_tag),
        "ci_run_id": str(require_positive_int(ci_run_id, "ci_run_id")),
        "ci_run_attempt": str(require_positive_int(ci_run_attempt, "ci_run_attempt")),
        "commit_sha": require_sha(commit_sha, "commit_sha"),
        "publisher_workflow_sha": require_sha(workflow_sha, "publisher workflow SHA"),
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
        "publisher_workflow_sha": values["publisher_workflow_sha"],
    }
    output_path.write_bytes(_canonical_bytes(candidate))


def validate_candidate(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    workflow_sha: str,
    api_url: str,
    token: str,
    output_path: Path,
) -> None:
    repository = require_repository(repository)
    if not token:
        raise ReleaseCandidateError("GITHUB_TOKEN is required for release candidate validation")
    try:
        raw = event_path.read_bytes()
        event = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError(
            "repository_dispatch event file is not valid UTF-8 JSON"
        ) from exc
    if type(event) is not dict:
        raise ReleaseCandidateError("repository_dispatch event root must be an object")
    version_tag, ci_run_id = validate_dispatch_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
    )
    ci_run = fetch_ci_run(api_url, repository, ci_run_id, token)
    commit_sha, ci_run_attempt = validate_ci_run(
        ci_run, repository=repository, expected_run_id=ci_run_id
    )
    ci_jobs = fetch_ci_jobs(api_url, repository, ci_run_id, token)
    validate_release_qualification_jobs(
        ci_jobs,
        ci_sha=commit_sha,
        ci_run_attempt=ci_run_attempt,
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
        workflow_sha=workflow_sha,
        output_path=output_path,
    )


def validate_pypi_release(
    *,
    event_path: Path,
    repository: str,
    workflow_ref: str,
    event_sha: str,
    api_url: str,
    token: str,
    output_path: Path,
) -> None:
    repository = require_repository(repository)
    if not token:
        raise ReleaseCandidateError("GITHUB_TOKEN is required for PyPI release validation")
    try:
        event = json.loads(
            event_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError("PyPI publication event file is not valid UTF-8 JSON") from exc
    if type(event) is not dict:
        raise ReleaseCandidateError("PyPI publication event root must be an object")

    action = event.get("action")
    if action == "published":
        version_tag, expected_commit_sha = validate_pypi_release_event(
            event,
            repository=repository,
            workflow_ref=workflow_ref,
            event_sha=event_sha,
        )
    elif action == PYPI_DISPATCH_TYPE:
        version_tag, expected_commit_sha = validate_pypi_dispatch_event(
            event,
            repository=repository,
            workflow_ref=workflow_ref,
            event_sha=event_sha,
        )
    else:
        raise ReleaseCandidateError(
            "PyPI publication requires a published release event or pypi-publish-request"
        )

    published_release = fetch_release(api_url, repository, version_tag, token)
    validate_pypi_release_record(published_release, expected_tag=version_tag)

    tag_sha = resolve_tag_commit(api_url, repository, version_tag, token)
    if tag_sha != expected_commit_sha:
        raise ReleaseCandidateError(
            "published release tag commit does not match the authorized publication commit"
        )
    pyproject_bytes = fetch_pyproject(api_url, repository, tag_sha, token)
    version = validate_version_binding(
        version_tag=version_tag,
        ci_sha=tag_sha,
        tag_sha=tag_sha,
        pyproject_bytes=pyproject_bytes,
    )
    output = {
        "schema_version": "agent-evals/pypi-release-candidate/v1",
        "repository": repository,
        "version": version,
        "version_tag": version_tag,
        "commit_sha": tag_sha,
    }
    output_path.write_bytes(_canonical_bytes(output))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"version={version}\n")
            stream.write(f"version_tag={version_tag}\n")
            stream.write(f"commit_sha={tag_sha}\n")


def self_test() -> None:
    repo = "owner/repo"
    sha = "a" * 40
    event = {
        "action": DISPATCH_TYPE,
        "repository": {"full_name": repo},
        "client_payload": {"version_tag": "v1.2.3", "ci_run_id": 22},
    }
    assert validate_dispatch_event(
        event,
        repository=repo,
        workflow_ref="refs/heads/main",
        workflow_sha=sha,
    ) == ("v1.2.3", 22)
    invalid_events = (
        dict(event, action="other"),
        dict(event, repository={"full_name": "other/repo"}),
        dict(event, client_payload={"version_tag": "1.2.3", "ci_run_id": 22}),
        dict(event, client_payload={"version_tag": "v1.2.3", "ci_run_id": 0}),
        dict(event, client_payload={"version_tag": "v1.2.3", "ci_run_id": 22, "extra": 1}),
    )
    for mutated in invalid_events:
        try:
            validate_dispatch_event(
                mutated,
                repository=repo,
                workflow_ref="refs/heads/main",
                workflow_sha=sha,
            )
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError("self-test accepted invalid repository_dispatch event")
    for bad_ref, bad_sha in (("refs/heads/feature", sha), ("refs/heads/main", "bad")):
        try:
            validate_dispatch_event(
                event,
                repository=repo,
                workflow_ref=bad_ref,
                workflow_sha=bad_sha,
            )
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError("self-test accepted invalid publisher workflow binding")

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

    repro_job = {
        "name": REPRODUCIBILITY_JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha,
        "run_attempt": 3,
    }
    supply_chain_job = {
        "name": SUPPLY_CHAIN_JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha,
        "run_attempt": 3,
    }
    qualification_job = {
        "name": QUALIFICATION_JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha,
        "run_attempt": 3,
    }
    release_statement_job = {
        "name": RELEASE_STATEMENT_JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha,
        "run_attempt": 3,
    }
    provenance_job = {
        "name": PROVENANCE_JOB_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha,
        "run_attempt": 3,
    }
    qualification_jobs = {
        "total_count": 5,
        "jobs": [
            repro_job,
            supply_chain_job,
            qualification_job,
            release_statement_job,
            provenance_job,
        ],
    }
    validate_release_qualification_jobs(qualification_jobs, ci_sha=sha, ci_run_attempt=3)
    invalid_job_sets = (
        {"total_count": 0, "jobs": []},
        {
            "total_count": 4,
            "jobs": [repro_job, supply_chain_job, qualification_job, provenance_job],
        },
        {
            "total_count": 5,
            "jobs": [
                dict(repro_job, conclusion="failure"),
                supply_chain_job,
                qualification_job,
                release_statement_job,
                provenance_job,
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                dict(supply_chain_job, conclusion="failure"),
                qualification_job,
                release_statement_job,
                provenance_job,
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                supply_chain_job,
                dict(qualification_job, conclusion="failure"),
                release_statement_job,
                provenance_job,
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                supply_chain_job,
                qualification_job,
                release_statement_job,
                dict(provenance_job, conclusion="failure"),
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                supply_chain_job,
                qualification_job,
                release_statement_job,
                dict(provenance_job, head_sha="b" * 40),
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                supply_chain_job,
                dict(qualification_job, run_attempt=2),
                release_statement_job,
                provenance_job,
            ],
        },
        {
            "total_count": 5,
            "jobs": [
                repro_job,
                supply_chain_job,
                qualification_job,
                dict(release_statement_job, conclusion="failure"),
                provenance_job,
            ],
        },
        {
            "total_count": 6,
            "jobs": [
                repro_job,
                supply_chain_job,
                qualification_job,
                release_statement_job,
                provenance_job,
            ],
        },
    )
    for mutated in invalid_job_sets:
        try:
            validate_release_qualification_jobs(mutated, ci_sha=sha, ci_run_attempt=3)
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError("self-test accepted invalid release qualification jobs")

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

    release_event = {
        "action": "published",
        "repository": {"full_name": repo},
        "release": {
            "draft": False,
            "prerelease": False,
            "tag_name": "v1.2.3",
            "assets": [
                {"name": "example.whl"},
                {"name": "example.tar.gz"},
                {"name": "artifact-manifest.json"},
                {"name": "release-sbom.spdx.json"},
                {"name": "release-supply-chain-evidence.json"},
                {"name": "ci-qualification-evidence.json"},
                {"name": "release-statement.json"},
                {"name": "release-provenance.sigstore.json"},
                {"name": "subject-checksums.sha256"},
                {"name": "bundle-checksum.sha256"},
            ],
        },
    }
    assert validate_pypi_release_event(
        release_event,
        repository=repo,
        workflow_ref="refs/tags/v1.2.3",
        event_sha=sha,
    ) == ("v1.2.3", sha)
    try:
        validate_pypi_release_event(
            dict(release_event, action="edited"),
            repository=repo,
            workflow_ref="refs/tags/v1.2.3",
            event_sha=sha,
        )
    except ReleaseCandidateError:
        pass
    else:
        raise ReleaseCandidateError("self-test accepted a non-published release event")

    pypi_dispatch_event = {
        "action": PYPI_DISPATCH_TYPE,
        "repository": {"full_name": repo},
        "client_payload": {"version_tag": "v1.2.3", "commit_sha": sha},
    }
    assert validate_pypi_dispatch_event(
        pypi_dispatch_event,
        repository=repo,
        workflow_ref="refs/heads/main",
        event_sha=sha,
    ) == ("v1.2.3", sha)
    invalid_pypi_dispatches = (
        dict(pypi_dispatch_event, action="other"),
        dict(pypi_dispatch_event, repository={"full_name": "other/repo"}),
        dict(
            pypi_dispatch_event,
            client_payload={"version_tag": "v1.2.3", "commit_sha": sha, "extra": 1},
        ),
        dict(
            pypi_dispatch_event,
            client_payload={"version_tag": "1.2.3", "commit_sha": sha},
        ),
        dict(
            pypi_dispatch_event,
            client_payload={"version_tag": "v1.2.3", "commit_sha": "bad"},
        ),
    )
    for mutated in invalid_pypi_dispatches:
        try:
            validate_pypi_dispatch_event(
                mutated,
                repository=repo,
                workflow_ref="refs/heads/main",
                event_sha=sha,
            )
        except ReleaseCandidateError:
            pass
        else:
            raise ReleaseCandidateError("self-test accepted invalid PyPI repository_dispatch event")
    try:
        validate_pypi_dispatch_event(
            pypi_dispatch_event,
            repository=repo,
            workflow_ref="refs/heads/feature",
            event_sha=sha,
        )
    except ReleaseCandidateError:
        pass
    else:
        raise ReleaseCandidateError("self-test accepted non-default-branch PyPI dispatch")

    print("release candidate self-test: ok")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    validate = sub.add_parser("validate")
    validate.add_argument("--event", type=Path, required=True)
    validate.add_argument("--repository", required=True)
    validate.add_argument("--workflow-ref", required=True)
    validate.add_argument("--workflow-sha", required=True)
    validate.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    validate.add_argument("--output", type=Path, default=Path("validated-release.json"))
    pypi = sub.add_parser("validate-pypi")
    pypi.add_argument("--event", type=Path, required=True)
    pypi.add_argument("--repository", required=True)
    pypi.add_argument("--workflow-ref", required=True)
    pypi.add_argument("--event-sha", required=True)
    pypi.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    pypi.add_argument("--output", type=Path, default=Path("validated-pypi-release.json"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "self-test":
            self_test()
        elif args.command == "validate":
            validate_candidate(
                event_path=args.event,
                repository=args.repository,
                workflow_ref=args.workflow_ref,
                workflow_sha=args.workflow_sha,
                api_url=args.api_url,
                token=os.environ.get("GITHUB_TOKEN", ""),
                output_path=args.output,
            )
        else:
            validate_pypi_release(
                event_path=args.event,
                repository=args.repository,
                workflow_ref=args.workflow_ref,
                event_sha=args.event_sha,
                api_url=args.api_url,
                token=os.environ.get("GITHUB_TOKEN", ""),
                output_path=args.output,
            )
    except (ReleaseCandidateError, OSError) as exc:
        raise SystemExit(f"release candidate validation failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
