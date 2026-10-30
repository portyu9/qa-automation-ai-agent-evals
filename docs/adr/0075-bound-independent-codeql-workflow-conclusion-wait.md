# ADR 0075: Bound independent CodeQL workflow conclusion wait to observed GitHub latency

**Status:** Accepted
**Date:** 2026-10-30
**Supersedes:** ADR 0060 timing assumption only; all security evidence and veto contracts remain mandatory.

## Context

The accepted `main` commit `d93e069c402f77de9be6ee3e84d470872f7a5251` produced independent CodeQL workflow run [41099170673](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/41099170673) and CI run [41099170813](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/41099170813). Its read-only CodeQL scanner job completed successfully by 17:39:56 UTC and its trusted SARIF publisher job by 17:47:12 UTC, but GitHub did not report the overall CodeQL workflow successful until 17:57:54 UTC. CI's protected `Package integrity` job began its CodeQL wait at 17:31:39 UTC, exhausted `90 × 10 seconds` at 17:47:50 UTC, and failed the exact-SHA evidence veto **before** the independently successful CodeQL workflow conclusion became observable. A retry after the workflow finished succeeded. This is a verified bounded-polling liveness failure, not permission to skip CodeQL.

Prior [ADR 0060](0060-bound-postmerge-security-evidence-window.md) aligned CodeQL and Security polling at approximately 15 minutes each, before this observed 29-minute publication/conclusion latency. The CodeQL and Security original scanner workflows and their authentication contracts are unchanged.

## Decision

Keep the exact-SHA, branch, trigger-event, authenticated API and every `verify_required_codeql.py` evidence validation invariant. Extend **only the CodeQL** polling delay in `.github/workflows/ci.yml` from 10 to 30 seconds, with 90 attempts unchanged, yielding approximately 45 minutes of bounded observation with fewer API queries per elapsed minute. Increase the `protected-gate` job timeout from 22 to 75 minutes so this window and the independent unchanged 15-minute Security wait can complete sequentially, including the separately required native PR-head CodeQL gate.

Retain the exact existing Security poll (90 × 10 seconds), native PR-head Code Scanning proof, `ci-gate`, full scanner set, immutable Action SHA pins and minimal read-only token permissions. Never accept a prior-green run, unrelated commit, pending/failed run, missing scanner job, invalid published SARIF, or downstream fallback as CodeQL success.

## Consequences

A correctly qualified but delayed CodeQL workflow has an opportunity to complete before CI declares a timeout. Genuine missing or unsuccessful CodeQL evidence still causes the required Package integrity job to fail after a finite timeout. At most, the CI check may remain pending longer when GitHub cannot complete or report scanner results; this does **not** relax merge protection.

## Assurance impact

Immediate pre-branch lineage-and-salvage preflight: accepted `main@d93e069c402f77de9be6ee3e84d470872f7a5251`; only remote branch `main`; zero open PRs; historical CodeQL wait PRs #372 (merge `8da85cb2947fb7ea26ca07ff9c51a056e01fe081`) and #410 (merge `2479fd91a064925f7dec3e4bb6b5fa7f625e33e5`) were both already accepted, not competing; historical branch searches for `ci` and `codeql` found none. Accepted immutable Git blob IDs: `ci.yml@c656d06c0cc5987fd779db9f8227d6ad6e05a59d`, `verify_required_codeql.py@952573fd7aba8e3c07d7309d5bf16bb6ca913120`, `validate_workflow_graph.py@74bf543b25fce32fc2148948a3c21d5968070d40`, prior ADR 0074 `1e1212065f83872f8100e3bf5bcfe13d744f0dc9`. No divergent historical branch, open competing PR, unique unmerged code or change to these validator implementations was found.

Qualification must run repository policy's semantic workflow validator, CodeQL, Security, native PR-head analysis, and required exact-head gates on the new PR. This ADR records the timing change; it is not a substitute for that execution.

## Non-claims

The change does not resolve the separate GitHub Dependency Review HTTP 403 issue in the eleven QA repositories or assume GitHub schedule latency is bounded globally. It does not establish that any future CodeQL run will complete inside 45 minutes, or that a workflow conclusion can be inferred solely from successful jobs. No GitHub repository administrative permission or security setting was changed.
