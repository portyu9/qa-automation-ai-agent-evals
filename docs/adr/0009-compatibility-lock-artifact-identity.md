# ADR 0009: Preserve compatibility artifact identity during autonomous lock refresh

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

ADR 0008 introduced isolated, hash-locked compatibility artifacts for authorized Dependabot pip changes. The established compatibility validator requires `Artifact-Selection: linux-x86_64`, but the new trusted lock generator did not emit that mandatory header. Therefore the read-only compiler matrix succeeded yet the accepted-main publisher rejected its output. Independently, publisher self-tests executed on a Dependabot source `pyproject.toml` that legitimately changed direct `mcp` and `openai-agents` pins while copied historical committed locks still describe accepted main. The test's positive case erroneously assumed the two different revisions were identical.

## Decision

Compatibility-boundary generated locks must carry the existing Linux x86-64 artifact-selection claim in their deterministic header. The existing compatibility validator retains exact profile, boundary, Python, artifact-selection, input-digest and hash checks without relaxing any field.

The publisher self-test's *historical committed-lock fixture only* derives its own source manifest's exact direct dependency pins from that committed lock set. The real publisher must continue to obtain the actual Dependabot source manifest from the GitHub-verified immutable source SHA and independently validate **all twelve freshly generated artifacts** against it before publishing. A regression test asserts that the canonical generated header contains the selection claim and that removing the claim is rejected.

## Consequences

A legitimate new dependency version no longer causes the historical-fixture self-test to fail for the unrelated version-change reason, and generated compatibility artifacts satisfy the previously accepted metadata contract. Version changes that cannot be resolved or verified under all twelve supported profiles still block publication. The required header is intentionally bound to this Linux compiler environment, not a platform-neutral claim.

## Assurance impact

No compiler choice, allowed profile, SHA-256 hash proof, immutable bot source identity, exact merge subject, approved owner credential, GITHUB_TOKEN permission, workflow-run authentication, trusted status, or post-merge requalification policy changes. Artifact payloads remain untrusted data; the publisher runs only accepted-main code and refuses missing or tampered header fields.

## Non-claims

This decision does not prove an upstream package is harmless, permit an unsigned Dependabot revision, waive CI or CodeQL, allow arbitrary `Artifact-Selection` values, or authorize dependency changes without the existing security and governance gates. Passing the fixture self-test is not proof that a newly generated dependency graph can resolve or install.
