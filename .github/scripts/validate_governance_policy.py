"""Validate repository-owned governance intent without claiming live GitHub enforcement."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "repository-governance.json"
CODEOWNERS_PATH = ROOT / ".github" / "CODEOWNERS"
GOVERNANCE_DOC = ROOT / "docs" / "REPOSITORY_GOVERNANCE.md"


def fail(message: str) -> None:
    raise SystemExit(f"governance policy contract failed: {message}")


def object_field(value: dict[str, object], key: str) -> dict[str, object]:
    field = value.get(key)
    if not isinstance(field, dict):
        fail(f"{key} must be an object")
    return field


def string_list(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        fail(f"{label} must be a non-empty string list")
    return value


def load_policy() -> dict[str, object]:
    try:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot load repository governance policy: {type(exc).__name__}")
    if not isinstance(raw, dict):
        fail("repository governance policy root must be an object")
    return raw


def load_codeowners() -> dict[str, tuple[str, ...]]:
    entries: dict[str, tuple[str, ...]] = {}
    try:
        lines = CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot load CODEOWNERS: {type(exc).__name__}")
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            fail(f"malformed CODEOWNERS entry: {raw_line!r}")
        path, *owners = fields
        entries[path] = tuple(owners)
    return entries


def main() -> int:
    policy = load_policy()
    if policy.get("schema_version") != "agent-evals/repository-governance/v2":
        fail("unsupported schema_version")
    if policy.get("default_branch") != "main":
        fail("default_branch must remain main")

    review = object_field(policy, "review_policy")
    if review.get("pull_request_required") is not True:
        fail("pull requests must remain required")
    if review.get("required_approvals") != 0:
        fail("autonomous single-CODEOWNER policy must not require approving reviews")
    if review.get("require_code_owner_review") is not False:
        fail("sole CODEOWNER must not be a mandatory merge approver")
    for key in ("dismiss_stale_reviews_on_push", "require_last_push_approval"):
        if review.get(key) is not False:
            fail(f"{key} must remain disabled when approvals are not merge authority")
    if review.get("require_review_thread_resolution") is not True:
        fail("review threads must remain resolved before merge")
    if review.get("allowed_merge_methods") != ["merge"]:
        fail("protected history policy must remain merge-only")

    maintainers = object_field(policy, "maintainer_policy")
    if maintainers.get("minimum_human_codeowners") != 1:
        fail("single-codeowner policy must require exactly one human CODEOWNER minimum")
    current_human_codeowners = string_list(
        maintainers.get("current_human_codeowners"),
        label="current_human_codeowners",
    )
    if current_human_codeowners != ["@portyu9"]:
        fail("current single human CODEOWNER must remain @portyu9")
    if maintainers.get("ownership_model") != "single-codeowner-ci-authoritative":
        fail("ownership model must remain CI-authoritative with one CODEOWNER")
    if maintainers.get("codeowner_role") != "routing-and-trust-ownership-not-merge-approval":
        fail("CODEOWNER role must not silently become merge approval authority")

    automation = object_field(policy, "automation_policy")
    if automation.get("required_status_checks_are_merge_authority") is not True:
        fail("required status checks must remain merge authority")
    if automation.get("github_actions_approval_required") is not False:
        fail("GitHub Actions approval must not be required")
    if automation.get("copilot_approval_required") is not False:
        fail("Copilot approval must not be required")

    signed = object_field(policy, "signed_history_policy")
    if signed.get("decision") != "do-not-require-signed-commits-for-autonomous-automation":
        fail("signed-history decision must preserve autonomous automation")
    if signed.get("required") is not False:
        fail("signed commits must not be required by repository governance")
    if not isinstance(signed.get("reason"), str) or not signed["reason"]:
        fail("signed-history tradeoff must retain an explicit reason")

    settings = object_field(policy, "repository_settings_policy")
    expected_setting = "eligible-after-live-ruleset-matches-ci-authoritative-policy"
    for key in ("auto_merge", "update_branch"):
        if settings.get(key) != expected_setting:
            fail(f"{key} policy must remain gated on authoritative live rules")

    prerequisites = object_field(policy, "external_admin_prerequisites")
    for feature in ("dependency_graph", "secret_scanning", "push_protection"):
        entry = prerequisites.get(feature)
        if not isinstance(entry, dict) or entry.get("required") is not True:
            fail(f"{feature} must remain a required external admin prerequisite")
        if entry.get("verification") != "verified-enabled":
            fail(f"{feature} must remain recorded as verified-enabled")

    live = object_field(policy, "live_enforcement")
    if live.get("source") != "github-ruleset" or live.get("ruleset_name") != "Protect Main":
        fail("live enforcement source must remain the Protect Main GitHub ruleset")
    if live.get("verification") != "external-admin-surface":
        fail("live ruleset enforcement must remain externally verified")
    if live.get("repository_owned_policy_is_not_live_attestation") is not True:
        fail("repository-owned policy must not be represented as live attestation")

    codeowners = load_codeowners()
    if codeowners.get("*") != tuple(current_human_codeowners):
        fail("default CODEOWNER entry must match current_human_codeowners")

    boundaries = policy.get("trust_boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        fail("trust_boundaries must be a non-empty list")
    seen_paths: set[str] = set()
    for item in boundaries:
        if not isinstance(item, dict):
            fail("trust boundary entries must be objects")
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            fail("trust boundary paths must be absolute repository patterns")
        if path in seen_paths:
            fail(f"duplicate trust boundary path: {path}")
        seen_paths.add(path)
        owners = string_list(item.get("owners"), label=f"owners for {path}")
        if owners != current_human_codeowners:
            fail(f"trust boundary {path} must use the declared single human CODEOWNER")
        if codeowners.get(path) != tuple(owners):
            fail(
                f"CODEOWNERS mismatch for {path}: "
                f"found={codeowners.get(path)!r}, expected={tuple(owners)!r}"
            )

    try:
        governance_doc = GOVERNANCE_DOC.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"cannot load repository governance documentation: {type(exc).__name__}")
    for required in (
        "Repository-owned intent is not live enforcement",
        "Single-CODEOWNER CI-authoritative model",
        "Signed-commit tradeoff",
        "Auto-merge and update-branch",
        "External administration prerequisites",
    ):
        if required not in governance_doc:
            fail(f"repository governance documentation is missing: {required!r}")

    print(
        "Repository governance contract: one CODEOWNER, zero required approvals, "
        "CI-authoritative merge policy, and autonomous unsigned working commits are bound; "
        "live GitHub administration remains separately verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
