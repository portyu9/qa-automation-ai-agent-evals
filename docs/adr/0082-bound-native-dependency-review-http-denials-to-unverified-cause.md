# ADR 0082: Do not attribute native dependency comparison HTTP denials to an unverified repository setting

**Status:** Accepted
**Date:** 2026-11-10
**Supersedes:** The unsubstantiated operator-facing assertion that native dependency comparison HTTP 403/404 proves the repository dependency graph is disabled, or that closed issue #193 is the active source of truth. It does not supersede any dependency assurance gate or existing ADR governing native review.

## Context

For the pull-request dependency delta, the authenticated GitHub dependency-graph compare API returned HTTP 403. The existing workflow classified the response as `blocked-admin-prerequisite`, but the accompanying warning asserted that the dependency graph was disabled. HTTP 403/404 alone does not identify whether the actual cause is effective token authorization, repository graph configuration, feature entitlement, or another GitHub-side prerequisite. The active tracking issue is #440; prior issue #193 is closed. An inaccurate root-cause message can misdirect incident response and falsely imply that the current repository configuration was independently inspected.

The existing PR path already uses the native `actions/dependency-review-action` when the authenticated compare probe returns HTTP 200; it retains `warn-only: "false"`, real scanner coverage, and strict failure on unexpected HTTP statuses. An HTTP denial does not establish that native dependency-delta analysis ran or passed.

## Decision

Keep the probe and all admission, terminal-state, and security policy conditions unchanged. For HTTP 403 or 404, continue to emit the existing `blocked-admin-prerequisite` state while explicitly describing the **unverified** cause and the absence of native change-aware review, referring to active issue #440. Never infer a specific administrative state from the denial alone. An authenticated HTTP 200 remains only the precondition for executing the native semantic review, not evidence of a passing review by itself. Unexpected HTTP status and unknown final states remain blocking, with no silent fallback or status forgery.

Three regression tests bind the no-attribution rule, native-action and strict-failure admission, and the final degraded-coverage notice. This is an evidence-honesty correction; it does not grant waivers or authorize a merge without the repository's independent CI, Security, CodeQL, package-integrity and governance checks.

## Consequences

Operator-facing diagnostics can no longer claim a specific disabled setting that has not been independently proven. Native GitHub dependency-delta coverage remains **blocked** until an authenticated comparison succeeds and the native dependency-review action genuinely executes. The responsible GitHub configuration/authorization prerequisite remains tracked by #440. Independent scanners and other required gates must remain operational; reporting `blocked-admin-prerequisite` is not equivalent to passing native review.

## Assurance impact

No alteration to data-plane behavior, native review action identity, dependency comparison admission, `warn-only` semantics, CI-gate resolution, or repository permissions. Acceptance requires a new, append-only ADR under this governance policy; tests and exact PR-head CI, Security and CodeQL must pass. Restore and independently verify native compare coverage before changing the blocked finding.

## Non-claims

- This ADR does not assert that the dependency graph is disabled or enabled.
- This ADR does not assert whether HTTP 403 was caused by authorization, settings, or product entitlement.
- This ADR does not claim that changing diagnostic strings resolves the administrative prerequisite or delivers native dependency-delta scanning.
- This ADR does not waive a real security failure, invent green status, or close issue #440.
