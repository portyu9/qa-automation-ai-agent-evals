# ADR 0068: Bound native Dependabot rebase escalation without manufacturing signed source

**Status:** Accepted
**Date:** 2026-10-27
**Supersedes:** The indefinitely pending native `@dependabot rebase` refresh state in the owner-authenticated dependency governance controller. All signed-source, security, reviewer and protected-merge decisions remain unchanged.

## Context

Native signed Dependabot Actions PR #417 retains four unique immutable action-pin changes against a superseded base. The accepted main now contains the upstream-action scanner fix and its separately certified security source. An owner-authenticated `@dependabot rebase` command on #417 was issued by the trusted controller after that accepted-main advance; over two hours later, Dependabot had not emitted a new signed head. The controller's existing one-per-exact-head comment deduplication prevented a duplicate command, but its next scheduled runs continued to report `refresh-requested` indefinitely. Old failing first-attempt CI cannot qualify the old head, and a human-authored replacement of the native bot commit would lose the required publisher/provenance trust.

## Decision

Retain Dependabot's original signed source, current-main lease checks, semver and controlled path verification, owner-token identity binding, manual-review vetoes, and required authentic CI/Security/CodeQL/Package integrity checks. Introduce a small finite-state, deterministic *request* controller. For each exact pair of immutable Dependabot head SHA and accepted main SHA, an owner token may publish a single authenticated `@dependabot rebase` request. Only after that precise owner's authenticated comment has an unambiguous GitHub timestamp at least the explicitly configured `nativeRefreshEscalationMinutes` old may the controller publish at most one `@dependabot recreate` request for that same pair. The config bounds the escalation interval to 30–1440 minutes and currently sets 120.

The proof requires both the owner's login and immutable numeric user ID, a precisely bound command marker, valid chronological evidence, and no duplicate owner commands. Other commenters, changed head/main identities, missing or future timestamps, malformed response rows and repeated commands cannot trigger escalation. Immediately before either side effect, re-fetch the bot PR head/base and protected accepted-main SHA. Any movement or ambiguity fails closed and the next scheduled run must start a new assessment. The second command only asks the **native Dependabot service** to issue a fresh signed candidate; the governance controller is forbidden to write the bot branch, synthesize statuses, replay a red run as green, or waive a required reviewer.

A single original signed bot head may remain stalled after this second request if the external Dependabot service is unresponsive. That is a visible pending/block condition, not permission to force-merge or silently replace its unique pin payload. The governing change is reviewed under the repository's append-only ADR policy and must itself pass genuine protected CI/security.

## Consequences

The controller has one bounded recovery escalation instead of indefinite rebase-only requests. Run-to-run comment deduplication remains stable. Legitimate owner-originated requests are distinguished from unauthenticated or malformed comments; duplicate and future-timestamp conditions fail closed. Adversarial self-tests cover no previous request, premature and overdue transitions, exact-head/current-main substitution, different owner IDs/logins, malformed time, duplicate requests, idempotency and invalid configuration bounds.

External Dependabot can still be unavailable. Additional recovery beyond the one replay-safe request requires a separately reviewed architecture decision, not an unbounded command loop. This ADR does not require or permit new GitHub secrets, Actions permissions, PAT scopes, branch protection bypass, or change to the native signed release source.

## Assurance impact

The accepted pre-branch baseline is `main@32d1e451e20c99e2ce1214f2567e4ff3aa4f6e7f` with trusted governance script blob `e4fce0fc114a52d4c93e80d06ec7596a55f5cf09`. Native bot #417 head `a03140e930cc0c124e2ea6501e62a6fa037d510f` contains four unique **must preserve** workflow blobs; the exact blob IDs are recorded in the bot PR's bounded-recovery comment. Previously merged scanner source PR #418 and source certificate PR #419 are **already accepted**. No other live divergent source branch existed before this feature lane. Only the governance source, its bounded policy config, and this append-only ADR are changed. New source must pass protected CI, CodeQL, security, semantic ADR and governance self-tests on its exact current PR head.

## Non-claims

A successful command post is **not** evidence that Dependabot actually rebased or recreated its head. This ADR does not claim PR #417 is presently eligible, that any historical failed security or CodeQL run can be reused, that GHAS alert counts are zero, or that an external Dependabot service has any guaranteed response time.
