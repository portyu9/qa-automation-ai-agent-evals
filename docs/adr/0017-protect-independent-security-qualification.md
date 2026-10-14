# ADR 0017: Protect independent Security qualification at the exact subject

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** None

## Context

The active `Protect Main` ruleset requires the `Package integrity` status
but does not directly require the independent `security-gate` status.
The accepted `Package integrity` job already requires a successful
exact-subject `CodeQL` run through its separate Actions-API verification
bridge. The independent `Security` workflow runs Bandit and pip-audit on
PRs and accepted `main`, and publishes `security-gate`, but that second
workflow could fail without its own run being explicitly authenticated by
the ruleset-bound aggregation. Both required Python Quality jobs also run
Bandit and pip-audit, but scanner independence remains useful defense in
depth rather than redundant permission.

The immediate historical lineage is already accepted: #284 introduced the
ruleset-bound aggregate CI/CodeQL check, #338 hardened scheduled CodeQL
evidence, #337 added dedicated Security evidence, #350 introduced workflow
permission constraints, and #351 extended authentic Scorecard monitoring
to every accepted main revision. Current exact accepted `main` at branch
creation was `6c7f4ca14b57493e0422d2c94ec9004f52ab8b93`; only
`main` existed, with no open PRs or divergent security branches.
Source blobs: verifier `53e50865db6e92baa192f8a77678c1022f7016f3`,
CI `b1509ac76c1abb9e888c93b92102e82f5afb790c`, runtime
policy `f77bc830f58af96f886c96b4c4567afdb18053ca`, scanner
inventory `6af2015423b1683513625eb779d8a9e0abe5b46d`.
All previous contracts are classified **already accepted**; there is no
unmerged unique capability to salvage in this lane.

## Decision

Extend the trusted, already-required `Package integrity` post-aggregate
job to require an independent successful `Security` workflow run bound to
the **same canonical PR head SHA, head branch, event class, accepted
workflow name and immutable workflow file path** used by the CodeQL
verification design. This check is additional, not a substitute for the
existing CodeQL requirement.

The verifier owns the precise mapping of `Security` to
`.github/workflows/security.yml`, not a caller-provided arbitrary
workflow identity. A completed successful workflow run must also have
exactly one completed-success `Security scanners` job and one
completed-success `security-gate` job from the same run ID and
attempt. Missing, duplicated, ambiguous, skipped, cancelled, wrong-subject,
wrong-event, or failed evidence is not success. Read only via the GitHub
Actions API; keep PR job permissions least-privileged.

Bind the invocation to the executable runtime and scanner policies and
self-test authentic match/reject cases. Retain existing `ci-gate` and
`Package integrity` names because they are ruleset authority.

## Consequences

A PR whose independent dedicated Security workflow fails or has not
produced complete exact-subject evidence can no longer pass the existing
ruleset-bound aggregate package check, even if another build/lint job is
green. There is bounded wait for asynchronous status propagation and
failure-closed behavior when the API cannot establish the required
preconditions. This incurs additional Actions API reads but requires no
repository setting change or write-scoped PR token. GitHub administrators
may add direct `security-gate` requirements later only after verifying
compatibility with all supported PR sources.

## Assurance impact

This is a verifier-owned cross-workflow evidence-binding contract; it
does not let untrusted evaluated agents or submitted PR code authoritatively
claim security. It preserves separate CodeQL, source/dependency scanner,
Scorecard posture-monitor, deterministic agent-grading, and release
provenance domains. Neither positive CodeQL nor positive Bandit converts
unknown Scorecard findings into proof of universal security.

## Non-claims

This ADR does not assert that the ruleset directly requires Security,
that every future security vulnerability is detectable, that an external
second human reviewed any PR, that a scheduled Scorecard finding itself
blocks merges, or that repository-level/age-dependent Scorecard alerts
were resolved. A reported `BLOCKED` prerequisite remains uncertainty
and is not silently treated as a successful verification.
