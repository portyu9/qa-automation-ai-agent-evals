# ADR 0057: Retire temporary scanner source-blob migration approval

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** The one-time scanner source exception of ADR 0052 and ADR 0054

## Context

The accepted-main CodeQL publisher temporarily allowed one
independently preapproved exact scanner verifier source blob in an
untrusted pull request. This enabled the protected staged migration of
PR #401 / ADR 0053 to finish without self-asserted authority. That
migration has now **auto-merged through all thirteen required status
checks and authentic native CodeQL**, at accepted main commit
`104c72c04b91e5708aa7157e2e6047e688101b1b`. The approved scanner
source Git blob `89d1eabbb866b16a43497df8aebc4610df35bec8` is already
the normal accepted-main blob. Retaining an independent exception
would allow a future PR to downgrade an evolved main-owned validator
back to older bytes while claiming unchanged producer authority.

## Decision

Delete the runtime `APPROVED_SCANNER_MIGRATION_BLOB` constant and
remove the special scanner source equality exception. All executable
CodeQL producer inputs other than the separately authenticated
signed-bot immutable CodeQL workflow pin-only transition must now
match the **current trusted-main Git blob**, not a previously approved
static SHA. Retain exact base/head/merge tree and original SARIF
authentication, zero-alert veto, native CodeQL duplicate avoidance,
main-only privilege, vendor release tag dereference and verified commit
provenance.

Replace the obsolete self-test that expected preapproved script changes
to be accepted with negative cases: (1) a candidate reintroduces the
formerly approved scanner source after accepted main evolves;
(2) a candidate supplies arbitrary scanner code. Both must BLOCK.
The retained positive fixture continues requiring fully identical
executable source against trusted main.

## Consequences

Approval to migrate scanner code was one-time and is no longer an
ongoing capability. Genuine signed Dependabot action-pin upgrades can
still qualify through the independently accepted main-owned upstream
tag/commit signature, signed source and action-only scoped diff guard,
without candidate control over producer identity. If future scanner
script changes are truly necessary, they require a new separately
protected accepted-main decision rather than candidate self-trust.

## Assurance impact

A formerly approved Git blob is no longer an alternative authority.
Hashes remain identity/equality references, not authentication. Native
Code Scanning, security analysis and branch protections still require
independent success; FAIL/BLOCKED remain distinct and fail-closed.

## Non-claims

- No promise of zero future upstream API outages or unsafe vendor releases.
- No proof of bot end-to-end automation until actual signed bot #397
  passes all checks and uses configured owner-token governor.
- No privileged execution of candidate code or review/ruleset bypass.

## Evidence and lineage preflight

Accepted main `104c72c04b91e5708aa7157e2e6047e688101b1b` includes the unique scanner migration #401
and earlier protected #400/#402. Only open PRs are:
#397 canonical Dependabot action-only branch head
`3695bf549489a60bd590f3c70cb3ba3f480c98fc`,
#403 transient API retry head
`e9fbf7f4a6d4e81b31d77c39e44cebc5d46ef775`,
#405 per-file ADR grouping head
`17d06fcb9e3a0f9f1b8a8e160a508f790efd6da3`.
Each has separately preserved unique code/tests and a linked PR.
Original #389 was explicitly superseded by #390. No orphan branch,
duplicate scanner migration or unclassified divergent history exists.
Issue #404 tracks this exact removal, and #399 tracks bot live proof.
