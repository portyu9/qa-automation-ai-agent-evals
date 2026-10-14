# ADR 0011: Make the trusted lock child replaceable by native Dependabot rebases

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

ADR 0008 permits a strictly verified two-commit Dependabot pip chain: a GitHub-signed bot-only manifest update followed by a GitHub-signed trusted publisher commit that changes only the twelve generated SHA-256 dependency locks. That second commit is reproducible derived evidence, not independently authored source. Once a subsequent maintenance PR changes accepted main, GitHub Dependabot by default refuses to rebase its branches after additional commits are present. Native `@dependabot rebase` requests therefore leave the otherwise valid two-commit PR behind main, permanently blocking required exact-main admission. GitHub's documented opt-in is the exact commit message marker `[dependabot skip]`.

## Decision

Append `[dependabot skip]` as a distinct, exact final paragraph of the generated child commit message. The default-branch trusted publisher and the independent published-chain verifier share a single canonical message constructor bound to the exact verified signed bot source SHA. Its error handling rejects invalid subjects, removed or modified trailers, changed parentage, altered sources, unauthorized paths, unsigned commits and non-canonical chains. Regressions assert the trailer is present exactly once and that missing or altered messages fail closed.

Native Dependabot may now replace the *derived child* when rebasing the canonical manifest update; the read-only compiler and trusted publisher must reconstruct all required lock artifacts on the new signed bot source and base. No mutation of a bot source or lock graph is authorized by this ADR alone.

## Consequences

A future accepted-main governance change can trigger normal Dependabot rebasing rather than permanently stranding a bot PR that has a publisher child. A rebase discards previous generated artifacts from the branch; their previous immutable Git object identities remain auditable, while new pinned resolution must pass the entire compiler, publisher, provenance, CI, CodeQL and owner-gated merge cycle. The presence of the marker grants Dependabot permission to force-push on that branch under GitHub's policy, **not** to skip this repository's quality or governance checks.

## Assurance impact

The privilege separation in ADR 0008 remains: read-only resolver generates artifact data; accepted-main publisher verifies and writes a single derived child; owner-authorized branch update remains fast-forward-only; governor authenticates the two-commit chain and locks against the actual source manifest. The new exact message trailer is part of the signed provenance claim. No branch-force push by the publisher, arbitrary third commit, expanded file allowlist, waived hash, altered CodeQL gate, or synthetic CI evidence is authorized.

## Non-claims

This marker is not a Dependabot merge instruction, not an authorization for other bots or human branches, and not a guarantee that GitHub's hosted Dependabot service will promptly complete every native rebase. A successful rebase is not evidence that generated locks, SDK compatibility, artifact provenance or security checks have passed.
