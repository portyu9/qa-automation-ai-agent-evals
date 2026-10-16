"""Authenticate a read-only PR CodeQL run before trusted SARIF publication.

Executed ONLY from accepted-main source in the trusted main-owned scheduled consumer.
This module neither executes nor imports any checked-out PR files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "portyu9/qa-automation-ai-agent-evals"
WORKFLOW_ID = 359681797
WORKFLOW_PATH = ".github/workflows/codeql.yml"
CODEQL_CATEGORY = ".github/workflows/codeql.yml:codeql-upload"
SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_PRODUCER_FILES = (
    WORKFLOW_PATH,
    ".github/scripts/validate_codeql_sarif.py",
    ".github/scripts/validate_codeql_sarif_selfcheck.py",
    ".github/scripts/validate_security_stack.py",
)
CHECK_NAMES = (
    "Validate zero-alert gate implementation",
    "Initialize CodeQL",
    "Analyze",
    "Enforce zero CodeQL alerts",
    "Upload CodeQL SARIF evidence",
)


class Blocked(ValueError):
    """Required provenance is absent, contradictory or not independently verified."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Blocked(reason)


def obj(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label}: expected object")
    return value


def field(value: dict[str, Any], key: str, expected: Any, label: str) -> None:
    require(value.get(key) == expected, f"{label}: {key} is not the expected value")


def nested(data: Any, *keys: str) -> Any:
    for key in keys:
        data = obj(data, ".".join(keys)).get(key)
    return data


