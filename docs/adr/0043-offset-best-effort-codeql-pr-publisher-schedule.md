# ADR 0043: Offset the trusted CodeQL PR publisher's best-effort schedule

**Status:** Accepted

## Context

Same-repository pull requests use a read-only, no-security-write CodeQL
producer, including the original two-file zero-alert SARIF gate. A separate
privileged accepted-main scheduler or explicit owner dispatch independently
authenticates exact current PR-head source/run/artifact/digest/original SARIF
and publishes it through GitHub's native Code Scanning app. This trust split
was documented and tested in ADRs 0038–0042. Privileged publication must
never execute candidate PR code or treat hashes as authentication.

The accepted trusted workflow's schedule was `*/10 * * * *`, executing
nominally at minute zero and each multiple of ten. The publisher's last
actual observed scheduled runs on October 16, 2026 were
[38848732252](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38848732252)
at 04:04:45 UTC and
[38877431090](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38877431090)
at 09:00 UTC. Despite later nominal schedule slots, no more publisher
runs had appeared when live PR #387 passed all 13 strictly enforced checks
and its read-only source CodeQL scan. Its native GitHub Advanced Security
CodeQL check never materialized before normal protected merge. Genuine,
unfiltered post-merge Scorecard SARIF retained `SASTID` at 18 of 30
recognized commits. The absence of an Actions run is not evidence that a
repository security check passed; nor does it prove a specific GitHub
scheduler root cause.

GitHub-hosted scheduled jobs are best-effort; scheduled work can be
delayed or dropped, with the start of the hour a particularly contended
period. An on-the-hour `*/10` expression includes that crowded boundary.
The repository controls source configuration, but not hosted scheduler
delivery guarantees.

## Decision

Use `7,17,27,37,47,57 * * * *` for the accepted-main publisher.
This maintains a **10-minute nominal period** while shifting every slot
away from minute zero. Retain the explicit main-only
`workflow_dispatch` owner option, but **do not** introduce untrusted PR
triggers, `pull_request_target`, `workflow_run` token promotion,
new write permissions, self-reported SAST successes, or a scheduler
fallback that could bypass the exact accepted-main provenance checks.

Update the repository's fail-closed workflow-graph validator to require
the *exact* shifted expression, alongside its existing exact job steps,
write-scope pinning, immutable main checkout, SARIF veto, and publication
category checks. The negative fixtures explicitly reject both reverting
to `*/10 * * * *` and broadening to `* * * * *`; existing fixtures
also reject `pull_request_target`, attacker-substituted run IDs and
commit SHAs, token scope expansion, and tampered digest enforcement.

Keep the accepted CodeQL producer workflow, original evidence artifact
verification, publisher Python, one-job authority boundary, zero-alert
veto, active `.github/workflows/codeql.yml:codeql-upload` category,
and Protect Main's 13 required checks **unchanged**.

## Consequences

Nominal schedule opportunities remain six per hour, simply offset.
Moving away from minute zero may reduce platform scheduling contention,
but there is **no guaranteed upper bound** for delay, delivery, or actual
native GitHub Code Scanning result publication. Failure to observe a
new accepted-main run still requires an explicit BLOCKED / evidence-
pending conclusion, not retrospective PASS.

Subsequent same-repository PRs must still be checked on their own
current exact-head native GitHub Code Scanning app conclusion
`success`; an ordinary green GitHub Actions CodeQL job is not
equivalent. Historical SAST coverage only changes when genuine
Scorecard-observed commits qualify. The case of external forks remains
separately BLOCKED for privileged native publication until a safe,
independently tested mechanism exists.

## Assurance impact

The change is restricted to best-effort scheduler liveness and the
supply-chain guard that pins the only authorized trigger list. It
does not change security authority boundaries, broaden native publication
eligibility, or compensate for missing evidence. A missed publisher
execution remains genuinely missing; `BLOCKED` must never become
`FAIL` or `PASS` merely for operational convenience.

The schedule change itself requires protected CI, Security, genuine
read-only PR CodeQL and policy self-tests, and the established normal
protected merge. Native exact-head result should be obtained whenever
GitHub actually runs the accepted-main publisher; otherwise the
limitation must be documented rather than fabricated.

## Non-claims

- This change cannot force GitHub to run scheduled workflows, and does
  not provide a time-bound service-level guarantee.
- This does not guarantee native CodeQL success on the scheduler-change
  PR before merge, retroactively repair PR #387's missing app check,
  or make Scorecard `SASTID` 30/30.
- This does not authorize local score suppression, alert dismissal, unsafe
  fork tokens, or a privileged `pull_request_target` execution path.
- A clean Actions run, archive digest or trusted-main SHA cannot by
  itself authenticate all the independent per-head Code Scanning claims.

**Tracking:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380),
[#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
