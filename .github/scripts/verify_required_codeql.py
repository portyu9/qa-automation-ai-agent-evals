"""Require exact-subject CodeQL success before the protected aggregate gate passes."""

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


def select_codeql_run(
    rows: list[dict[str, Any]],
    *,
    subject_sha: str,
    branch: str,
    trigger_event: str,
) -> dict[str, Any] | None:
    subject_sha = require_sha(subject_sha)
    if not branch or branch.strip() != branch:
        raise GateError("subject branch must be a non-empty canonical ref name")
    events = allowed_events(trigger_event)
    candidates: list[dict[str, Any]] = []

    for row in rows:
        if (
            row.get("name") != WORKFLOW_NAME
            or row.get("path") != WORKFLOW_PATH
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
            raise GateError("exact-subject CodeQL run has invalid run id")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise GateError("exact-subject CodeQL run has invalid run_attempt")
        if status not in ACTIVE_STATUSES | {"completed"}:
            raise GateError(f"exact-subject CodeQL run has invalid status: {status!r}")
        if status == "completed" and conclusion != "success":
            raise GateError(f"exact-subject CodeQL run completed non-successfully: {conclusion!r}")
        if status != "completed" and conclusion is not None:
            raise GateError("non-terminal exact-subject CodeQL run unexpectedly has a conclusion")
        candidates.append(row)

    if len(candidates) > 1:
        run_ids = sorted(int(row["id"]) for row in candidates)
        raise GateError(
            f"ambiguous exact-subject CodeQL evidence for {subject_sha}: run ids {run_ids}"
        )
    return candidates[0] if candidates else None


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
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise GateError("GitHub Actions API workflow_runs must be an object list")
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
) -> dict[str, Any]:
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

        run = select_codeql_run(
            rows,
            subject_sha=subject_sha,
            branch=branch,
            trigger_event=trigger_event,
        )
        if run is not None and run["status"] == "completed":
            return run
        if attempt < attempts:
            time.sleep(delay_seconds)

    if last_transient is not None:
        raise last_transient
    raise GateError("exact-subject CodeQL success did not register before the bounded gate timeout")


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
        select_codeql_run(
            [canonical],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
        != canonical
    ):
        raise GateError("self-test rejected canonical exact-subject CodeQL success")

    for wrong in (
        dict(canonical, head_sha="2" * 40),
        dict(canonical, head_branch="other"),
        dict(canonical, path=".github/workflows/not-codeql.yml"),
        dict(canonical, event="push"),
    ):
        if (
            select_codeql_run(
                [wrong],
                subject_sha=sha,
                branch="feature",
                trigger_event="pull_request",
            )
            is not None
        ):
            raise GateError("self-test accepted mismatched CodeQL evidence")

    try:
        select_codeql_run(
            [dict(canonical, conclusion="failure")],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
    except GateError:
        pass
    else:
        raise GateError("self-test accepted terminal CodeQL failure")

    try:
        select_codeql_run(
            [canonical, dict(canonical, id=102)],
            subject_sha=sha,
            branch="feature",
            trigger_event="pull_request",
        )
    except GateError:
        pass
    else:
        raise GateError("self-test accepted ambiguous CodeQL evidence")

    if allowed_events("workflow_dispatch") != {"push", "workflow_dispatch"}:
        raise GateError("self-test rejected governed post-merge CodeQL event set")
    if allowed_events("schedule") != {"push", "workflow_dispatch"}:
        raise GateError("self-test rejected scheduled CI post-merge CodeQL event set")

    scheduled = dict(canonical, head_branch="main", event="push")
    for event in ("push", "workflow_dispatch"):
        if (
            select_codeql_run(
                [dict(scheduled, event=event)],
                subject_sha=sha,
                branch="main",
                trigger_event="schedule",
            )
            is None
        ):
            raise GateError(f"self-test rejected exact-subject {event} evidence for scheduled CI")

    for event in ("pull_request", "schedule"):
        if (
            select_codeql_run(
                [dict(scheduled, event=event)],
                subject_sha=sha,
                branch="main",
                trigger_event="schedule",
            )
            is not None
        ):
            raise GateError(
                f"self-test accepted non-post-merge {event} CodeQL evidence for scheduled CI"
            )

    try:
        select_codeql_run(
            [
                dict(scheduled, event="push"),
                dict(scheduled, id=102, event="workflow_dispatch"),
            ],
            subject_sha=sha,
            branch="main",
            trigger_event="schedule",
        )
    except GateError:
        pass
    else:
        raise GateError("self-test accepted ambiguous scheduled-CI post-merge CodeQL evidence")

    try:
        allowed_events("unknown")
    except GateError:
        pass
    else:
        raise GateError("self-test accepted unsupported CI trigger")

    print("required CodeQL gate self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
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

    run = wait_for_success(
        repository=args.repository,
        subject_sha=args.subject_sha,
        branch=args.branch,
        trigger_event=args.trigger_event,
        token=os.environ.get("GITHUB_TOKEN", ""),
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
    )
    print(
        "protected CodeQL gate accepted exact-subject evidence: "
        f"run={run['id']} attempt={run['run_attempt']} sha={run['head_sha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