class GitHubRead:
    def __init__(self, token: str):
        require(bool(token), "read-only GitHub token missing")
        self.token = token

    def get(self, path: str) -> Any:
        require(path.startswith(f"/repos/{REPOSITORY}/"), "non-canonical GitHub API path")
        req = urllib.request.Request(
            "https://api.github.com" + path,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trusted-codeql-pr-evidence",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                require(response.status == 200, "GitHub read did not return 200")
                raw = response.read(8_000_001)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise Blocked(f"GitHub API provenance read failed: {type(exc).__name__}") from exc
        require(len(raw) <= 8_000_000, "GitHub response exceeded size limit")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Blocked("GitHub read was not valid JSON") from exc


def verify(api: Any, event: Any, *, trusted_main_sha: str | None = None) -> dict[str, str]:
    payload = obj(event, "workflow_run event")
    run_event = obj(payload.get("workflow_run"), "workflow_run payload")
    run_id = run_event.get("id")
    require(type(run_id) is int and run_id > 0, "invalid triggering run id")
    require(payload.get("action") == "completed", "unexpected workflow_run action")
    run = obj(api.get(f"/repos/{REPOSITORY}/actions/runs/{run_id}"), "canonical run")
    require(run.get("id") == run_id, "run identity mismatch")
    for key, value in (
        ("workflow_id", WORKFLOW_ID),
        ("path", WORKFLOW_PATH),
        ("name", "CodeQL"),
        ("event", "pull_request"),
        ("status", "completed"),
        ("conclusion", "success"),
        ("run_attempt", 1),
    ):
        field(run, key, value, "CodeQL run")
        field(run_event, key, value, "event run")
    head = run.get("head_sha")
    branch = run.get("head_branch")
    require(isinstance(head, str) and SHA.fullmatch(head) is not None, "invalid head SHA")
    require(isinstance(branch, str) and BRANCH.fullmatch(branch) is not None, "invalid head branch")
    require(
        ".." not in branch and not branch.startswith("/") and not branch.endswith("/"),
        "ambiguous head branch",
    )
    field(run_event, "head_sha", head, "event run")
    field(run_event, "head_branch", branch, "event run")
    require(
        nested(run, "head_repository", "full_name") == REPOSITORY,
        "fork PR is intentionally BLOCKED from trusted publication",
    )
    require(
        nested(run_event, "head_repository", "full_name") == REPOSITORY,
        "event run repository differs",
    )
    require(nested(run, "repository", "full_name") == REPOSITORY, "producer repository differs")

    main_ref = obj(api.get(f"/repos/{REPOSITORY}/git/ref/heads/main"), "main ref")
    main_sha = nested(main_ref, "object", "sha")
    require(
        isinstance(main_sha, str) and SHA.fullmatch(main_sha) is not None,
        "malformed accepted-main SHA",
    )
    require(main_ref.get("ref") == "refs/heads/main", "main ref identity drift")
    if trusted_main_sha is not None:
        require(
            isinstance(trusted_main_sha, str)
            and SHA.fullmatch(trusted_main_sha) is not None
            and main_sha == trusted_main_sha,
            "accepted main moved away from the workflow's pinned trusted source SHA",
        )
    matched = []
    for page in range(1, 4):
        candidates = api.get(
            f"/repos/{REPOSITORY}/pulls?state=open&base=main&per_page=100&page={page}"
        )
        require(isinstance(candidates, list) and len(candidates) <= 100, "malformed PR page")
        for pr in candidates:
            pr = obj(pr, "open PR")
            if nested(pr, "head", "sha") == head and nested(pr, "head", "ref") == branch:
                matched.append(pr)
        if len(candidates) < 100:
            break
    else:
        raise Blocked("open PR inventory exceeds bounded pagination")
    require(len(matched) == 1, "missing or ambiguous exact-head open PR")
    pr = matched[0]
    number = pr.get("number")
    require(type(number) is int and number > 0, "invalid PR number")
    field(pr, "state", "open", "PR")
    field(pr, "draft", False, "PR")
    require(nested(pr, "base", "ref") == "main", "non-main base")
    require(nested(pr, "base", "sha") == main_sha, "base moved after candidate scan")
    require(
        nested(pr, "head", "repo", "full_name") == REPOSITORY,
        "PR head repository is not the canonical trusted repository",
    )
    require(nested(pr, "base", "repo", "full_name") == REPOSITORY, "PR base repository differs")
    live = obj(api.get(f"/repos/{REPOSITORY}/pulls/{number}"), "exact PR detail")
    require(
        live.get("number") == number and nested(live, "head", "sha") == head,
        "PR moved during revalidation",
    )
    require(
        nested(live, "base", "sha") == main_sha and live.get("state") == "open",
        "PR/base changed after candidate discovery",
    )
    ref_branch = urllib.parse.quote(branch, safe="/")
    branch_ref = api.get(f"/repos/{REPOSITORY}/git/ref/heads/{ref_branch}")
    require(nested(branch_ref, "object", "sha") == head, "live PR branch moved")

    merge_ref = api.get(f"/repos/{REPOSITORY}/git/ref/pull/{number}/merge")
    merge_sha = nested(merge_ref, "object", "sha")
    require(
        merge_ref.get("ref") == f"refs/pull/{number}/merge"
        and isinstance(merge_sha, str)
        and SHA.fullmatch(merge_sha) is not None,
        "unverifiable PR merge ref",
    )
    head_commit = api.get(f"/repos/{REPOSITORY}/commits/{head}")
    merge_commit = api.get(f"/repos/{REPOSITORY}/commits/{merge_sha}")
    head_tree = nested(head_commit, "commit", "tree", "sha")
    merge_tree = nested(merge_commit, "commit", "tree", "sha")
    require(
        isinstance(head_tree, str) and SHA.fullmatch(head_tree) is not None,
        "malformed PR head source tree",
    )
    require(
        head_tree == merge_tree,
        "PR merge tree differs from head; cannot claim exact-source analysis",
    )
    # The read-only producer executes PR checked-out scripts. Prove all its
    # workflow/validator executable inputs are identical to trusted main.
    for path in SAFE_PRODUCER_FILES:
        urlpath = urllib.parse.quote(path, safe="/")
        trusted = api.get(f"/repos/{REPOSITORY}/contents/{urlpath}?ref={main_sha}")
        candidate = api.get(f"/repos/{REPOSITORY}/contents/{urlpath}?ref={head}")
        sha_trusted = obj(trusted, "trusted file").get("sha")
        sha_candidate = obj(candidate, "candidate file").get("sha")
        require(
            isinstance(sha_trusted, str) and SHA.fullmatch(sha_trusted) is not None,
            f"invalid accepted file identity: {path}",
        )
        require(
            sha_candidate == sha_trusted,
            f"PR alters CodeQL producer authority; publisher BLOCKED: {path}",
        )

    jobs = api.get(f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = obj(jobs, "CodeQL run jobs")
    require(
        type(jobs.get("total_count")) is int and jobs["total_count"] <= 100,
        "incomplete or oversized CodeQL jobs snapshot",
    )
    jobs_list = jobs.get("jobs")
    require(
        isinstance(jobs_list, list) and len(jobs_list) == jobs["total_count"],
        "CodeQL job list mismatch",
    )
    scanner_jobs = [j for j in jobs_list if isinstance(j, dict) and j.get("name") == "CodeQL"]
    require(len(scanner_jobs) == 1, "ambiguous CodeQL scanner job")
    scan = scanner_jobs[0]
    field(scan, "conclusion", "success", "CodeQL scanner job")
    field(scan, "status", "completed", "CodeQL scanner job")
    require(nested(scan, "head_sha") == head, "CodeQL scanner head not matched")
    steps = scan.get("steps")
    require(isinstance(steps, list), "CodeQL scan steps absent")
    for name in CHECK_NAMES:
        matched_steps = [st for st in steps if isinstance(st, dict) and st.get("name") == name]
        require(
            len(matched_steps) == 1 and matched_steps[0].get("conclusion") == "success",
            f"CodeQL required scan step absent or failed: {name}",
        )

    artifacts = api.get(f"/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = obj(artifacts, "CodeQL artifact list")
    require(
        type(artifacts.get("total_count")) is int and 0 < artifacts["total_count"] <= 100,
        "incomplete CodeQL artifacts",
    )
    collection = artifacts.get("artifacts")
    require(
        isinstance(collection, list) and len(collection) == artifacts["total_count"],
        "invalid CodeQL artifacts inventory",
    )
    named = [
        a for a in collection if isinstance(a, dict) and a.get("name") == f"codeql-sarif-{run_id}"
    ]
    require(len(named) == 1, "exact-run CodeQL SARIF artifact is missing/ambiguous")
    artifact = named[0]
    require(artifact.get("expired") is False, "CodeQL SARIF artifact expired")
    require(
        nested(artifact, "workflow_run", "id") == run_id
        and nested(artifact, "workflow_run", "head_sha") == head,
        "CodeQL artifact source run/head differs",
    )
    require(
        isinstance(artifact.get("digest"), str)
        and DIGEST.fullmatch(artifact["digest"]) is not None,
        "CodeQL artifact lacks authenticated GitHub upload digest",
    )
    size = artifact.get("size_in_bytes")
    require(type(size) is int and 100 <= size <= 12_000_000, "CodeQL artifact outside size limits")
    require(
        type(artifact.get("id")) is int and artifact["id"] > 0, "invalid CodeQL artifact identifier"
    )
    return {
        "pr_number": str(number),
        "head_sha": head,
        "base_sha": main_sha,
        "run_id": str(run_id),
        "artifact_id": str(artifact["id"]),
        "artifact_digest": artifact["digest"],
    }


def discover(api: Any, *, trusted_main_sha: str | None = None) -> dict[str, str] | None:
    """Re-read canonical completed PR runs; do not trust caller-supplied run IDs."""
    if trusted_main_sha is not None:
        main_ref = obj(api.get(f"/repos/{REPOSITORY}/git/ref/heads/main"), "scheduled main ref")
        require(
            main_ref.get("ref") == "refs/heads/main"
            and isinstance(trusted_main_sha, str)
            and SHA.fullmatch(trusted_main_sha) is not None
            and nested(main_ref, "object", "sha") == trusted_main_sha,
            "current main no longer matches immutable scheduled-workflow source",
        )
    prs = api.get(f"/repos/{REPOSITORY}/pulls?state=open&base=main&per_page=100&page=1")
    require(isinstance(prs, list) and len(prs) < 100, "open PR listing incomplete")
    active = set()
    for pr in prs:
        pr = obj(pr, "candidate open PR")
        if nested(pr, "head", "repo", "full_name") == REPOSITORY:
            active.add((nested(pr, "head", "sha"), nested(pr, "head", "ref")))
    if not active:
        return None
    # A blocked newest run must shadow older successes for THAT head, but
    # cannot veto a distinct, independently authenticated green PR.
    seen_heads: set[tuple[str, str]] = set()
    blocked_heads: set[tuple[str, str]] = set()
    for page in range(1, 4):
        payload = obj(
            api.get(
                f"/repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/runs"
                f"?event=pull_request&per_page=100&page={page}"
            ),
            "canonical CodeQL run listing",
        )
        runs = payload.get("workflow_runs")
        require(isinstance(runs, list) and len(runs) <= 100, "CodeQL run page malformed")
        for run in runs:
            run = obj(run, "CodeQL workflow run")
            subject = (run.get("head_sha"), run.get("head_branch"))
            if subject not in active or subject in seen_heads:
                continue
            # Runs are newest-first across all pages. Mark the head before
            # admission so an earlier green attempt never masks its bad latest.
            seen_heads.add(subject)
            require(
                run.get("workflow_id") == WORKFLOW_ID and run.get("event") == "pull_request",
                "canonical CodeQL producer workflow identity drift",
            )
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                blocked_heads.add(subject)
                print(
                    "BLOCKED: live PR's newest CodeQL run is not completed-success; "
                    "older runs for that head are ineligible",
                    file=sys.stderr,
                )
                continue
            result = verify(
                api,
                {"action": "completed", "workflow_run": run},
                trusted_main_sha=trusted_main_sha,
            )
            head = result["head_sha"]
            # A successful native check can represent an unrelated tool or
            # a different CodeQL configuration. Only the *actual*, exact-head
            # analysis for the trusted active CodeQL category permits a skip.
            number = result["pr_number"]
            ref = f"refs/pull/{number}/head"
            encoded_ref = urllib.parse.quote(ref, safe="")
            analyses = api.get(
                f"/repos/{REPOSITORY}/code-scanning/analyses?ref={encoded_ref}&per_page=100"
            )
            require(
                isinstance(analyses, list) and len(analyses) < 100,
                "bounded exact-ref Code Scanning analysis inventory missing",
            )
            matching = [
                a
                for a in analyses
                if isinstance(a, dict)
                and a.get("ref") == ref
                and a.get("commit_sha") == head
                and nested(a, "tool", "name") == "CodeQL"
                and a.get("analysis_key") == CODEQL_CATEGORY
                and a.get("category") == CODEQL_CATEGORY
            ]
            require(len(matching) <= 1, "ambiguous active CodeQL analyses on exact PR head")
            if matching:
                require(
                    matching[0].get("error") == "" and matching[0].get("warning") == "",
                    "published active CodeQL analysis contains failure/warning",
                )
                # A completed upload alone does not prove GitHub's *native*
                # Code Scanning check is successful. A stale second CodeQL
                # configuration can turn that check neutral/blocked despite
                # this one category being present. Never treat neutral as PASS
                # or spam an already uploaded result into the same category.
                head_checks = obj(
                    api.get(f"/repos/{REPOSITORY}/commits/{head}/check-runs?per_page=100"),
                    "native head Code Scanning check-runs",
                )
                checks = head_checks.get("check_runs")
                count = head_checks.get("total_count")
                require(
                    type(count) is int
                    and 0 <= count <= 100
                    and isinstance(checks, list)
                    and len(checks) == count,
                    "incomplete native Code Scanning check-run inventory",
                )
                native = [
                    check
                    for check in checks
                    if isinstance(check, dict)
                    and check.get("name") == "CodeQL"
                    and check.get("head_sha") == head
                    and nested(check, "app", "slug")
                    in {"github-advanced-security", "github-code-scanning"}
                ]
                require(
                    len(native) == 1
                    and native[0].get("status") == "completed"
                    and native[0].get("conclusion") == "success",
                    "CodeQL analysis exists but native PR check is absent, neutral or failed",
                )
                continue
            return result
        if len(runs) < 100:
            if blocked_heads:
                raise Blocked(
                    f"{len(blocked_heads)} live PR head(s) have no completed-success newest "
                    "CodeQL run; no ineligible evidence was published"
                )
            return None
    raise Blocked("CodeQL workflow run inventory exceeds bounded 300-run lookback")


def verify_sarif(directory: Path) -> None:
    require(directory.is_dir() and not directory.is_symlink(), "SARIF directory missing")
    files = list(directory.rglob("*"))
    require(files and len(files) <= 16, "SARIF archive file budget violated")
    actual = [p for p in files if p.is_file()]
    require(
        len(actual) == len(files) == 2,
        "SARIF archive must include exactly two regular CodeQL language reports",
    )
    require(
        {p.relative_to(directory).as_posix() for p in actual} == {"actions.sarif", "python.sarif"},
        "CodeQL Actions or Python source analysis is missing/renamed",
    )
    for f in actual:
        require(not f.is_symlink() and f.suffix == ".sarif", "SARIF entry type invalid")
        require(100 <= f.stat().st_size <= 12_000_000, "SARIF byte limit violated")
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Blocked("SARIF is not valid UTF-8 JSON") from exc
        require(
            isinstance(doc, dict) and doc.get("version") == "2.1.0", "SARIF schema version mismatch"
        )
        runs = doc.get("runs")
        require(
            isinstance(runs, list) and bool(runs) and len(runs) <= 8,
            "SARIF contains no bounded CodeQL run",
        )
        for run in runs:
            driver = nested(run, "tool", "driver")
            require(
                isinstance(driver, dict) and driver.get("name") == "CodeQL",
                "non-CodeQL SARIF cannot be published",
            )
            analysis = obj(run, "SARIF run")
            metadata = analysis.get("automationDetails")
            # GitHub's upload-sarif 'category' input cannot override SARIF's
            # own automationDetails.id. Reject an unexpected category rather
            # than silently creating another untracked analysis identity.
            require(
                metadata is None
                or (isinstance(metadata, dict) and metadata.get("id") == f"{CODEQL_CATEGORY}/"),
                "CodeQL original SARIF carries a conflicting analysis category",
            )
            results = analysis.get("results", [])
            require(
                isinstance(results, list) and len(results) == 0,
                "nonzero/malformed CodeQL findings are never published as green",
            )


def self_test() -> None:
    head = "a" * 40
    main = "b" * 40
    merge = "c" * 40
    tree = "d" * 40
    run_id = 101
    branch = "security/sast-real-identity"
    prnum = 6
    blob = "e" * 40
    event_run = dict(
        id=run_id,
        workflow_id=WORKFLOW_ID,
        path=WORKFLOW_PATH,
        name="CodeQL",
        event="pull_request",
        status="completed",
        conclusion="success",
        run_attempt=1,
        head_sha=head,
        head_branch=branch,
        head_repository={"full_name": REPOSITORY},
    )
    run = dict(event_run, repository={"full_name": REPOSITORY})
    pr = {
        "number": prnum,
        "state": "open",
        "draft": False,
        "head": {"sha": head, "ref": branch, "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "main", "sha": main, "repo": {"full_name": REPOSITORY}},
    }
    step_names = CHECK_NAMES
    lookup = {
        f"/repos/{REPOSITORY}/actions/runs/{run_id}": run,
        f"/repos/{REPOSITORY}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"sha": main},
        },
        f"/repos/{REPOSITORY}/pulls?state=open&base=main&per_page=100&page=1": [pr],
        f"/repos/{REPOSITORY}/pulls/{prnum}": pr,
        f"/repos/{REPOSITORY}/git/ref/heads/{branch}": {"object": {"sha": head}},
        f"/repos/{REPOSITORY}/git/ref/pull/{prnum}/merge": {
            "ref": f"refs/pull/{prnum}/merge",
            "object": {"sha": merge},
        },
        f"/repos/{REPOSITORY}/commits/{head}": {"commit": {"tree": {"sha": tree}}},
        f"/repos/{REPOSITORY}/commits/{merge}": {"commit": {"tree": {"sha": tree}}},
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100": {
            "total_count": 1,
            "jobs": [
                {
                    "name": "CodeQL",
                    "head_sha": head,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [{"name": name, "conclusion": "success"} for name in step_names],
                }
            ],
        },
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100": {
            "total_count": 1,
            "artifacts": [
                {
                    "name": f"codeql-sarif-{run_id}",
                    "id": 202,
                    "expired": False,
                    "size_in_bytes": 1000,
                    "digest": "sha256:" + "f" * 64,
                    "workflow_run": {"id": run_id, "head_sha": head},
                }
            ],
        },
    }
    for path in SAFE_PRODUCER_FILES:
        enc = urllib.parse.quote(path, safe="/")
        lookup[f"/repos/{REPOSITORY}/contents/{enc}?ref={main}"] = {"sha": blob}
        lookup[f"/repos/{REPOSITORY}/contents/{enc}?ref={head}"] = {"sha": blob}

    class Fake:
        def __init__(self, routes: dict[str, Any]):
            self.routes = routes

        def get(self, path: str) -> Any:
            require(path in self.routes, "unexpected test API request")
            return self.routes[path]

    event = {"action": "completed", "workflow_run": event_run}
    require(verify(Fake(lookup), event)["head_sha"] == head, "valid exact-head evidence rejected")

    def blocked(routes: dict[str, Any], e: Any, label: str) -> None:
        try:
            verify(Fake(routes), e)
        except Blocked:
            return
        raise AssertionError(f"tampering fixture passed: {label}")

    from copy import deepcopy

    for label, mutate in (
        (
            "fork",
            lambda d: d[f"/repos/{REPOSITORY}/actions/runs/{run_id}"]["head_repository"].update(
                full_name="attacker/fork"
            ),
        ),
        (
            "stale main",
            lambda d: d[f"/repos/{REPOSITORY}/pulls/{prnum}"]["base"].update(sha="9" * 40),
        ),
        (
            "different merge tree",
            lambda d: d[f"/repos/{REPOSITORY}/commits/{merge}"]["commit"]["tree"].update(
                sha="8" * 40
            ),
        ),
        (
            "failed scan",
            lambda d: d[f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"][0][
                "steps"
            ][2].update(conclusion="failure"),
        ),
        (
            "modified producer",
            lambda d: d[
                f"/repos/{REPOSITORY}/contents/"
                f"{urllib.parse.quote(WORKFLOW_PATH, safe='/')}?ref={head}"
            ].update(sha="0" * 40),
        ),
        (
            "unbound artifact",
            lambda d: d[f"/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"][
                "artifacts"
            ][0]["workflow_run"].update(head_sha="9" * 40),
        ),
    ):
        mutated = deepcopy(lookup)
        mutate(mutated)
        blocked(mutated, event, label)
    discover_lookup = deepcopy(lookup)
    discover_lookup[
        f"/repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/runs?event=pull_request&per_page=100&page=1"
    ] = {
        "workflow_runs": [run],
    }
    analysis_path = (
        f"/repos/{REPOSITORY}/code-scanning/analyses"
        f"?ref={urllib.parse.quote(f'refs/pull/{prnum}/head', safe='')}&per_page=100"
    )
    discover_lookup[analysis_path] = []
    require(
        discover(Fake(discover_lookup), trusted_main_sha=main)["head_sha"] == head,
        "trusted scheduler discovery rejected valid PR run",
    )
    try:
        discover(Fake(discover_lookup), trusted_main_sha="0" * 40)
    except Blocked:
        pass
    else:
        raise AssertionError("stale workflow main SHA was trusted during publication")
    newer_main = deepcopy(discover_lookup)
    newer_main[f"/repos/{REPOSITORY}/git/ref/heads/main"]["object"]["sha"] = "9" * 40
    try:
        discover(Fake(newer_main), trusted_main_sha=main)
    except Blocked:
        pass
    else:
        raise AssertionError("newer accepted main did not block old trusted consumer")
    # A bad or still-running PR cannot starve a distinct verified PR.
    # No auth data or source files from the blocked peer are ever read.
    peer_blocked = deepcopy(discover_lookup)
    peer_pr = deepcopy(pr)
    peer_pr["number"] = prnum + 1
    peer_pr["head"]["sha"] = "1" * 40
    peer_pr["head"]["ref"] = "security/blocked-peer"
    prs_path = f"/repos/{REPOSITORY}/pulls?state=open&base=main&per_page=100&page=1"
    runs_path = (
        f"/repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/runs"
        "?event=pull_request&per_page=100&page=1"
    )
    peer_blocked[prs_path].append(peer_pr)
    peer_run = deepcopy(run)
    peer_run.update(
        id=102,
        head_sha="1" * 40,
        head_branch="security/blocked-peer",
        conclusion="failure",
    )
    peer_blocked[runs_path]["workflow_runs"] = [peer_run, run]
    require(
        discover(Fake(peer_blocked))["head_sha"] == head,
        "failed unrelated CodeQL scan starved valid exact-head publication",
    )
    peer_pending = deepcopy(peer_blocked)
    peer_pending[runs_path]["workflow_runs"][0].update(status="in_progress", conclusion=None)
    require(
        discover(Fake(peer_pending))["head_sha"] == head,
        "in-progress unrelated CodeQL scan starved valid exact-head publication",
    )
    newest_failed = deepcopy(discover_lookup)
    newer = deepcopy(run)
    newer["id"] = 102
    newer["conclusion"] = "failure"
    newest_failed[
        f"/repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/runs?event=pull_request&per_page=100&page=1"
    ]["workflow_runs"] = [newer, run]
    try:
        discover(Fake(newest_failed))
    except Blocked:
        pass
    else:
        raise AssertionError("older successful CodeQL run concealed latest failed run")
    already = deepcopy(discover_lookup)
    existing = {
        "tool": {"name": "CodeQL"},
        "ref": f"refs/pull/{prnum}/head",
        "commit_sha": head,
        "analysis_key": CODEQL_CATEGORY,
        "category": CODEQL_CATEGORY,
        "error": "",
        "warning": "",
    }
    already[analysis_path] = [existing]
    check_path = f"/repos/{REPOSITORY}/commits/{head}/check-runs?per_page=100"
    already[check_path] = {
        "total_count": 1,
        "check_runs": [
            {
                "name": "CodeQL",
                "head_sha": head,
                "app": {"slug": "github-advanced-security"},
                "status": "completed",
                "conclusion": "success",
            }
        ],
    }
    require(discover(Fake(already)) is None, "already published successful CodeQL head not skipped")
    all_blocked = deepcopy(peer_blocked)
    all_blocked[analysis_path] = [existing]
    all_blocked[check_path] = deepcopy(already[check_path])
    try:
        discover(Fake(all_blocked))
    except Blocked:
        pass
    else:
        raise AssertionError("blocked peer was silently reported as no outstanding work")
    neutral = deepcopy(already)
    neutral[check_path]["check_runs"][0]["conclusion"] = "neutral"
    try:
        discover(Fake(neutral))
    except Blocked:
        pass
    else:
        raise AssertionError("neutral native CodeQL check falsely counted as success")
    omitted = deepcopy(already)
    omitted[check_path]["total_count"] = 0
    omitted[check_path]["check_runs"] = []
    try:
        discover(Fake(omitted))
    except Blocked:
        pass
    else:
        raise AssertionError("missing native CodeQL check falsely counted as success")
    unrelated = deepcopy(already)
    unrelated[analysis_path][0]["analysis_key"] = "(default)"
    unrelated[analysis_path][0]["category"] = ""
    require(
        discover(Fake(unrelated))["head_sha"] == head,
        "unrelated native CodeQL category masked required trusted publication",
    )
    invalid = deepcopy(already)
    invalid[analysis_path][0]["error"] = "integrity failure"
    try:
        discover(Fake(invalid))
    except Blocked:
        pass
    else:
        raise AssertionError("failed published CodeQL analysis concealed as a success")
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sarif_file = root / "actions.sarif"
        python_sarif = root / "python.sarif"
        doc = {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "CodeQL",
                            "semanticVersion": "2.20.0",
                            "informationUri": "https://github.com/github/codeql",
                            "rules": [],
                        }
                    },
                    "results": [],
                }
            ],
        }
        sarif_file.write_text(json.dumps(doc), encoding="utf-8")
        python_sarif.write_text(json.dumps(doc), encoding="utf-8")
        verify_sarif(root)
        python_sarif.unlink()
        try:
            verify_sarif(root)
        except Blocked:
            pass
        else:
            raise AssertionError("partial CodeQL language evidence was accepted")
        python_sarif.write_text(json.dumps(doc), encoding="utf-8")
        doc["runs"][0]["results"].append({"ruleId": "dangerous"})
        sarif_file.write_text(json.dumps(doc), encoding="utf-8")
        try:
            verify_sarif(root)
        except Blocked:
            pass
        else:
            raise AssertionError("alert-containing CodeQL SARIF accepted")
        doc["runs"][0]["results"] = []
        doc["runs"][0]["automationDetails"] = {"id": "attacker/other-scan/"}
        sarif_file.write_text(json.dumps(doc), encoding="utf-8")
        try:
            verify_sarif(root)
        except Blocked:
            pass
        else:
            raise AssertionError("SARIF with conflicting category accepted")
        doc["runs"][0]["automationDetails"] = {"id": f"{CODEQL_CATEGORY}/"}
        sarif_file.write_text(json.dumps(doc), encoding="utf-8")
        verify_sarif(root)
        python_sarif.rename(root / "unverified.sarif")
        try:
            verify_sarif(root)
        except Blocked:
            pass
        else:
            raise AssertionError("forged CodeQL language filename accepted")
    print("Trusted CodeQL PR publication provenance negative fixtures passed")


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--discover", action="store_true")
    mode.add_argument("--verify-sarif", metavar="DIR", type=Path)
    mode.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.verify_sarif is not None:
            verify_sarif(args.verify_sarif)
            print("CodeQL source run and zero-alert SARIF schema verified")
        else:
            require(
                os.environ.get("GITHUB_REF") == "refs/heads/main",
                "privileged publisher invoked outside accepted main",
            )
            value = discover(
                GitHubRead(os.environ["GH_TOKEN"]),
                trusted_main_sha=os.environ["TRUSTED_MAIN_SHA"],
            )
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as f:
                f.write(f"has_target={'true' if value else 'false'}\n")
                if value:
                    for key, val in value.items():
                        f.write(f"{key}={val}\n")
            if value:
                print("Authenticated same-repo CodeQL scan and exact PR head", value["pr_number"])
            else:
                print("No eligible PR-head SAST scan; no report fabricated")
    except (Blocked, ValueError, KeyError, OSError) as exc:
        print(f"BLOCKED: trusted CodeQL PR publication: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
