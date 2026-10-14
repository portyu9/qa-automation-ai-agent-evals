# ADR 0015: Guard workflow write authority without weakening supply-chain evidence

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** None

## Context

The first successful authentic Scorecard SARIF export on `main`
(`fcabb60826dd43d95e66311d5cf3cb55e87a19a2`) exposed 30
repository-level security posture alerts. In particular, the retained GitHub
release publisher requested `contents: write` at workflow scope even though
only its trusted publication job needed that capability. Other highly
privileged trusted workflows legitimately publish verified artifacts or
reconcile Dependabot, while CodeQL and Scorecard upload authentic SARIF.

The active `Protect Main` ruleset has seven required CI contexts, zero
required approving reviewers, and no independently required `CodeQL` or
`security-gate` check. The Scorecard monitor runs on a weekly schedule,
manual dispatch, and accepted-main changes to its own workflow, not on
untrusted pull requests. Neither green CI nor a scanner-produced error
severity is proof that every alert is an exploitable vulnerability.

Preflight: accepted `main` `fcabb60826dd43d95e66311d5cf3cb55e87a19a2`;
only `main` existed, no open PRs or active divergent security branches.
Historical security PR #337 (merge `46dd529e930d2eac8f8e8bd0d0fe38cd003f41b5`),
SARIF repair #347 (`0c9b6c2b9c1c86662a8c1732bfbf46828ccbd267`),
and Scorecard verification #348 (`fcabb60826dd43d95e66311d5cf3cb55e87a19a2`)
are already accepted. Existing ADRs 0013 and 0014 remain intact. Relevant
upstream blob identities: `publish-release.yml`
`71e11f39cc952bf36ea86365eed8630422493605`;
`validate_workflow_graph.py` `2a42fdad4b5470844ac40dec5604a2af3c3cf903`;
`.github/SECURITY.md` `fc2f14532241735d09bba15ea5a5da258419d740`.
No unmerged unique capability requires salvage in this lane.

## Decision

1. Set the release publishing workflow's default token to `contents: read`,
   retain `actions: read`, and grant `contents: write` **only** to the
   default-branch-bound publication job. Update the existing runtime
   release contract to reject regression to workflow-wide writes.
2. Extend the previously required semantic workflow-graph policy to reject
   missing read-only defaults, broad workflow writes, unapproved job-scoped
   writes, dangerous untrusted triggers, and drift from exact accepted
   trust guards. Maintain a validator-owned, narrowly enumerated allowance
   for the current trusted release, lock, governance, provenance, and
   security-upload jobs. This is independent of what a workflow claims
   about its own trustworthiness.
3. Preserve read-only untrusted analysis paths and actual SHA-pinned
   third-party actions, locked dependency installation, CodeQL zero-alert
   interpretation, retained artifacts and explicit `BLOCKED` preconditions.
   Run negative policy self-tests in the existing required CI path.
4. Publish a precise Scorecard triage inventory and a private reporting
   contact route without claiming the 30 findings are automatically fixed.

## Consequences

Existing workflows with their accepted capability boundaries continue to
operate; the release publication job has the same specific needed write
permission with a less privileged workflow default. Future CI changes
that silently grant new broad write scopes fail policy validation.
Legitimate future privileged operations require an explicit allowlist
change, tests and compatible ADR before acceptance. This gate remains
subject to the trustworthiness of the checked code and repository
protection: independent human reviews and additional required checks
must be configured by an authorized GitHub administrator.

The dedicated CodeQL job currently skips external fork PRs; requiring it
globally in branch settings before implementing and verifying a safe
fork-capable read-only analysis path could deadlock forks. Review
and configure merge protection with that limitation explicit.

## Assurance impact

This change narrows the default `GITHUB_TOKEN` authority granted to the
retained release publisher and adds a fail-closed syntactic trust-boundary
regression guard. It does **not** change the authority of evaluated agents,
DSSE envelopes, receipts, release artifact checksums, witness integrity,
or semantic grading. Real security scans remain independent evidence
domains. No verifier accepts self-declared safety or a hash as authentication.

## Non-claims

This ADR does not certify zero vulnerabilities, eliminate every Scorecard
heuristic finding, prove any alert closed, produce retrospective SAST
coverage, or confer human review. It does not assert that a Scorecard run
is a required PR check, that a private report form is enabled, or that
GitHub's ruleset has already changed. Python Hypothesis fuzz tests must
not be removed merely because Scorecard's current detector does not
recognize them; nor may locally verified source/package installs be
replaced with unverified remote builds to improve a pinning score.
