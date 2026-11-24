# ADR 0090: Fail idle scheduled dependency governance closed on owner-token loss

**Status:** Accepted
**Date:** 2026-11-24
**Supersedes:** Only the previous operational assumption that a green scheduled dependency-governance run with zero open signed Dependabot PRs establishes unattended owner readiness. It does not supersede ADR 0068's bounded native refresh escalation, ADR 0069's owner-command provenance, ADR 0077's reconciliation latency, or ADR 0087's post-merge supersession rules.

## Context

The main-owned AI Agent Evals governance controller verifies the configured owner's exact GitHub login and numeric user ID before issuing native Dependabot refresh commands and exact-head reviews. However, when a scheduled reconciliation wakes with an empty bot-PR queue, no owner operation executes. The scheduled run could finish green even if the owner credential was removed, expired, revoked or misbound. A later security update would discover that failure only when owner approval was needed, making an apparent healthy autonomous controller operationally unavailable.

Credential verification must be distinguished from signed-bot provenance, review authorization, PR qualification, accepted-main CI and security attestation. An empty queue proves no dependent change was processed, not that owner recovery will remain available.

## Decision

For the trusted, default-branch `schedule` event only, invoke the already accepted `_verified_owner_token` check before opening or scanning Dependabot PRs. It performs authenticated GitHub user retrieval with the configured owner token and requires the exact configured login and numeric ID. Missing, expired, inaccessible, malformed or wrong-owner credentials remain hard `GovernanceError` failures. Emit a machine-readable `owner-readiness` event with `checked=true` and `identity=verified` only after the authentic upstream identity request succeeds. No token, login or numeric ID may appear in that diagnostic receipt.

For non-scheduled push, workflow_run, workflow_dispatch and PR events, preserve all previously accepted behavior. Do not perform this extra credential probe on untrusted PR code or alter trusted workflow permissions. The repository-bound current-main owner approval and merge paths continue independently to apply all existing checks.

Add built-in adversarial selftests for valid identity, missing token, expired credential response, wrong user ID and non-schedule event isolation. Do not weaken required semantic-ADR, CodeQL, dependency review, reproducible release or security gates.

## Consequences

A scheduled run with zero eligible signed bot PRs now fails visibly if owner credentials cannot perform their required role. This may expose a previously masked secret configuration outage. The operator must restore the existing authorized owner credential through repository configuration; automatically inventing or copying a secret is forbidden.

The same scheduled run can still return successfully when the owner token authenticates even if there is no signed change to process. This is a readiness signal only; future native bot refresh or GitHub scheduling may independently fail. No merge is produced from an empty candidate set.

## Assurance impact

Exact owner token identity is checked using an authenticated GitHub request rather than inferred from an environmental secret name, a passing no-op or a forged PR comment. The new selftests are deterministic and fail closed on injected wrong identities, invalid credentials and unexpected owner probes on other event types. All existing signed Dependabot SHA provenance, PR policy, owner review, CI, CodeQL, dependency review, and post-merge qualification requirements remain unchanged.

The ADR and implementation must be accepted only with repository-policy, full CI, security and CodeQL checks on the same PR head, followed by merged-main validation. No GitHub App privilege, ruleset bypass, or alternate merge route is introduced.

## Non-claims

- Passing scheduled owner authentication is not evidence that an ignored native Dependabot recreate was eventually salvaged, merged and requalified.
- This ADR does not certify a zero-vulnerability inventory: live Dependabot alert APIs may remain inaccessible to the connected automation.
- It does not establish a service-level guarantee for GitHub's actual cron scheduling cadence or bypass a stale/failed webhook.
- It does not reintroduce retired credentialed live-provider canaries, external API costs or out-of-scope provider tokens.
- It does not authorize synthetic signed bot commits, workflow status fabrication, reusing obsolete PR heads, or relaxing fail-closed merge rules.
