# ADR 0063: Bind native lowercase CI and security names to immutable evidence contracts

**Status:** Accepted
**Date:** 2026-10-23
**Supersedes:** ADR 0062 for downstream workflow name consumers; the approved display-name decision remains in force.

## Context

ADR 0062 changed the two top-level native GitHub Actions display names to `ci` and
`security` for consistent first-party status badges. The first accepted-main `ci`
push run 40006508246 passed all core tests, but failed its exact retained CI
qualification job: `workflow must be exactly CI`. The historical evidence schema
uses `CI` as a stable internal qualifier, while the job had been passing native
`GITHUB_WORKFLOW` as the evidence label. Additional exact native workflow-name
consumers in Dependabot recovery, governance and release-candidate selection
were still checking the old names.

## Decision

Preserve `ci` and `security` as the literal native workflow names and URLs;
retain `CI` as the historical release-statement and CI-qualification **evidence**
identity, not an alias accepted by the evidence validator. Both retained
qualification and release-statement creation/verification steps explicitly
require runtime `GITHUB_WORKFLOW == ci` before passing the hard-bound internal
`CI` evidence identity. The reviewed runtime policy statically requires that
separation. Package manifest and independent supply-chain evidence continue to
bind the native `GITHUB_WORKFLOW` value. GitHub API selectors and governed
Dependabot recovery/configuration use exact current native names `ci` and
`security`, including the AI QA upstream name. CodeQL remains unchanged.

## Consequences

Protected CI can retain valid canonical qualification/release evidence on exact
`main` pushes without weakening its stable schema or rejecting the new badge
labels. Native release selection no longer rejects legitimate lowercase `ci`
runs. Existing evidence from prior CI runs retains the same schema and semantic
qualifier; no backdating or rewriting of released attestations is authorized.

## Assurance impact

The accepted baseline is `main@c9e4af94ec3e15fdae8f860d948e252d88e1e82f`
with tree `f5e2f64f7263ed2278e66fd433cd8944028a8e49` and previously accepted
ADR 0062 blob `6fb3b6e2214f9d9f64d5ee482fea0b6008316223`.
No open PR or divergent unmerged branches existed before the fix. This ADR
is append-only; ADR 0062 is restored byte-for-byte. Protected CI, CodeQL,
security, governed dependency checks, release receipt and required branch
restrictions remain mandatory. A green PR run does not substitute for a full
accepted-main push run of release retention, attestation and signing.

## Non-claims

This fixes native-name and evidence-label conflation, not a missing upstream
artifact, flaky scheduling, unrelated security finding, or a bypass to protected
merge. GitHub status badges still reflect live native workflow results.
