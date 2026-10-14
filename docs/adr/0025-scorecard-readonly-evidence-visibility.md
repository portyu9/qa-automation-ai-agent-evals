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
