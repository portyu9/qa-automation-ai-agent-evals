# ADR 0077: Bound main-owned Dependabot reconciliation latency

**Status:** Accepted
**Date:** 2026-11-02
**Supersedes:** The hourly reconciliation cadence in the governance workflow and its self-test. All prior provenance, approval, signed-commit, CodeQL, security, and post-merge contracts remain mandatory.

## Context

On November 2, accepted main `7da6707bd93f14d9c3d7471d5d431ea9fa1e764f` included merged PR #433. In main-owned dependency-governance run `41487412173` at 17:03 UTC, both live signed Dependabot PRs #431 and #432 were correctly diagnosed as stale against the new main; the controller issued owner-authenticated `@dependabot rebase` comments instead of rewriting either bot branch. Dependabot subsequently updated their exact heads to `f5d26c558614f4ba5234792e263ec61ca2a8d5b7` and `e5c007af34e15c07ae3650c5ecfc307aacfc71b3` at approximately 17:07/17:09 UTC. Current required CI, native CodeQL, and package-integrity checks then became successful, but the only scheduled governance reconciliation ran at minute 17 of each hour; successful governance on the earlier main push did not itself merge heads that had not yet completed signed rebase and independent qualification.

The trusted CodeQL PR-head publisher already schedules every ten minutes at minutes 07/17/27/37/47/57, using only main-owned provenance verification. A post-rebase reconciliation period of up to an additional hour is unnecessary liveness latency; eliminating it must not introduce a privileged PR-triggered execution path or substitute successful scheduled workflows for actual eligible PR qualification.

## Decision

Change only the existing `dependency-governance.yml` schedule from minute 17 hourly to six entries per hour at minutes 02/12/22/32/42/52, offset by five minutes from the trusted CodeQL publisher. Keep `push` restricted to `main`, retain existing unprivileged `pull_request` governance self-tests and manually invoked reconciliations, and add neither `workflow_run` nor `pull_request_target` to privileged reconciliation. GitHub schedules are best-effort, not a hard ten-minute service-level guarantee.

Update `dependency_governance.py` self-test and the independent exact-source `test_dependency_governance_push_wake.py` guard to require the new phase instead of the old hourly contract. Retain the push wake guard's verbatim restricted source and add negative fixtures for hourly rollback and overbroad minute scheduling. Extend the PyYAML-based semantic workflow graph validator with the exact trusted trigger/schedule check and negative fixtures demonstrating that an hourly downgrade, wildcard push, or privileged PR-target introduction fails closed. Do not alter the `govern-dependabot` job's token scope, owner-authenticated exact-head review, Dependabot commit signature policy, canonical dependency-semantic validation, CodeQL zero-alert qualification, `ci-gate`, `Package integrity`, or required post-merge Security/CodeQL/CI runs.

## Consequences

After a completed signed Dependabot rebase and full head-specific qualifications, the trusted reconciler will usually have more frequent opportunities to assess and merge without additional owner intervention. API delay, GitHub schedule delay, fresh main movement, unprocessed source provenance, missing required checks, or owner review veto can still legitimately block or defer a merge. No previously failed or pending check is reclassified as success. Failed initial CodeQL PR-head publication during a still-running newest scan remains a valid fail-closed result; a later completed verified run must qualify separately.

## Assurance impact

Before branching, exact accepted `main` was `7da6707bd93f14d9c3d7471d5d431ea9fa1e764f`, including prior accepted PR #433 head `949488ffbb800e111d6d5bbcc4b7041f39cc584c`. Existing remote branches were only `main`, bot PR #431 head `f5d26c558614f4ba5234792e263ec61ca2a8d5b7` and bot PR #432 head `e5c007af34e15c07ae3650c5ecfc307aacfc71b3`. Both bot branches are **must preserve**; #431's unique Ruff+12 lock/compatibility changes and #432's unique signed zizmor action pin remain independent and unmodified. Earlier governance PRs #420/#424 and CodeQL PR #429 were already merged; closed older bot action PRs #417/#422 were superseded by accepted newer versions. No divergent active lane implementation branch was found.

Accepted source blobs before this change: `dependency-governance.yml@09d865a96482513aae074177928a2f4a83c05036`, `validate_workflow_graph.py@74bf543b25fce32fc2148948a3c21d5968070d40`, `dependency_governance.py@4f61a02527018ccd402335d4965bf73ea8d7a525`. Qualification must require fresh PR-head repository-policy/ADR validation, both governance self-tests, immutable action graph checks, CodeQL, security scanning, and full CI rather than a prior green source head. After merge, requalify exact accepted main and observe native bot reconciliation on newly current heads.

## Non-claims

A ten-minute cron expression is not proof of execution within ten minutes, nor proof of future Dependabot merges. It does not remove GitHub administrative limitations, grant additional API token privileges, or bypass owner veto, signed-commit checks, live base/head reauthentication, CodeQL zero alerts, required CI, or protected post-merge workflow evidence. No unrelated QA repository is modified by this decision.
