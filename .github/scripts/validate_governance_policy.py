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
    if policy.get("schema_version") != "agent-evals/repository-governance/v1":
        fail("unsupported schema_version")
    if policy.get("default_branch") != "main":
        fail("default_branch must remain main")

    review = object_field(policy, "review_policy")
    if review.get("pull_request_required") is not True:
        fail("pull requests must remain required")
    if review.get("required_approvals") != 1:
        fail("review policy must require exactly one approval at minimum")
    for key in (
        "require_code_owner_review",
        "dismiss_stale_reviews_on_push",
        "require_last_push_approval",
        "require_review_thread_resolution",
    ):
        if review.get(key) is not True:
            fail(f"review policy must require {key}")
    if review.get("allowed_merge_methods") != ["merge"]:
        fail("protected history policy must remain merge-only")

    maintainers = object_field(policy, "maintainer_policy")
    minimum = maintainers.get("minimum_distinct_trust_maintainers")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2:
        fail("independent trust review requires at least two distinct maintainers")
    if maintainers.get("current_independent_review_state") != "blocked-single-maintainer":
        fail("single-maintainer review state must remain explicitly BLOCKED")
    if (
        maintainers.get("codeowner_enforcement_precondition")
        != "at-least-two-distinct-trust-maintainers"
    ):
        fail("CODEOWNER enforcement precondition must remain explicit")

    signed = object_field(policy, "signed_history_policy")
    if signed.get("decision") != "require-signed-commits-on-protected-history":
        fail("signed protected history decision must remain explicit")
    if signed.get("live_enforcement") != "external-admin-required":
        fail("signed-history live enforcement must remain externally verified")

    settings = object_field(policy, "repository_settings_policy")
    expected_setting = "enable-only-after-live-review-controls-are-authoritative"
    for key in ("auto_merge", "update_branch"):
        if settings.get(key) != expected_setting:
            fail(f"{key} policy must remain gated on authoritative live review controls")

    prerequisites = object_field(policy, "external_admin_prerequisites")
    allowed_verification = {
        "blocked-admin-surface",
        "unverified-admin-surface",
        "verified-enabled",
    }
    for feature in ("dependency_graph", "secret_scanning", "push_protection"):
        entry = prerequisites.get(feature)
        if not isinstance(entry, dict) or entry.get("required") is not True:
            fail(f"{feature} must remain a required external admin prerequisite")
        if entry.get("verification") not in allowed_verification:
            fail(f"{feature} has unsupported verification state")

    live = object_field(policy, "live_enforcement")
    if live.get("source") != "github-ruleset" or live.get("ruleset_name") != "Protect Main":
        fail("live enforcement source must remain the Protect Main GitHub ruleset")
    if live.get("verification") != "external-admin-surface":
        fail("live ruleset enforcement must remain externally verified")
    if live.get("repository_owned_policy_is_not_live_attestation") is not True:
        fail("repository-owned policy must not be represented as live attestation")

    codeowners = load_codeowners()
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
        "BLOCKED: single-maintainer independent review",
        "Signed protected history",
        "Auto-merge and update-branch",
        "External administration prerequisites",
    ):
        if required not in governance_doc:
            fail(f"repository governance documentation is missing: {required!r}")

    print(
        "Repository governance contract: intended review/signature/ownership policy is bound; "
        "live GitHub administration remains separately verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
