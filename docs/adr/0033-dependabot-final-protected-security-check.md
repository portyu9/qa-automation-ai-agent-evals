# ADR 0033: Gate autonomous Dependabot approval on the final protected security bridge

**Status:** Accepted (candidate must pass exact-PR and independent accepted-main qualification).

## Context

The signed-source, 12-profile hash-lock publisher and narrowly scoped Dependabot governor are already accepted. Before this ADR the governor's `requiredChecks` configuration was **only** `["ci-gate", "CodeQL"]`. However, `ci-gate` finishes *before* the separately required `Package integrity` check. `Package integrity` independently verifies the exact-head CodeQL workflow and the independent Security workflow's scanner and `security-gate` jobs before the native ruleset permits merge. Therefore the governance controller could issue a programmatic owner-authenticated review/approval based on preliminary green CI and CodeQL **before** the final Security bridge had passed. The native branch ruleset still blocks the merge, but an earlier owner approval or a statement of verified security qualification is premature and should not be issued.

A second trust gap: `latest_checks` selected check runs by name and reported success only, without confirming that `ci-gate`, `CodeQL`, or `Package integrity` originated from the **approved GitHub Actions App** and the current exact PR head. An arbitrary same-named check run could otherwise be mistaken for legitimate evidence inside the governor, even though the native ruleset itself pins the GitHub Actions integration ID.

The issue #360 [lineage-and-salvage preflight](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/360#issuecomment-6182244878) established current `main@070d8edc44619d7ea15861371c5eaf0e1163be01`, only one live branch, zero open PRs, and all historical overlapping Dependabot/check bridge work accepted in main. No unique divergent code was left behind. A genuine GitHub check-runs read of merged [PR #373](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/373) head `6e225333e1c5ee8f3490c63e8ea7bc8f215e192d` independently confirmed each of `ci-gate` (check ID 116193962737), `CodeQL` (116193202628) and `Package integrity` (116193992498) has `app.id=15368`, `app.slug=github-actions`, `head_sha` exactly matching the source, and authentic `completed/success`.

## Decision

Change the exact required check list to `["ci-gate","CodeQL","Package integrity"]` and preserve this exact order and membership through `validate_config`. The controller will not classify a Dependabot update eligible for automated **owner review** until the final `Package integrity` bridge completes successfully. This is independent from (and stricter than) merely checking that the native merge API would eventually reject an unqualified PR.

Every individual required check run must now authenticate:
- The **same exact PR head commit SHA** used for signed bot provenance and the pending protected merge.
- The *trusted GitHub Actions integration* by numeric GitHub App ID `15368` **and** slug `github-actions`.
- `status=completed` and `conclusion=success`; missing, skipped, cancelled, failed or in-progress are not eligible.

The app ID derives from the **current live protected ruleset**, not from arbitrary content in the PR. This is an executable invariant in the trusted, repository-owned governor, not a self-declared trust extension. Check names alone and uploaded cryptographic hashes are not sufficient as authentication.

Add fail-closed deterministic fixtures proving an absent/pending/failed/skipped `Package integrity` veto, missing/foreign App identity, mismatched head, and newer same-named foreign check-run are rejected. Preserve the independent existing owner latest-veto precedence from ADR 0032, native required seven status checks, read-only PR CodeQL scanner, signed canonical bot commits, trusted lock publisher, exact-head protected Security and final merge SHA binding. No extra GitHub workflow token authority or bot discretionary edit powers are introduced.

## Consequences

A genuine eligible Dependabot update may spend additional time awaiting the final protected gate before the next hourly governor reconcile. This is intended; completing the 12-lock publisher, external CodeQL, and independent Security is necessary evidence, not a performance optimization target. The controller will not post an owner-authenticated approval merely because aggregate CI and CodeQL appear green while final Security qualification remains pending.

A malformed or forged check-run result is `BLOCKED`; it does **not** convert into success or authorize a signed child merge.

## Assurance impact

This closes a real gap between the governor's earlier two-check approximation and GitHub's actual final non-compensatory branch-protected security gate. It additionally verifies native GitHub Actions app origin and binds result claims to the exact signed source head, rather than accepting arbitrary successful name aliases.

## Non-claims

- This does **not** assert an independent human reviewer: programmatic owner-token approval remains the **same account** and cannot qualify the CodeReview Scorecard criterion.
- A passing unit test is **not** a real new eligible signed Dependabot E2E; the first new 12-profile current-policy PR, authenticated owner token, final merge SHA and postmerge CodeQL/Security still require real-world qualification under #360.
- The 23 open OpenSSF Scorecard SARIF posture findings are not confirmed exploitable vulnerabilities, and this change does not suppress alerts or remove scanner-limited local-source pip-install smoke tests. No hash is equated with publisher authentication. Repository-admin review quorum, SAST recognition, Best Practices self-enrollment, age-based Maintained and external fork PR testing remain open.
