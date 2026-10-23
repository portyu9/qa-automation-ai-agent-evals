# ADR 0065: Enforce lowercase native CI identity while signing canonical release evidence

**Status:** Accepted
**Date:** 2026-10-23
**Supersedes:** ADR 0063 for the final attestation re-verification boundary; previous decisions remain historically immutable.

## Context

The accepted name-boundary repair #414 and 84.2.1 security lock update merged
to main at `06a371152a05c117e93ce010f86b73015b76632b`. Its new exact-main push CI run 40039599343 passed
repository policy, quality, CI gate, Package integrity, retained qualification
and release-statement generation, but the final trusted attestation signing
job failed at `CI qualification evidence failed: expected workflow must be
exactly CI`. The signing step was still passing lowercase native
`GITHUB_WORKFLOW=ci` into the historical uppercase `CI` qualification and
release-statement validators. This was a forgotten consumer of the same
boundary and blocked genuinely reproduced signed provenance.

## Decision

Keep the public GitHub workflow name exactly `ci`; do not rename it or
relax old signed evidence schemas. Bind the final keyless attestation
re-verification step to exact native `GITHUB_WORKFLOW=ci`, and pass the
stable internal `CI` semantic identity solely into canonical retained CI
qualification and release-statement validators. Keep package manifest
and independent supply-chain identities tied to the native GitHub workflow
`$GITHUB_WORKFLOW`. Extend the existing runtime policy to require exactly
these four specific call-site identities; fail closed on missing or extra
aliases. Maintain OIDC permissions, SLSA signer, exact SHA/run/attempt, tag,
permissions and proof steps unchanged.

## Consequences

The final signing job can verify its own retained qualification and
release-statement bytes under their original stable semantic identity,
without rewriting them. Native workflow badges remain lowercase. No
unchecked artifact, untrusted token, stale commit, or failed CI evidence
becomes eligible for signing.

## Assurance impact

Lineage preflight: the only live branch at source was `main@06a371152a05c117e93ce010f86b73015b76632b`,
Git tree `2e5e38d19305e7e7877b333eb2909b260ab83a13`; the prior name/security PR #414 is protected-merged
and its branch is absent. No open PR, divergent historical source branch,
or unmerged unique capability exists in this repository. This is a
three-file, narrowly reviewed PR. The signing job is gated by successful
upstream CI, exact retention and supply-chain checks and produces
keyless provenance only on trusted exact `main` push. Required
post-merge proof: a fresh main run completing all signing jobs, not
merely a green PR run where signing is intentionally skipped.

## Non-claims

This does not resolve unrelated portfolio-generated publication,
Dependabot controller scheduling, or repository-wide GHAS alert inventory.
