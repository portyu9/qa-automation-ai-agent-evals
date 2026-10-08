# ADR 0006: Scheduled CI binds to post-merge CodeQL evidence

**Status:** Accepted
**Date:** 2026-10-08
**Supersedes:** None

## Context

The protected `Package integrity` gate introduced by the accepted #284 lineage requires a successful
CodeQL workflow run for the exact subject SHA and branch before aggregate CI is accepted. The merge
governance established by #283 separately guarantees post-merge registration of exact-main CI and
CodeQL qualification using `push` or an explicit `workflow_dispatch`.

CI also runs on a Thursday schedule (`13 4 * * 4`). Scheduled run 37769150728 evaluated main
`46dd529e930d2eac8f8e8bd0d0fe38cd003f41b5`: every aggregate CI job succeeded, but the protected
gate failed before evidence selection because `verify_required_codeql.py` did not recognize
`schedule` as a CI trigger.

Merely treating a CodeQL `schedule` run as interchangeable evidence would be unsafe and brittle.
CodeQL has its own independent Monday schedule. On an unchanged main SHA, the repository can therefore
have both the accepted post-merge CodeQL run and a later scheduled CodeQL run. The verifier deliberately
fails closed when more than one eligible exact-subject run exists. Broadly admitting scheduled CodeQL
evidence would make quiet-week CI ambiguous, and it could also allow a later periodic scan to substitute
for missing post-merge qualification.

## Decision

Recognize `schedule` as a valid CI trigger, but bind that trigger to the same post-merge CodeQL
evidence classes used by governed main requalification: `push` and `workflow_dispatch` only.

Scheduled CodeQL runs remain independent security evidence and are intentionally not candidates for
the protected CI bridge. Pull-request CodeQL runs also remain ineligible for scheduled main CI.
The verifier continues to require the exact workflow name and path, exact SHA, exact branch, valid run
identity and attempt, terminal success, and a single unambiguous eligible run.

Extend the verifier self-test so scheduled CI accepts exact-subject `push` and
`workflow_dispatch` evidence, rejects `pull_request` and `schedule` evidence, rejects unknown CI
triggers, and preserves fail-closed ambiguity when multiple eligible post-merge runs exist.

## Consequences

The weekly CI schedule can reuse the exact-main CodeQL qualification already required after merge
instead of depending on the unrelated CodeQL cron day. No additional workflow dispatch, token
permission, or mutable state is introduced.

If exact-subject post-merge CodeQL evidence is absent, non-successful, malformed, or ambiguous, the
scheduled protected gate still fails. A later CodeQL schedule does not heal missing post-merge
qualification. Manual duplicate post-merge qualification can still create ambiguity and is
intentionally fail-closed rather than resolved by timestamp preference.

## Assurance impact

This decision repairs trigger coverage without broadening the evidence authority accepted by the
protected gate. Exact-subject identity, workflow identity, branch identity, terminal-success
requirements, bounded API retries, and ambiguity rejection remain unchanged.

The independent CodeQL scheduled workflow still runs and retains its own SARIF evidence, but its cron
execution is not promoted into merge or protected-CI authority. The change therefore preserves the
accepted separation between post-merge qualification and periodic security scanning.

## Non-claims

This ADR does not claim that a green scheduled CI run proves absence of vulnerabilities or defects.
It does not make scheduled CodeQL evidence equivalent to post-merge qualification, relax the zero-alert
CodeQL policy, authorize branch-protection bypass, or change merge/release authority. It also does not
guarantee that manually creating multiple eligible post-merge CodeQL runs will pass; ambiguity remains
an explicit fail-closed condition.
