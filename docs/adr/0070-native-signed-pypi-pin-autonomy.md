# ADR 0070: Preserve isolated PyPI publishing while admitting signed Dependabot revision upgrades

**Status:** Accepted
**Date:** 2026-10-28

## Context

The canonical protected `validate_runtime_policy.py` embedded an obsolete literal SHA for `pypa/gh-action-pypi-publish`, even though the repository supports GitHub-native signed Dependabot action-only updates. Dependabot #422 introduced an authentic fifth action update to the isolated OIDC PyPI publisher, `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` → `7245906fb61fa33a13554f9d5fb856fe61758086`. The full native CI run correctly failed `Repository policy` before any release. Replacing a hardcoded hash with a broader unconditional allowlist would remove the publisher's exact-action trust boundary, so the accepted design must bind the semantics of the privileged publishing step.

## Decision

Continue enforcing immutable **40-character Git revision pins for every workflow action** and the publish-pypi workflow's sole OIDC privilege, isolated final publish job, no checkout, no secret/token exfiltration, verification dependency, exact artifact consumption, approved package count, and fixed verified-dist sources. Bind the PyPI publishing action to the **single named final step**, exact `pypa/gh-action-pypi-publish` identity, immutable commit revision and reviewed `release/v1` channel. Require exactly one instance in the entire publish-pypi workflow. Intentionally permit the bot-maintained 40-hex *revision* to advance under its separate verified, signed one-for-one diff and protected reviews/checks; reject a floating ref, different action identity, duplicate publisher, wrong step location and major release-channel drift. Retain all existing workflow/attestation policies.

## Consequences

An updated bot-signed, action-pin-only PyPI publisher can pass source-level runtime policy without a new human PR to certify each release's SHA. This validation does **not** itself grant publication rights or establish that an arbitrary pin is trustworthy; the native GitHub signed Dependabot source, protected current-main merge, dedicated authenticated owner review, required CI, security and CodeQL remain separate prerequisites. A human-authored workflow/security/validation semantic change continues to require an append-only ADR.

## Assurance impact

The existing repository policy test workspace now proves a changed immutable revision is permitted **only in the reviewed publisher step**, while mutations to floating refs, duplicate actions, foreign action identity, wrong step name, and release/v2 are rejected. The separately signed Dependabot one-for-one workflow-patch parser also recognizes only the exact PyPI publisher `# release/v1 YYYY-MM-DD` comment and rejects changed dates, removed annotations, foreign actions, and use outside the dedicated PyPI workflow; other Actions retain version-advance enforcement. Existing auth boundaries and negative tests stay active. Signed bot #422 is preserved and never manually rewritten.

## Non-claims

No claim is made that a new bot PR has passed, is mergeable, was auto-merged, or that a PyPI package was published. The signed Dependabot PR must independently revalidate on accepted main, and autonomous end-to-end completion is only established by an actual observed protected bot PR merge with first-attempt required checks.
