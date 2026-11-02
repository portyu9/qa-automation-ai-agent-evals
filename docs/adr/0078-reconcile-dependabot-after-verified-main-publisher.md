# ADR 0078: Wake Dependabot reconciliation after verified main-owned CodeQL publication

**Status:** Accepted
**Date:** 2026-11-02
**Supersedes:** ADR 0077's decision to restrict privileged dependency reconciliation exclusively to push/schedule/dispatch. ADR 0077's ten-minute phase, owner authentication, and fail-closed approval and qualification rules remain in force.

## Context

Accepted main `23be1ab44efdde70eeeffcc359bb5e4b5c5ef667` includes ADR 0077 and its six-per-hour cron at minute 02/12/22/32/42/52. Its exact-main CI, CodeQL and Security qualification completed successfully after the merge of PR #434. Two open bot PRs reached fully green, clean heads: #431 (`bd9bc6ab3e33ee91065bcb3a273f2954669bfcad`, signed Dependabot Ruff source plus separately signed hash-lock publisher) and #432 (`7341a38f0f288cfcc7cd500118dee2e83a12db02`, signed Dependabot action pin). Both had no owner approvals. The existing controller's last privileged run was on the earlier accepted-main push, before both bot PRs were requalified, and its PR-triggered self-test cannot grant merge authority. At 18:15 UTC no new scheduled governance run had registered, despite the 18:02 and 18:12 scheduled opportunities. Historical schedule observations on the same repository also showed multi-hour gaps (2026-11-02 00:40 to 07:38 UTC; 2026-11-01 20:28 to 2026-11-02 00:40 UTC), so an increased cron frequency does not guarantee convergence latency.

GitHub documents that scheduled workflows are best-effort and can be delayed or dropped. GitHub also warns that privilege-bearing `workflow_run` triggers may be exploited when they trust PR-controlled runs, check out untrusted source, or consume arbitrary artifacts. The already accepted `ai-qa-automation` controller uses segregated, provenance-verified `workflow_run` qualification as one alternative to relying exclusively on schedules. A direct candidate-PR or arbitrary-workflow wake is not acceptable.

## Decision

Retain the trusted ten-minute scheduled retry and exact-main push/dispatch paths. Additionally let the main-owned `Trusted CodeQL PR-head publication` workflow, and only that workflow, wake the existing main-owned Dependabot controller upon completion. At the job-admission boundary require **success**, publisher run's `head_repository.full_name == github.repository`, `head_branch == main`, and `head_sha == github.sha`; register the trigger only on `main`. Before any checkout or access to `DEPENDABOT_OWNER_TOKEN`, reauthenticate the live current main and workflow ref and retrieve the **original completed run from GitHub's API** using the webhook's numeric run ID. Resolve the current publisher workflow ID via the accepted-main workflow endpoint, and require the original run's `workflow_id` to match exactly; the original workflow name, complete/success status, repository identity, main branch, original main SHA, and permitted publisher event must also match. Never trust the webhook's displayed name alone.

Execute the existing `dependency_governance.py --reconcile --allow-merge` only after that preflight. It re-fetches each exact current PR head; enforces signed bot and trusted lock-graph provenance, semantic scope, actual security/CodeQL/CI status, time and label vetoes; and obtains separate authenticated owner approval only after passing its current exact-head qualification. No source from candidate PRs is checked out, evaluated or executed in this privileged job; no untrusted artifact is consumed; and no permission or token scope changes. The ten-minute schedule remains the fallback when no successful publisher run arrives.

## Consequences

Successful, GitHub-authenticated main-owned CodeQL publication now provides a bounded event-driven reconciliation opportunity independent of cron delivery. Every wake still performs live exact-main and exact-bot-head assessment; absent publisher completion or failed provenance cannot approve or merge. Multiple publisher completions may enqueue redundant governance executions, but the existing serialized reconciliation group and exact-head checks prevent stale duplicate merges. GitHub schedule remains an independent best-effort fallback and is not promoted to an SLA.

## Threat model and regression evidence

The `workflow_run` event is **a wake hint, not an authorization credential**. An attacker can potentially cause a same-name workflow or re-run a stale workflow. Reject every case whose GitHub-verified `workflow_id`, source repository, main ref, completed-success state, or exact live SHA differs from the accepted provenance. Validate this in the semantic workflow graph validator, including independent negative mutations for publisher source identity and live main validation; retain exact-source checks in `test_dependency_governance_push_wake.py` so altering either the original push guard or new publisher guard fails closed. Retain `pull_request_target` prohibition, exact single owner-token placement, and no extra event-trigger privileges.

GitHub `workflow_run` cascade depth remains limited; the upstream CodeQL PR run, accepted main publisher and main reconciliation are within the permitted chain depth. The fallback schedule and main push are independent paths if the publisher does not run.

## Assurance impact

The new privileged trigger requires an additional separately verified GitHub workflow ID and exact live current-main proof before checking out trusted source or exposing owner approval credentials. Existing post-merge protected qualification, zero-alert CodeQL, signed source and lock graph, approved reviewer identity, and owner-veto constraints are unchanged. The extra trigger widens the wake surface, not the set of approvable or mergeable PRs. Any change to event origin, token placement, or source provenance must fail the independently pinned workflow-graph and unit exact-source regression suites.

## Lineage and salvage preflight

Before creating this branch, inspected accepted main `23be1ab44efdde70eeeffcc359bb5e4b5c5ef667`, open PRs #431 and #432, and all remote branches. The remote branches were exclusively `main`, `dependabot/pip/routine-dependencies-2503575160@bd9bc6ab3e33ee91065bcb3a273f2954669bfcad` and `dependabot/github_actions/routine-actions-d6f809a3bd@7341a38f0f288cfcc7cd500118dee2e83a12db02`; earlier fix #434 was already merged, not divergent. Unique PR #431 Ruff manifest and twelve hash/compatibility lock changes, and unique PR #432 action pin remain **must preserve**. Earlier PR #433/434 merged capabilities are **already accepted**. Older closed superseded branch #422 remains **superseded** with no active unique code indicated by the repository branch inventory. No bot branch was modified or duplicated.

Source blobs at branch creation: governance workflow `9ee44648a73b5caa430ceb5d33fb64e4e2808fa2`, semantic validator `a4802b15999f5348c4e07ea707194c6531808af8`, exact-source test `ee0bccf5c39339db1e8db8bdc9b16ae4a793ea0d`. The amended control path must pass full PR-head CI/security/native CodeQL, semantic ADR and workflow self-tests, mutation assurance and the protected `ci-gate`/`Package integrity` checks before merging. After merge observe live event-driven reconciliation, independent signed-bot merges, and exact new-main post-merge qualification.

## Non-claims

The new wake does not promise real-time execution, guarantee immediate merge after a passing publisher, or attest absent owner approval. An incomplete/failing/stale publisher does not grant authority. The exact-head controller can still refuse or wait for genuine security evidence and post-merge workflows. GitHub platform schedule delays remain an external limitation; no independent HTTP 403 Dependency Review access issue is fixed by this ADR.
