# ADR 0074 — Retire merged PR #418 CodeQL publisher scanner grant

**Status:** Accepted for review, October 30, 2026.

## Context

The protected-main CodeQL PR-head publisher once allowed one exact, separately pre-certified scanner source update for owner PR #418. That authorization was intentionally narrow: old scanner Git blob `89d1eabbb866b16a43497df8aebc4610df35bec8`, replacement blob `f755168b966a9f5ded03351d7c2e09029fa72e6a`, and PR #418 owner identity. The source grant was introduced in merged PR #419.

PR #418 was merged on October 27, 2026, with merge commit `32d1e451e20c99e2ce1214f2567e4ff3aa4f6e7f`. A prior, independent retirement precedent exists in merged PR #406 for a different migration grant.

## Decision

Remove the PR #418 allowance, including the named special-case predicate and exact prior authorization constants. Require candidate source equality to accepted-main source for every ordinary CodeQL producer file. The existing independently verified, signed Dependabot workflow-pin exception remains unchanged; it does **not** authorize arbitrary producer script changes.

Retain adversarial checks proving that the exact historical scanner blob pair, formerly certified scanner code, and arbitrary source changes are now rejected. Continue to fail closed for incomplete, pending, or failed newest PR-head CodeQL runs; an earlier green run for the same head must not substitute. A later successful scheduled scan already establishes recovery and does not justify bypassing the provenance gate.

## Security and rollback

No new secret, actor authority, approval or merge path. The publisher still never executes untrusted PR source. Revert only through a newly reviewed PR with explicit immutable Git blob provenance if a future migration is legitimately required.
