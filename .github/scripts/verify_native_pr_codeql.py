"""Require authentic native CodeQL evidence on the *live* PR head before protected merge.

This reader runs in the existing required, unprivileged CI Package integrity job.
It never publishes SARIF or upgrades the PR token. A trusted main-only workflow
separately authenticates original zero-alert PR scan evidence before publication.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACTIVE_CATEGORY = ".github/workflows/codeql.yml:codeql-upload"
ACTIVE_ANALYSIS_KEY = ".github/workflows/codeql-pr-publisher.yml:publish"
NATIVE_APPS = frozenset({"github-advanced-security", "github-code-scanning"})


class Blocked(RuntimeError):
    """Missing, stale, contradictory or ineligible security evidence."""


class Pending(Blocked):
    """No completed trusted-main publication yet; bounded retry is allowed."""


def require(condition: bool, why: str) -> None:
    if not condition:
        raise Blocked(why)


def mapping(value: Any, why: str) -> dict[str, Any]:
    require(isinstance(value, dict), why)
    return value


class GitHubRead:
    """Read-only authenticated GitHub API adapter, never executing PR code."""

    def __init__(self, repository: str, token: str):
        require(bool(REPO.fullmatch(repository)), "invalid canonical repository")
        require(bool(token), "GitHub read token missing")
        self.repository = repository
        self.token = token

    def get(self, path: str) -> Any:
        require(path.startswith(f"/repos/{self.repository}/"), "non-canonical API path")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "native-codeql-required-premerge-gate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                require(response.status == 200, "unexpected GitHub API status")
                raw = response.read(8_000_001)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise Blocked(f"native CodeQL evidence API unavailable: {type(exc).__name__}") from exc
        require(len(raw) <= 8_000_000, "GitHub response oversized")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise Blocked("malformed GitHub evidence response") from exc


def validate_snapshot(
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    pr: Any,
    main_ref: Any,
    native_checks: Any,
    analyses: Any,
) -> None:
    """Fail closed on wrong PR, stale head/base, synthetic actions checks or alertful SARIF."""
    require(bool(REPO.fullmatch(repository)), "invalid repository")
    require(type(pr_number) is int and pr_number > 0, "invalid PR number")
    require(isinstance(head_sha, str) and SHA.fullmatch(head_sha) is not None, "invalid head SHA")
    pr = mapping(pr, "PR metadata missing")
    require(pr.get("number") == pr_number and pr.get("state") == "open", "PR is closed or wrong")
    require(pr.get("draft") is False, "draft PR is not eligible")
    head = mapping(pr.get("head"), "PR head absent")
    base = mapping(pr.get("base"), "PR base absent")
    require(head.get("sha") == head_sha, "PR source head moved or disagrees with CI")
    require(
        mapping(head.get("repo"), "PR head repository missing").get("full_name") == repository,
        "external fork native publication not qualified; BLOCKED",
    )
    require(
        base.get("ref") == "main"
        and mapping(base.get("repo"), "PR base repository missing").get("full_name") == repository,
        "PR target is not protected main",
    )
    main_ref = mapping(main_ref, "current main ref unavailable")
    require(main_ref.get("ref") == "refs/heads/main", "main ref mismatch")
    main_sha = mapping(main_ref.get("object"), "main ref object missing").get("sha")
    require(isinstance(main_sha, str) and SHA.fullmatch(main_sha) is not None, "invalid main SHA")
    require(base.get("sha") == main_sha, "PR base moved; rebuild CI against latest main")

    checks = mapping(native_checks, "native app check inventory absent")
    rows = checks.get("check_runs")
    count = checks.get("total_count")
    require(
        type(count) is int and 0 <= count <= 100 and isinstance(rows, list) and len(rows) == count,
        "incomplete native check-run inventory",
    )
    native = []
    for row in rows:
        check = mapping(row, "malformed native check")
        app = mapping(check.get("app"), "check app identity missing")
        if app.get("slug") in NATIVE_APPS and check.get("name") == "CodeQL":
            native.append(check)
    require(len(native) <= 1, "ambiguous native CodeQL checks on exact head")
    if native:
        check = native[0]
        require(check.get("head_sha") == head_sha, "native CodeQL checked a different SHA")
        status, conclusion = check.get("status"), check.get("conclusion")
        if status in {"queued", "in_progress"} and conclusion is None:
            # Only actual nonterminal, null-conclusion native checks may use
            # the existing bounded Pending retry; never accept them as PASS.
            raise Pending("native CodeQL still running on exact PR head")
        require(status == "completed", "native CodeQL has invalid terminal state")
        # Unlike Scorecard's historical count, NEUTRAL is not a security approval.
        require(conclusion == "success", "native CodeQL is not genuinely SUCCESS")

    require(isinstance(analyses, list) and len(analyses) < 100, "Code Scanning analyses incomplete")
    ref = f"refs/pull/{pr_number}/head"
    matching = []
    for item in analyses:
        analysis = mapping(item, "malformed Code Scanning analysis")
        if (
            analysis.get("ref") == ref
            and analysis.get("commit_sha") == head_sha
            and mapping(analysis.get("tool"), "analysis tool absent").get("name") == "CodeQL"
            and analysis.get("analysis_key") == ACTIVE_ANALYSIS_KEY
            and analysis.get("category") == ACTIVE_CATEGORY
        ):
            matching.append(analysis)
    require(len(matching) <= 1, "multiple active CodeQL analyses on same PR head")
    if not native and not matching:
        raise Pending("no genuine native PR-head CodeQL evidence yet")
    require(
        len(native) == 1 and len(matching) == 1,
        "native check/analysis mismatch: "
        + json.dumps(
            {
                "native_count": len(native),
                "matching_count": len(matching),
                "pr_analysis_count": len(analyses),
                "pr_analysis_identity": _safe_analysis_metadata(analyses, head_sha=head_sha),
            },
            sort_keys=True,
        ),
    )
    analysis = matching[0]
    require(
        analysis.get("error") == "" and analysis.get("warning") == "",
        "Code Scanning analysis contains error or warning",
    )


def _safe_analysis_metadata(rows: Any, *, head_sha: str) -> list[dict[str, str]]:
    """Only public, bounded non-secret provider identifiers for fail-closed diagnostics."""
    if not isinstance(rows, list):
        return []
    result: list[dict[str, str]] = []
    for entry in rows[:100]:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        category = entry.get("category")
        if entry.get("commit_sha") != head_sha and not (
            isinstance(category, str) and ACTIVE_CATEGORY in category
        ):
            continue
        result.append(
            {
                key: str(entry.get(key, ""))[:180]
                for key in ("ref", "commit_sha", "analysis_key", "category", "error", "warning")
            }
        )
        result[-1]["tool"] = str(tool.get("name", ""))[:100] if isinstance(tool, dict) else ""
        if len(result) == 8:
            break
    return result


def verify_live(api: Any, *, repository: str, pr_number: int, head_sha: str) -> None:
    require(bool(REPO.fullmatch(repository)), "invalid repository")
    require(type(pr_number) is int and pr_number > 0, "invalid PR")
    require(bool(SHA.fullmatch(head_sha)), "invalid source SHA")
    root = f"/repos/{repository}"
    number = pr_number
    # Re-read PR/current main *after* the two native evidence queries as well,
    # so a concurrent head/base update cannot silently qualify an obsolete scan.
    native = api.get(f"{root}/commits/{head_sha}/check-runs?per_page=100")
    # GitHub lists PR analyses using the documented pr filter, not the upload head ref.
    analyses = api.get(f"{root}/code-scanning/analyses?pr={number}&per_page=100")
    if analyses == []:
        # Diagnostics are never evidence or authorization. The API may omit
        # head-ref uploads when filtered by PR; inspect most recent exact SHA.
        try:
            recent = api.get(f"{root}/code-scanning/analyses?per_page=100")
        except Blocked:
            recent = []
        print(
            "NATIVE_CODEQL_PR_ANALYSIS_DIAGNOSTIC "
            + json.dumps(
                {
                    "pr_rows": 0,
                    "recent_exact_subject": _safe_analysis_metadata(recent, head_sha=head_sha),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
    main_ref = api.get(f"{root}/git/ref/heads/main")
    pr = api.get(f"{root}/pulls/{number}")
    validate_snapshot(
        repository=repository,
        pr_number=number,
        head_sha=head_sha,
        pr=pr,
        main_ref=main_ref,
        native_checks=native,
        analyses=analyses,
    )


def self_test() -> None:
    repo, sha, base = "owner/repo", "a" * 40, "b" * 40
    pr = {
        "number": 17,
        "state": "open",
        "draft": False,
        "head": {"sha": sha, "repo": {"full_name": repo}},
        "base": {"ref": "main", "sha": base, "repo": {"full_name": repo}},
    }
    main = {"ref": "refs/heads/main", "object": {"sha": base}}
    valid = {
        "name": "CodeQL",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
        "app": {"slug": "github-advanced-security"},
    }
    checks = {"total_count": 1, "check_runs": [valid]}
    analysis = {
        "ref": "refs/pull/17/head",
        "commit_sha": sha,
        "tool": {"name": "CodeQL"},
        "analysis_key": ACTIVE_ANALYSIS_KEY,
        "category": ACTIVE_CATEGORY,
        "error": "",
        "warning": "",
    }
    params: dict[str, Any] = dict(
        repository=repo,
        pr_number=17,
        head_sha=sha,
        pr=pr,
        main_ref=main,
        native_checks=checks,
        analyses=[analysis],
    )
    validate_snapshot(**params)

    def rejected(**changes: Any) -> None:
        altered = {**params, **changes}
        try:
            validate_snapshot(**altered)
        except Blocked:
            return
        raise AssertionError("unsafe native PR-head CodeQL evidence was accepted")

    rejected(head_sha="c" * 40)
    rejected(pr={**pr, "state": "closed"})
    rejected(pr={**pr, "draft": True})
    rejected(pr={**pr, "head": {**pr["head"], "sha": "c" * 40}})
    rejected(pr={**pr, "head": {**pr["head"], "repo": {"full_name": "outside/fork"}}})
    rejected(pr={**pr, "base": {**pr["base"], "sha": "c" * 40}})
    rejected(pr={**pr, "base": {**pr["base"], "ref": "develop"}})
    rejected(main_ref={"ref": "refs/heads/main", "object": {"sha": "c" * 40}})
    rejected(native_checks={"total_count": 0, "check_runs": []}, analyses=[])
    rejected(native_checks={"total_count": 1, "check_runs": [dict(valid, conclusion="neutral")]})
    rejected(native_checks={"total_count": 1, "check_runs": [dict(valid, status="queued")]})

    # Real in-progress native checks must consume the bounded retry lease,
    # never qualify an unfinished scan or ignore its eventual failure.
    for state in ("queued", "in_progress"):
        for waiting in (dict(valid, status=state, conclusion=None),):
            try:
                validate_snapshot(
                    **{
                        **params,
                        "native_checks": {"total_count": 1, "check_runs": [waiting]},
                    }
                )
            except Pending:
                pass
            else:
                raise AssertionError("unfinished exact-head native CodeQL did not wait")
    for forged in (
        dict(valid, status="in_progress", conclusion="success"),
        dict(valid, status="queued", conclusion="failure"),
        dict(valid, status="unknown", conclusion=None),
    ):
        try:
            validate_snapshot(
                **{
                    **params,
                    "native_checks": {"total_count": 1, "check_runs": [forged]},
                }
            )
        except Pending:
            raise AssertionError("forged native CodeQL terminal state used retry lease")
        except Blocked:
            pass
        else:
            raise AssertionError("forged native CodeQL terminal state passed")
    rejected(native_checks={"total_count": 1, "check_runs": [dict(valid, head_sha="c" * 40)]})
    rejected(native_checks={"total_count": 1, "check_runs": [dict(valid, conclusion="failure")]})
    rejected(
        native_checks={
            "total_count": 1,
            "check_runs": [dict(valid, app={"slug": "github-actions"})],
        }
    )
    rejected(native_checks={"total_count": 2, "check_runs": [valid, valid]})
    rejected(native_checks={"total_count": 2, "check_runs": [valid]})
    rejected(native_checks={"total_count": 101, "check_runs": [valid] * 101})
    rejected(analyses=[])
    rejected(analyses=[dict(analysis, commit_sha="c" * 40)])
    rejected(analyses=[dict(analysis, category="unrelated")])
    rejected(analyses=[dict(analysis, category=f"{ACTIVE_CATEGORY}/")])
    rejected(analyses=[dict(analysis, analysis_key=ACTIVE_CATEGORY)])
    rejected(analyses=[dict(analysis, analysis_key="unrelated")])
    rejected(analyses=[dict(analysis, error="scan error")])
    rejected(analyses=[dict(analysis, warning="ignored result")])
    rejected(analyses=[analysis, analysis])
    rejected(analyses=[analysis] * 100)
    # Correct independent evidence from the other recognized GitHub app is valid.
    validate_snapshot(
        **{
            **params,
            "native_checks": {
                "total_count": 1,
                "check_runs": [{**valid, "app": {"slug": "github-code-scanning"}}],
            },
        }
    )

    class Fake:
        def __init__(self, rows: dict[str, Any]):
            self.rows = rows

        def get(self, path: str) -> Any:
            return self.rows[path]

    prefix = f"/repos/{repo}"
    lookup = {
        f"{prefix}/commits/{sha}/check-runs?per_page=100": checks,
        f"{prefix}/code-scanning/analyses?pr=17&per_page=100": [analysis],
        f"{prefix}/git/ref/heads/main": main,
        f"{prefix}/pulls/17": pr,
    }
    verify_live(Fake(lookup), repository=repo, pr_number=17, head_sha=sha)
    print("native CodeQL PR-head gate: accepted positive and adversarial refusal fixtures")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--subject-sha", default="")
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--attempts", type=int, default=48)
    parser.add_argument("--delay-seconds", type=int, default=5)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request",
        "native premerge qualification is only run on PR events",
    )
    require(1 <= args.attempts <= 60 and 1 <= args.delay_seconds <= 10, "invalid bounded wait")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api = GitHubRead(repository, os.environ.get("GITHUB_TOKEN", ""))
    for attempt in range(args.attempts):
        try:
            verify_live(
                api, repository=repository, pr_number=args.pr_number, head_sha=args.subject_sha
            )
        except Pending as exc:
            if attempt == args.attempts - 1:
                raise Blocked(f"native CodeQL BLOCKED after bounded wait: {exc}") from exc
            time.sleep(args.delay_seconds)
        else:
            print(f"native CodeQL SUCCESS: exact live PR #{args.pr_number} head {args.subject_sha}")
            return 0
    raise Blocked("native CodeQL qualification unavailable")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Blocked as exc:
        print(f"BLOCKED: required native CodeQL qualification: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
