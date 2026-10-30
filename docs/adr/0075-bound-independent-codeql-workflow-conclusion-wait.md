# ADR 0075: Bound independent CodeQL workflow conclusion wait to observed GitHub latency

**Status:** Accepted
**Date:** 2026-10-30
**Supersedes:** ADR 0060 timing assumption only; all security evidence and veto contracts remain mandatory.

## Context

The accepted `main` commit `d93e069c402f77de9be6ee3e84d470872f7a5251` produced independent CodeQL workflow run [41099170673](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/41099170673) and CI run [41099170813](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/41099170813). Its read-only CodeQL scanner job completed successfully by 17:39:56 UTC and its trusted SARIF publisher job by 17:47:12 UTC, but GitHub did not report the overall CodeQL workflow successful until 17:57:54 UTC. CI's protected `Package integrity` job began its CodeQL wait at 17:31:39 UTC, exhausted `90 × 10 seconds` at 17:47:50 UTC, and failed the exact-SHA evidence veto **before** the independently successful CodeQL workflow conclusion became observable. A retry after the workflow finished succeeded. This is a verified bounded-polling liveness failure, not permission to skip CodeQL.

Prior [ADR 0060](0060-bound-postmerge-security-evidence-window.md) aligned CodeQL and Security polling at approximately 15 minutes each, before this observed 29-minute publication/conclusion latency. The CodeQL and Security original scanner workflows and their authentication contracts are unchanged.

## Decision

Keep the exact-SHA, branch, trigger-event, authenticated API and every `verify_required_codeql.py` evidence validation invariant. Update the repository-owned `validate_runtime_policy.py` contract to require the new 75-minute protected gate and 90 × 30-second bounded CodeQL wait, preserving static refusal of shorter/ungoverned windows. Extend **only the CodeQL** polling delay in `.github/workflows/ci.yml` from 10 to 30 seconds, with 90 attempts unchanged, yielding approximately 45 minutes of bounded observation with fewer API queries per elapsed minute. Increase the `protected-gate` job timeout from 22 to 75 minutes so this window and the independent unchanged 15-minute Security wait can complete sequentially, including the separately required native PR-head CodeQL gate.

Retain the exact existing Security poll (90 × 10 seconds), native PR-head Code Scanning proof, `ci-gate`, full scanner set, immutable Action SHA pins and minimal read-only token permissions. Never accept a prior-green run, unrelated commit, pending/failed run, missing scanner job, invalid published SARIF, or downstream fallback as CodeQL success.

## Consequences

A correctly qualified but delayed CodeQL workflow has an opportunity to complete before CI declares a timeout. Genuine missing or unsuccessful CodeQL evidence still causes the required Package integrity job to fail after a finite timeout. At most, the CI check may remain pending longer when GitHub cannot complete or report scanner results; this does **not** relax merge protection.

## Assurance impact

Immediate pre-branch lineage-and-salvage preflight: accepted `main@d93e069c402f77de9be6ee3e84d470872f7a5251`; only remote branch `main`; zero open PRs; historical CodeQL wait PRs #372 (merge `8da85cb2947fb7ea26ca07ff9c51a056e01fe081`) and #410 (merge `2479fd91a064925f7dec3e4bb6b5fa7f625e33e5`) were both already accepted, not competing; historical branch searches for `ci` and `codeql` found none. Accepted immutable Git blob IDs: `ci.yml@c656d06c0cc5987fd779db9f8227d6ad6e05a59d`, `verify_required_codeql.py@952573fd7aba8e3c07d7309d5bf16bb6ca913120`, `validate_workflow_graph.py@74bf543b25fce32fc2148948a3c21d5968070d40`, prior ADR 0074 `1e1212065f83872f8100e3bf5bcfe13d744f0dc9`. No divergent historical branch, open competing PR or unique unmerged code was found before branching. The PR updates only the CI workflow and its runtime-policy timing validator, plus this append-only ADR; the CodeQL evidence verifier and semantic workflow validator remain byte-identical to accepted main.

Qualification must run repository policy's semantic workflow validator, CodeQL, Security, native PR-head analysis, and required exact-head gates on the new PR. This ADR records the timing change; it is not a substitute for that execution.

## Qualification observation: original-run provenance, retries, and API eventual consistency

The first qualification of this change surfaced a separate GitHub Actions evidence-delivery defect, tracked in [issue #430](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/430). Read-only PR CodeQL run `41109344863`, head `1805e704d078daa99b2501c325e3fd93317933da`, completed successfully and its runner log showed all five required CodeQL steps and an uploaded exact-run SARIF artifact. The authenticated Actions jobs API initially reported `steps: []` for completed-success job `124248035013` and a separate Repository policy job. Its step inventory subsequently backfilled gradually, with initially missing or null step conclusions; by 21:57 UTC on October 30 it returned all 11 completed-success scanner steps. A separately re-executed CodeQL job `124251769900` also eventually returned the full completed-success scanner step inventory. The underlying scanner, SARIF and policy verifier did not change between these observations. A successful aggregate workflow alone must not substitute for authenticated step-level provenance.

That original CodeQL rerun exercised a deliberate further provenance boundary: accepted-main trusted publisher `verify_codeql_pr_publication.py` requires `run_attempt == 1` on both the canonical run and event, so after rerunning `41109344863` to attempt 2, subsequent trusted publisher schedule run `41122251303` refused `CodeQL run: run_attempt is not the expected value`. This is an intentional replay restriction, not a reason to permit attempt 2 or to override the protected native PR-head CodeQL check. Qualification must use a genuine first-attempt CodeQL workflow for a newly advanced PR head; a fresh evidence-bearing documentation update within this unmerged ADR provides a new non-replayed source head without rewriting any accepted ADR, scanner, token scope, or publisher logic.

The complete lineage remains the existing PR #429 branch; no new lane branch or unique independent source code is introduced. The observed missing-step and rerun constraints concern PR security qualification, independent of the original accepted-main CodeQL workflow-conclusion wait that this ADR addresses.

## Non-claims

The change does not resolve the separate GitHub Dependency Review HTTP 403 issue in the eleven QA repositories or assume GitHub schedule latency is bounded globally. It does not establish that any future CodeQL run will complete inside 45 minutes, or that a workflow conclusion can be inferred solely from successful jobs. No GitHub repository administrative permission or security setting was changed.
