# ADR 0025: Read-only Scorecard evidence visibility without elevated merge authority

**Status:** Accepted pending real post-merge SAST recognition confirmation.

## Context

The latest accepted `main@98f37231ef0e8db345e00d6f72265617520774ee` has a genuinely successful CodeQL push scan [38627529184](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38627529184), job 116070382428: upload completed, both SARIF files retained, and the local zero-alert gate passed. Yet the authentic main Scorecard [38627529298](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38627529298) reports SAST `0/30` recognized commits, while the CodeQL tool itself is recognized (score 7). Thus CodeQL execution and Scorecard's historical recognition are separate claims. No assertion is made that missing permission is conclusively the cause.

The Scorecard GitHub Action's official guidance recommends explicit `checks:read`, `issues:read`, and `pull-requests:read` for observing GraphQL and SAST metadata when permissions are restricted. The existing Scorecard job explicitly declared only `contents:read` and `security-events:write`; unspecified GitHub Actions token scopes can be `none` after permission narrowing. These are read-only observation capabilities and should not change accepted merge authority.

Issue #349 contains a 2026-10-14 lineage-and-salvage preflight: one live branch (`main`), no open PRs, no divergent historical branch carrying unmerged code, and accepted relevant commits/blobs from PRs #350/#351/#354/#356/#357/#359/#361/#362/#363/#364. All those controls are preserved.

## Decision

Grant **only** `checks:read`, `issues:read` and `pull-requests:read` in the trusted-main Scorecard job. Keep the workflow-wide `contents:read`, the job-only `security-events:write` SARIF upload, pinned immutable actions, `persist-credentials:false`, and exactly push/schedule/manual dispatch triggers. No pull request or `pull_request_target` execution, no PAT secret and no broader write authority are introduced.

Extend the repository-owned semantic YAML workflow validator to require the exact Scorecard trigger, job inventory and token grant; deliberately reject missing/none/write mutations of the read scopes, loss of SARIF write, and an untrusted PR trigger. Tests fail closed before merging.

## Verification and non-claims

Passing parser tests proves only that the desired permissions are declared and protected against regression. A successful Scorecard job **does not** prove its SAST detector recognizes every actual CodeQL commit. After merge, review exact-head CodeQL, Security, CI and authentic Scorecard SARIF. Record whether `SASTID` recognition changed; do not dismiss #27 or #349 on inference. The 18 local-source Scorecard PinnedDependencies detector findings, human reviewer governance, fuzz integration, age-based Maintained and external OpenSSF Best Practices enrollment remain independent open items. Do not downgrade BLOCKED to PASS or treat a hash as publisher authentication.

## Consequences

- **Positive:** a trusted-main Scorecard run receives documented read-only visibility into checks, issues, and pull-request metadata; structural policy tests catch accidental read-scope loss or write/trigger escalation before merge.
- **Tradeoff:** a small increase in metadata visibility for the existing Scorecard observer, with no additional mutation authority. The upload action still has precisely the prior job-only security-events write permission.
- **Limitations:** token availability, GitHub check-history data, detector behavior and scanner timing are external. The genuine SARIF result decides whether SAST recognition improves; absent recognition remains an open finding. No automatic suppression or synthetic check history is allowed.

## Assurance impact

The only security authority change is **read-only discovery** within the already trusted-main Scorecard observer. Read access cannot approve, merge, dismiss, mutate source, or upload SARIF. The previously authorized job-only `security-events:write` remains restricted to a workflow that never runs untrusted PR code. The CI semantic validator locks the read surface and exact trigger to prevent either accidental observation loss or token privilege creep. Existing CodeQL, Security, protected Package integrity, dependencies, release attestation and review-governance controls remain unchanged.

## Non-claims

- Explicit read scopes do not guarantee the Scorecard SAST detector will recognize CodeQL check history; only authentic post-merge SARIF confirms that.
- CodeQL's genuine zero-alert gate does not prove an absence of all vulnerabilities.
- Scanner read access is not independent human review and does not close BranchProtection, CodeReview, Fuzzing, Maintained, Best Practices or PinnedDependencies warnings.
- No source-owned policy declaration authenticates unobservable GitHub administrator settings, and no BLOCKED observation becomes PASS merely because a scheduled workflow completes.
