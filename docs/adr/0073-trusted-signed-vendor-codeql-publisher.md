# ADR 0073: Authenticate complete signed Dependabot Action groups before privileged CodeQL PR publication

**Status:** Accepted
**Date:** 2026-10-28
**Scope:** Read-only admission proof for the already governed trusted CodeQL PR-head publication workflow. No workflow or token permission changes.

## Context

The original native signed Dependabot routine-actions PR #425 changes six official GitHub Action identities across 18 existing workflow files. Its first-attempt native CodeQL run 40620309991 completed successfully. The separate accepted-main authenticated SARIF publisher 40620485401 failed closed: the trusted publisher imported a governance parser that had incorrectly demanded a full semver advance for the preexisting major-only `# v7` annotation on `actions/setup-python`. The narrowly reviewed owner-source #426 merged that missing parser compatibility. Yet the trusted publication module `.github/scripts/verify_codeql_pr_publication.py` still recognizes only three official vendor families (artifact, CodeQL and Scorecard), and its added-line grammar cannot parse the frozen PyPI release-channel comment, so later authentic signed groups remain blocked even after #426.

## Decision

Retain original bot login AND numeric ID, canonical single signed GitHub Dependabot web-flow commit, exact PR head/base/ref and current accepted main, complete 18-file one-for-one workflow-pin diff, read-only token, exact first-attempt successful CodeQL run, immutable source retention, and official upstream tag SHA + signed commit verification before SARIF publication. Expand read-only official vendor GET paths **only** to:
- `actions/setup-python` official tagged releases;
- `zizmorcore/zizmor-action` official tagged releases;
- `pypa/gh-action-pypi-publish` official tagged releases, including annotated Git tag dereferencing.

No arbitrary owner/repository can be admitted. An exact frozen `# release/v1 YYYY-MM-DD` comment is permitted only on the isolated PyPI publisher; the independent accepted native governance validator requires that comment to remain literally unchanged and the action identity and pinned SHA to be exact. A single-component major compatibility comment such as `# v7` must match the major of the full canonical signed Dependabot dependency-version, while fully dotted annotations must match **exactly**, never be silently normalized. Every action in the signed bot diff, not just CodeQL producer lines, must resolve to the independently authenticated official upstream tag and verifiably signed immutable commit.

## Consequences

A legitimately signed multi-vendor native Dependabot group can reach the same independently verified PR-head CodeQL SARIF publication as a single-vendor group after native gates qualify, without bypassing failed scanners, authorizing untrusted PR edits, broadening upstream API URLs, or changing privileged publisher credentials. A wrong signer, moved tag, mismatched metadata, unreviewed action family, altered PyPI annotation, spoofed major or non-action edit must still fail before publication.

## Assurance impact

Embedded deterministic in-process publisher self-tests exercise a signed multi-vendor original bot commit, a same-major update with independently verified full release, signed zizmor and PyPI annotated tags, an unchanged fixed PyPI comment, plus adversarial moved official tags, unsigned upstream commit, changed publisher comment, mismatched signed version, false major labels and forbidden external URL paths. Existing source-signature, SARIF, zero-alert and GitHub event/first-attempt regressions remain mandatory. Every production check is required to pass on the exact protected source PR head before merge; new live accepted-main publication must be witnessed independently.

## Non-claims

This is neither an auto-merge command nor evidence that PR #425 has already rebased, achieved required CI and CodeQL, been owner-reviewed or merged. It does not expand write permissions, invent SARIF, ignore native scanner failures, change rulesets, or imply that upstream commits are safe simply because their release tags and commit signatures verify. The source PR must merge under the existing 13 required native checks and preserve the original signed Dependabot branch until GitHub itself provides a new head and the independent protected merger legitimately accepts it.

## Lineage

Fresh mandatory pre-branch salvage and exact immutable source identities are recorded in the authentic signed #425 discussion, comment 6459487444. Previous owner source #426 and #423/#424 already accepted. Source parent accepted protected `main@bfc4cb73f48623f346eeaea65c0d711e0e634ecc`, Git tree `d1a7e5fd589159b5e1ece96580d933a96b2b7220`; current publisher source `.github/scripts/verify_codeql_pr_publication.py@7ac91681d8f473f41c520fbbbc9530345a606b47`. Native source #425 `f55ca6a978f746b9ddb369e1a6acf8ebbf5baacb` is must-preserve despite new main diverging; historical signed #417/#422 are bot-superseded.
