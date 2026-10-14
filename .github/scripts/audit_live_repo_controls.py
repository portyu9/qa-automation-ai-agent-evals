"""Read-only, fail-closed drift audit of *live* GitHub merge authority.

This monitors only the proven single-maintainer CI-authoritative configuration.
It NEVER asserts that bot reviews meet Scorecard's independent-human criterion,
that source policy authenticates live GitHub settings, or that a green check
proves every vulnerability absent.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = "portyu9/qa-automation-ai-agent-evals"
RULESET_ID = 22191532
GITHUB_ACTIONS_ID = 15368
REQUIRED_CHECKS = frozenset(
    {
        "Quality / Python 3.11",
        "Quality / Python 3.14",
        "OpenAI adapter / deterministic SDK",
        "MCP OAuth flow / separated AS-RS",
        "MCP fault lab / deterministic protocol",
        "MCP remote auth / loopback HTTP",
        "Package integrity",
    }
)


class DriftError(RuntimeError):
    """GitHub merge authority is missing or has drifted."""


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DriftError(f"{context}: expected JSON object")
    return value


def inspect(repo: Any, ruleset: Any) -> dict[str, Any]:
    repo = require_object(repo, "repository")
    ruleset = require_object(ruleset, "ruleset")
    expected_repo = {
        "full_name": REPO,
        "default_branch": "main",
        "allow_auto_merge": True,
        "allow_update_branch": True,
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_rebase_merge": False,
    }
    unavailable_admin_fields: list[str] = []
    for key, expected in expected_repo.items():
        # Ordinary GITHUB_TOKEN API responses can omit administration-only flags.
        # Missing is BLOCKED (not PASS, not a contradictory live setting).
        if key.startswith("allow_") and repo.get(key) is None:
            unavailable_admin_fields.append(key)
            continue
        if repo.get(key) != expected:
            raise DriftError(f"repository {key}: expected {expected!r}, got {repo.get(key)!r}")
    if ruleset.get("id") != RULESET_ID or ruleset.get("enforcement") != "active":
        raise DriftError("Protect Main ruleset must be active and exact-ID")
    # The read-only Actions token may omit administrator-only bypass actors.
    # Omission cannot be treated as an observed empty list or a real bypass.
    bypass = ruleset.get("bypass_actors")
    bypass_unobservable = bypass is None
    if not bypass_unobservable and bypass != []:
        raise DriftError("main ruleset must not grant bypass actors")
    conditions = require_object(ruleset.get("conditions"), "ruleset conditions")
    refs = require_object(conditions.get("ref_name"), "ruleset refs")
    if refs.get("include") != ["~DEFAULT_BRANCH"] or refs.get("exclude") != []:
        raise DriftError("Protect Main must bind exactly the default branch")
    rules = ruleset.get("rules")
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise DriftError("Protect Main rules must be a list of objects")
    indexed: dict[str, dict[str, Any]] = {}
    for rule in rules:
        name = rule.get("type")
        if not isinstance(name, str) or name in indexed:
            raise DriftError("duplicate or malformed repository rule type")
        indexed[name] = rule
    mandatory = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}
    if not mandatory.issubset(indexed):
        raise DriftError(f"missing protections {sorted(mandatory - indexed.keys())}")
    pr = require_object(indexed["pull_request"].get("parameters"), "PR protections")
    if pr.get("allowed_merge_methods") != ["merge"]:
        raise DriftError("Protect Main must permit merge commits only")
    if pr.get("required_review_thread_resolution") is not True:
        raise DriftError("protected PR threads must remain resolved")
    review_count = pr.get("required_approving_review_count")
    if not isinstance(review_count, int) or isinstance(review_count, bool) or review_count < 0:
        raise DriftError("invalid approving-review requirement")
    status = require_object(indexed["required_status_checks"].get("parameters"), "status rules")
    if status.get("strict_required_status_checks_policy") is not True:
        raise DriftError("up-to-date protected check qualification must be strict")
    rows = status.get("required_status_checks")
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise DriftError("protected contexts must be structured GitHub check objects")
    found: dict[str, int] = {}
    for row in rows:
        name, integration = row.get("context"), row.get("integration_id")
        if not isinstance(name, str) or not name or name in found:
            raise DriftError("duplicate or malformed protected status context")
        if not isinstance(integration, int) or isinstance(integration, bool):
            raise DriftError(f"invalid integration binding for {name!r}")
        found[name] = integration
    if not REQUIRED_CHECKS.issubset(found):
        raise DriftError(
            f"required check contexts missing {sorted(REQUIRED_CHECKS - found.keys())}"
        )
    for name in REQUIRED_CHECKS:
        if found[name] != GITHUB_ACTIONS_ID:
            raise DriftError(f"protected check {name!r} lost its Actions integration binding")
    return {
        "merge_controls": (
            "BLOCKED: GitHub Actions token cannot independently read "
            + ", ".join(unavailable_admin_fields)
            if unavailable_admin_fields
            else "PASS"
        ),
        "ruleset_controls": (
            "BLOCKED: GitHub Actions token cannot independently read bypass_actors"
            if bypass_unobservable
            else "PASS"
        ),
        "verified_rule_checks": "PASS",
        "repo": REPO,
        "ruleset_id": RULESET_ID,
        "protected_checks": len(found),
        "human_review_scorecard": (
            "BLOCKED: no independent approving reviewer required"
            if review_count == 0
            else "UNVERIFIED: number of approvers does not prove independent humans"
        ),
        "codeql_and_security": (
            "indirectly required by Package integrity; direct status enforcement not claimed"
        ),
        "private_vulnerability_reporting": "UNVERIFIED: separate admin-only feature",
    }


def fetch_json(path: str, token: str) -> dict[str, Any]:
    if not token:
        raise DriftError("GITHUB_TOKEN is required for authenticated live settings audit")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-evals-readonly-governance-monitor",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise DriftError(f"GitHub API denied authenticated audit: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
        raise DriftError(f"GitHub API audit unavailable: {type(exc).__name__}") from exc
    return require_object(data, path)


def self_test() -> None:
    repo = {
        "full_name": REPO,
        "default_branch": "main",
        "allow_auto_merge": True,
        "allow_update_branch": True,
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_rebase_merge": False,
    }
    ruleset = {
        "id": RULESET_ID,
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["merge"],
                    "required_review_thread_resolution": True,
                    "required_approving_review_count": 0,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": c, "integration_id": GITHUB_ACTIONS_ID}
                        for c in sorted(REQUIRED_CHECKS)
                    ],
                },
            },
        ],
    }
    if inspect(repo, ruleset)["human_review_scorecard"].startswith("PASS"):
        raise DriftError("fixture misclassified missing human review as PASS")
    if inspect(repo, ruleset)["merge_controls"] != "PASS":
        raise DriftError("fully readable compliant GitHub merge settings did not PASS")
    if inspect(repo, ruleset)["ruleset_controls"] != "PASS":
        raise DriftError("fully observed no-bypass ruleset incorrectly classified")
    for sentinel in (None, "omit"):
        partial_rules = json.loads(json.dumps(ruleset))
        if sentinel is None:
            partial_rules["bypass_actors"] = None
        else:
            partial_rules.pop("bypass_actors")
        report = inspect(repo, partial_rules)
        if not report["ruleset_controls"].startswith("BLOCKED:"):
            raise DriftError("unobservable bypass actors were falsely accepted as PASS")
        if report["verified_rule_checks"] != "PASS":
            raise DriftError("admin-only field masked other verified rule checks")
        partial_repo = dict(repo)
        partial_repo.pop("allow_auto_merge")
        mixed = inspect(partial_repo, partial_rules)
        if not mixed["merge_controls"].startswith("BLOCKED:"):
            raise DriftError("independent missing settings were falsely accepted")
        if not mixed["ruleset_controls"].startswith("BLOCKED:"):
            raise DriftError("independent missing bypass field was falsely accepted")
        partial_rules["bypass_actors"] = [{"actor_id": 1}]
        try:
            inspect(repo, partial_rules)
        except DriftError:
            pass
        else:
            raise DriftError("explicit bypass actor slipped past blocked-field handling")
    for missing in (
        "allow_auto_merge",
        "allow_update_branch",
        "allow_merge_commit",
        "allow_squash_merge",
        "allow_rebase_merge",
    ):
        for sentinel in (None, "omit"):
            partial = dict(repo)
            if sentinel is None:
                partial[missing] = None
            else:
                partial.pop(missing)
            result = inspect(partial, ruleset)
            if not result["merge_controls"].startswith("BLOCKED:"):
                raise DriftError("unobservable admin-only field was falsely reported as PASS")
            if result["ruleset_controls"] != "PASS":
                raise DriftError("unobservable repository field erased verified ruleset evidence")
    cases = [
        (dict(repo, allow_squash_merge=True), ruleset),
        (dict(repo, allow_auto_merge=False), ruleset),
        (dict(repo, allow_update_branch=False), ruleset),
        (dict(repo, allow_rebase_merge=True), ruleset),
        (dict(repo, default_branch="develop"), ruleset),
        (repo, dict(ruleset, bypass_actors=[{"actor_id": 1}])),
        (repo, dict(ruleset, enforcement="disabled")),
        (repo, dict(ruleset, conditions={})),
        (repo, dict(ruleset, rules=ruleset["rules"][:2])),
    ]
    for i, (bad_repo, bad_ruleset) in enumerate(cases):
        try:
            inspect(bad_repo, bad_ruleset)
        except DriftError:
            continue
        raise DriftError(f"negative fixture {i} was incorrectly accepted")
    for mutate in (
        lambda r: r["rules"][2]["parameters"].update({"allowed_merge_methods": ["squash"]}),
        lambda r: r["rules"][2]["parameters"].update({"required_review_thread_resolution": False}),
        lambda r: r["rules"][3]["parameters"].update(
            {"strict_required_status_checks_policy": False}
        ),
        lambda r: r["rules"][3]["parameters"]["required_status_checks"].pop(),
        lambda r: r["rules"][3]["parameters"]["required_status_checks"][0].update(
            {"integration_id": 100}
        ),
    ):
        bad = json.loads(json.dumps(ruleset))
        mutate(bad)
        try:
            inspect(repo, bad)
        except DriftError:
            continue
        raise DriftError("mutated protected check or merge rule accepted")
    print("Read-only live governance contract self-tests passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test == args.live:
        parser.error("specify exactly one of --self-test or --live")
    try:
        if args.self_test:
            self_test()
        else:
            if os.getenv("GITHUB_REPOSITORY") != REPO:
                raise DriftError("live audit attempted for unexpected repository")
            if os.getenv("GITHUB_REF") != "refs/heads/main":
                raise DriftError("live audit must execute on main, never untrusted PR code")
            token = os.getenv("GITHUB_TOKEN", "")
            outcome = inspect(fetch_json("", token), fetch_json(f"/rulesets/{RULESET_ID}", token))
            report = json.dumps(outcome, sort_keys=True)
            print(report)
            if outcome["merge_controls"].startswith("BLOCKED"):
                print(
                    "::warning::Live repository admin settings are BLOCKED from "
                    "this read-only token; do not interpret the audit job as "
                    "a PASS for unverified administrator controls."
                )
            if outcome["ruleset_controls"].startswith("BLOCKED"):
                print(
                    "::warning::Ruleset bypass-actor administration is BLOCKED "
                    "from this read-only token; verified protected checks "
                    "do not establish the absent no-bypass assertion."
                )
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report + "\n", encoding="utf-8")
    except DriftError as exc:
        print(f"live repository governance audit FAILED: {exc}")
        if args.live and args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"merge_controls": "FAIL", "error": str(exc)}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
