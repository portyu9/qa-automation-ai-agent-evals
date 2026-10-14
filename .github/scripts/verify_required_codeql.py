"""Require independent CodeQL and Security evidence for the protected aggregate gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKFLOW_NAME = "CodeQL"
WORKFLOW_PATH = ".github/workflows/codeql.yml"
SECURITY_WORKFLOW_NAME = "Security"
SECURITY_WORKFLOW_PATH = ".github/workflows/security.yml"
SECURITY_REQUIRED_JOBS = frozenset({"Security scanners", "security-gate"})
ACTIVE_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


class GateError(RuntimeError):
    """Fail-closed protected-gate error."""


class TransientApiError(GateError):
    """Retryable GitHub API transport/server error."""


def require_sha(value: str) -> str:
    if SHA.fullmatch(value) is None:
        raise GateError("subject SHA must be a canonical 40-character lowercase SHA")
    return value


def allowed_events(trigger_event: str) -> set[str]:
    if trigger_event == "pull_request":
        return {"pull_request"}
    if trigger_event == "push":
        return {"push"}
    if trigger_event == "workflow_dispatch":
        return {"push", "workflow_dispatch"}
    if trigger_event == "schedule":
        return {"push", "workflow_dispatch"}
    raise GateError(f"unsupported CI trigger event for protected gate: {trigger_event}")


def select_codeql_runs(
    rows: list[dict[str, Any]],
    *,
    subject_sha: str,
    branch: str,
    trigger_event: str,
    required_workflow_name: str = WORKFLOW_NAME,
    required_workflow_path: str = WORKFLOW_PATH,
) -> list[dict[str, Any]]:
    if (required_workflow_name, required_workflow_path) not in {
        (WORKFLOW_NAME, WORKFLOW_PATH),
        (SECURITY_WORKFLOW_NAME, SECURITY_WORKFLOW_PATH),
    }:
        raise GateError("unapproved security workflow identity")
    subject_sha = require_sha(subject_sha)
    if not branch or branch.strip() != branch:
        raise GateError("subject branch must be a non-empty canonical ref name")
    events = allowed_events(trigger_event)
    candidates: list[dict[str, Any]] = []
    run_ids: set[int] = set()

    for row in rows:
        if (
            row.get("name") != required_workflow_name
            or row.get("path") != required_workflow_path
            or row.get("head_sha") != subject_sha
            or row.get("head_branch") != branch
            or row.get("event") not in events
        ):
            continue

        run_id = row.get("id")
        attempt = row.get("run_attempt")
        status = row.get("status")
        conclusion = row.get("conclusion")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise GateError(f"exact-subject {required_workflow_name} run has invalid run id")
        if run_id in run_ids:
            raise GateError(f"duplicate exact-subject {required_workflow_name} run id: {run_id}")
        run_ids.add(run_id)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise GateError(f"exact-subject {required_workflow_name} run has invalid run_attempt")
        if status not in ACTIVE_STATUSES | {"completed"}:
            raise GateError(
                f"exact-subject {required_workflow_name} run has invalid status: {status!r}"
            )
        if status == "completed" and conclusion != "success":
            raise GateError(
                f"exact-subject {required_workflow_name} run completed non-successfully: {conclusion!r}"
            )
        if status != "completed" and conclusion is not None:
            raise GateError(
                f"non-terminal exact-subject {required_workflow_name} run unexpectedly has a conclusion"
            )
        candidates.append(row)

    # Never select a convenient green subset; every matched run is an obligation.
    return sorted(candidates, key=lambda row: row["id"])


def fetch_runs(repository: str, subject_sha: str, token: str) -> list[dict[str, Any]]:
    if REPOSITORY.fullmatch(repository) is None:
        raise GateError("repository must be in owner/name form")
    subject_sha = require_sha(subject_sha)
    if not token:
        raise GateError("GITHUB_TOKEN is required to read exact-subject workflow evidence")

    encoded_sha = urllib.parse.quote(subject_sha, safe="")
    url = (
        f"https://api.github.com/repos/{repository}/actions/runs"
        f"?head_sha={encoded_sha}&per_page=100"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "qa-automation-required-codeql-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 500, 502, 503, 504}:
            raise TransientApiError(f"GitHub Actions API transient HTTP {exc.code}") from exc
        raise GateError(f"GitHub Actions API rejected evidence query: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TransientApiError(f"GitHub Actions API transport failure: {exc.reason}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("GitHub Actions API returned malformed JSON") from exc

    if not isinstance(payload, dict):
        raise GateError("GitHub Actions API payload must be an object")
    rows = payload.get("workflow_runs")
    count = payload.get("total_count")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise GateError("GitHub Actions API workflow_runs must be an object list")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(rows):
        raise GateError("GitHub Actions API workflow_runs response is truncated or invalid")
    return rows


def wait_for_success(
    *,
    repository: str,
    subject_sha: str,
    branch: str,
    trigger_event: str,
    token: str,
    attempts: int,
    delay_seconds: float,
    required_workflow_name: str = WORKFLOW_NAME,
    required_workflow_path: str = WORKFLOW_PATH,
) -> list[dict[str, Any]]:
    if attempts < 1:
        raise GateError("attempts must be >= 1")
    if delay_seconds < 0:
        raise GateError("delay-seconds must be >= 0")

    last_transient: TransientApiError | None = None
    for attempt in range(1, attempts + 1):
        try:
            rows = fetch_runs(repository, subject_sha, token)
            last_transient = None
        except TransientApiError as exc:
            last_transient = exc
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)
            continue

        runs = select_codeql_runs(
            rows,
            subject_sha=subject_sha,
            branch=branch,
            trigger_event=trigger_event,
            required_workflow_name=required_workflow_name,
            required_workflow_path=required_workflow_path,
        )
        if runs and all(run["status"] == "completed" for run in runs):
            return runs
        if attempt < attempts:
            time.sleep(delay_seconds)

    if last_transient is not None:
        raise last_transient
    raise GateError(
        f"all exact-subject {required_workflow_name} successes did not register before "
        "the bounded gate timeout"
    )


def fetch_security_jobs(
    repository: str, token: str, *, run_id: int, attempt: int
) -> list[dict[str, Any]]:
    """Read the two independently executed Security jobs from the exact successful run."""
    if REPOSITORY.fullmatch(repository) is None or not token:
        raise GateError("Security job verification requires repository and Actions read token")
    if (
        not isinstance(run_id, int)
        or isinstance(run_id, bool)
        or run_id < 1
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
    ):
        raise GateError("Security job verification requires canonical run/attempt ids")
    url = (
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
        f"/attempts/{attempt}/jobs?per_page=100"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "qa-automation-required-security-jobs",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 500, 502, 503, 504}:
            raise TransientApiError(f"Security jobs API transient HTTP {exc.code}") from exc
        raise GateError(f"Security jobs API rejected evidence query: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TransientApiError(f"Security jobs API transport failure: {exc.reason}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("Security jobs API returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise GateError("Security jobs API payload must be an object")
    jobs = payload.get("jobs")
    count = payload.get("total_count")
    if (
        not isinstance(jobs, list)
        or not all(isinstance(job, dict) for job in jobs)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(jobs)
    ):
        raise GateError("Security jobs API returned invalid or truncated evidence")
    return jobs


def require_security_job_success(jobs: list[dict[str, Any]], *, run_id: int, attempt: int) -> None:
    """Reject skipped, failed, or missing scanners and the final security-gate."""
    observed: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise GateError("Security jobs evidence contains a non-object")
        name = job.get("name")
        if name not in SECURITY_REQUIRED_JOBS:
            continue
        if name in observed:
            raise GateError(f"duplicate security job evidence: {name}")
        observed.add(name)
        if (
            job.get("run_id") != run_id
            or job.get("run_attempt") != attempt
            or job.get("status") != "completed"
            or job.get("conclusion") != "success"
        ):
            raise GateError(f"required Security job did not succeed: {name}")
    if observed != SECURITY_REQUIRED_JOBS:
        raise GateError(
            f"Security job evidence missing required jobs: "
            f"{sorted(SECURITY_REQUIRED_JOBS - observed)}"
        )


def require_all_security_jobs(
    repository: str, token: str, runs: list[dict[str, Any]]
) -> None:
    """Prove that both required jobs passed in every independently successful run."""
    if not runs:
        raise GateError("no successful exact-subject Security workflows")
    for run in runs:
        jobs = fetch_security_jobs(
            repository, token, run_id=run["id"], attempt=run["run_attempt"]
        )
        require_security_job_success(
            jobs, run_id=run["id"], attempt=run["run_attempt"]
        )


def self_test() -> None:
    sha = "1" * 40
    canonical = {
        "id": 101,
        "name": WORKFLOW_NAME,
        "path": WORKFLOW_PATH,
        "head_sha": sha,
        "head_branch": "feature",
        "event": "pull_request",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    if (
        select_codeql_runs(
            [canonical],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
        != [canonical]
    ):
        raise GateError("self-test rejected canonical exact-subject CodeQL success")

    for wrong in (
        dict(canonical, head_sha="2" * 40),
        dict(canonical, head_branch="other"),
        dict(canonical, path=".github/workflows/not-codeql.yml"),
        dict(canonical, event="push"),
    ):
        if (
            select_codeql_runs(
                [wrong],
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
            )
            != []
        ):
            raise GateError("self-test accepted mismatched CodeQL evidence")

    try:
        select_codeql_runs(
            [dict(canonical, conclusion="failure")],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
    except GateError:
        pass
    else:
        raise GateError("self-test accepted terminal CodeQL failure")

    if (
        select_codeql_runs(
            [dict(canonical, id=102), canonical],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
        != [canonical, dict(canonical, id=102)]
    ):
        raise GateError("self-test rejected valid duplicate-SHA CodeQL successes")
    for bad in (
        [canonical, dict(canonical)],
        [canonical, dict(canonical, id=102, conclusion="failure")],
        [canonical, dict(canonical, id=102, conclusion="cancelled")],
        [canonical, dict(canonical, id=102, run_attempt=0)],
        [canonical, dict(canonical, id=102, conclusion="skipped")],
    ):
        try:
            select_codeql_runs(
                bad, subject_sha=sha, branch="feature", trigger_event="pull_request"
            )
        except GateError:
            pass
        else:
            raise GateError("self-test accepted duplicate/failed CodeQL run")

    if allowed_events("workflow_dispatch") != {"push", "workflow_dispatch"}:
        raise GateError("self-test rejected governed post-merge CodeQL event set")
    if allowed_events("schedule") != {"push", "workflow_dispatch"}:
        raise GateError("self-test rejected scheduled CI post-merge CodeQL event set")

    scheduled = dict(canonical, head_branch="main", event="push")
    for event in ("push", "workflow_dispatch"):
        if (
            select_codeql_runs(
                [dict(scheduled, event=event)],
                subject_sha=sha,
                branch="main",
                trigger_event="schedule",
            )
            == []
        ):
            raise GateError(f"self-test rejected exact-subject {event} evidence for scheduled CI")

    for event in ("pull_request", "schedule"):
        if (
            select_codeql_runs(
                [dict(scheduled, event=event)],
                subject_sha=sha,
                branch="main",
                trigger_event="schedule",
            )
            != []
        ):
            raise GateError(
                f"self-test accepted non-post-merge {event} CodeQL evidence for scheduled CI"
            )

    if (
        select_codeql_runs(
            [
                dict(scheduled, id=102, event="workflow_dispatch"),
                dict(scheduled, event="push"),
            ],
            subject_sha=sha,
            branch="main",
            trigger_event="schedule",
        )
        != [dict(scheduled, event="push"), dict(scheduled, id=102, event="workflow_dispatch")]
    ):
        raise GateError("self-test rejected two valid post-merge CodeQL runs")

    try:
        allowed_events("unknown")
    except GateError:
        pass
    else:
        raise GateError("self-test accepted unsupported CI trigger")

    security = dict(
        canonical,
        name=SECURITY_WORKFLOW_NAME,
        path=SECURITY_WORKFLOW_PATH,
    )
    if (
        select_codeql_runs(
            [security],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
            required_workflow_name=SECURITY_WORKFLOW_NAME,
            required_workflow_path=SECURITY_WORKFLOW_PATH,
        )
        != [security]
    ):
        raise GateError("self-test rejected exact-subject Security workflow")
    for unsafe in (
        dict(security, head_sha="2" * 40),
        dict(security, head_branch="wrong"),
        dict(security, path=WORKFLOW_PATH),
        dict(security, event="push"),
    ):
        if (
            select_codeql_runs(
                [unsafe],
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
                required_workflow_name=SECURITY_WORKFLOW_NAME,
                required_workflow_path=SECURITY_WORKFLOW_PATH,
            )
            != []
        ):
            raise GateError("self-test accepted mismatched Security workflow")
    for invalid in (
        dict(security, conclusion="failure"),
        dict(security, conclusion="cancelled"),
        dict(security, status="in_progress", conclusion="success"),
    ):
        try:
            select_codeql_runs(
                [invalid],
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
                required_workflow_name=SECURITY_WORKFLOW_NAME,
                required_workflow_path=SECURITY_WORKFLOW_PATH,
            )
        except GateError:
            pass
        else:
            raise GateError("self-test accepted unqualified Security workflow")
    if (
        select_codeql_runs(
            [dict(security, id=103, run_attempt=2), security],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
            required_workflow_name=SECURITY_WORKFLOW_NAME,
            required_workflow_path=SECURITY_WORKFLOW_PATH,
        )
        != [security, dict(security, id=103, run_attempt=2)]
    ):
        raise GateError("self-test rejected valid same-SHA Security runs")
    for bad in (
        [security, dict(security)],
        [security, dict(security, id=103, conclusion="failure")],
        [security, dict(security, id=103, status="queued", conclusion="success")],
    ):
        try:
            select_codeql_runs(
                bad,
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
                required_workflow_name=SECURITY_WORKFLOW_NAME,
                required_workflow_path=SECURITY_WORKFLOW_PATH,
            )
        except GateError:
            pass
        else:
            raise GateError("self-test accepted unqualified same-SHA Security run")

    security_jobs = [
        {
            "name": name,
            "run_id": 101,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        }
        for name in sorted(SECURITY_REQUIRED_JOBS)
    ]
    require_security_job_success(security_jobs, run_id=101, attempt=1)
    for altered in (
        [dict(security_jobs[0], conclusion="failure"), security_jobs[1]],
        [dict(security_jobs[0], conclusion="skipped"), security_jobs[1]],
        [dict(security_jobs[0], run_id=102), security_jobs[1]],
        [dict(security_jobs[0], run_attempt=2), security_jobs[1]],
        [dict(security_jobs[0], status="queued"), security_jobs[1]],
        security_jobs[:1],
        [security_jobs[0], security_jobs[0], security_jobs[1]],
    ):
        try:
            require_security_job_success(altered, run_id=101, attempt=1)
        except GateError:
            pass
        else:
            raise GateError("self-test accepted unsafe Security job evidence")

    from unittest.mock import patch

    queued = dict(canonical, id=103, status="queued", conclusion=None)
    with (
        patch(
            __name__ + ".fetch_runs",
            side_effect=[[canonical, queued], [canonical, dict(canonical, id=103)]],
        ),
        patch(__name__ + ".time.sleep"),
    ):
        seen = wait_for_success(
            repository="owner/repo",
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
            token="fake",
            attempts=2,
            delay_seconds=0,
        )
    if seen != [canonical, dict(canonical, id=103)]:
        raise GateError("self-test selected a green subset while another run was pending")
    with (
        patch(__name__ + ".fetch_runs", return_value=[canonical, queued]),
        patch(__name__ + ".time.sleep"),
    ):
        try:
            wait_for_success(
                repository="owner/repo",
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
                token="fake",
                attempts=2,
                delay_seconds=0,
            )
        except GateError:
            pass
        else:
            raise GateError("self-test accepted an unfinished same-SHA run")

    runs = [security, dict(security, id=103, run_attempt=2)]
    def good_jobs(_repository: str, _token: str, *, run_id: int, attempt: int) -> list[dict[str, Any]]:
        return [dict(row, run_id=run_id, run_attempt=attempt) for row in security_jobs]
    with patch(__name__ + ".fetch_security_jobs", side_effect=good_jobs) as mocked:
        require_all_security_jobs("owner/repo", "fake", runs)
        if mocked.call_count != len(runs):
            raise GateError("self-test did not verify jobs in every matching Security run")
    def bad_jobs(_repository: str, _token: str, *, run_id: int, attempt: int) -> list[dict[str, Any]]:
        result = good_jobs(_repository, _token, run_id=run_id, attempt=attempt)
        if run_id == 103:
            result[0]["conclusion"] = "failure"
        return result
    with patch(__name__ + ".fetch_security_jobs", side_effect=bad_jobs):
        try:
            require_all_security_jobs("owner/repo", "fake", runs)
        except GateError:
            pass
        else:
            raise GateError("self-test ignored failure in second matching Security run")

    print("required CodeQL and Security multi-run gates self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--workflow", choices=("codeql", "security"), default="codeql")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--subject-sha", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--trigger-event", default="")
    parser.add_argument("--attempts", type=int, default=36)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    security = args.workflow == "security"
    workflow_name = SECURITY_WORKFLOW_NAME if security else WORKFLOW_NAME
    workflow_path = SECURITY_WORKFLOW_PATH if security else WORKFLOW_PATH
    token = os.environ.get("GITHUB_TOKEN", "")
    runs = wait_for_success(
        repository=args.repository,
        subject_sha=args.subject_sha,
        branch=args.branch,
        trigger_event=args.trigger_event,
        token=token,
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
        required_workflow_name=workflow_name,
        required_workflow_path=workflow_path,
    )
    if security:
        require_all_security_jobs(args.repository, token, runs)
    receipts = [f"{run['id']}/{run['run_attempt']}" for run in runs]
    print(
        f"protected {workflow_name} gate accepted every exact-subject run: "
        f"receipts={receipts} sha={args.subject_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
