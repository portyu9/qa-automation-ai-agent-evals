# ADR 0008: Governed autonomous lock repair for signed pip updates

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

This repository intentionally executes CI from committed SHA-256-locked Python dependency profiles, including all four supported core interpreters and independent minimum/latest compatibility evidence. Dependabot changes only `pyproject.toml`, so an otherwise legitimate update of exact MCP or OpenAI SDK versions deterministically fails CI when the historical locks do not match. The existing transient failure recovery retries bounded network or runner failures but cannot solve this required deterministic lock renewal.

The existing single-commit signed Dependabot source policy, owner-authenticated approval, exact-head CI and CodeQL checks, and reviewed dependency-lock generator remain foundational. Python Pytest already has a two-commit trusted lock-publisher design in its own repository; this decision adapts the narrow idea without altering the semantic meaning of this repository's locks.

## Decision

A separate read-only `dependency-locks` matrix generates exactly the 12 repository-owned lock profiles for Python 3.11–3.14 using the pinned `pip==25.3` and `pip-tools==7.5.2` maintenance compiler and emits isolated short-lived artifacts. It has no mutation token or secrets. The privileged `dependency-lock-publisher` runs only accepted default-branch code after a successful, uniquely bound matrix workflow.

The publisher revalidates the exact GitHub-signed Dependabot source, unchanged accepted main, precise one-file dependency-only manifest diff and workflow-run provenance. It accepts exactly the known profile file set, rejects symlinks, unexpected files, invalid UTF-8, missing compiler/hash headers, drifted versions or graph contracts, and executes both existing snapshot and compatibility validators against isolated data before constructing a single derived-lock-only commit directly parented on the verified source. It never executes artifact code. An authenticated repository-owner token advances the existing Dependabot branch without force, so GitHub starts fresh exact-head CI on the new bot head.

The governor may accept this exact canonical two-commit chain only after independently proving the original signed bot commit, GitHub-signed trusted-publisher author/committer and message, exact parent relationship, immutable source manifest, derived-only diff and all 12 exact current-head lock bytes through the same existing validators. The entire chain remains subject to the original owner approval, CI, CodeQL, merge-parent and post-merge requalification rules. No other two-commit PR shape gains autonomy.

## Consequences

Signed bot PRs that cannot yet satisfy lock integrity can now regenerate the required graph without manual developer edits. The matrix deliberately costs more CI execution because it validates all interpreter and compatibility boundaries, not only the directly updated package. An unavailable package, unsatisfiable compatibility floor, invalid generated graph, stale base, missing owner credential, failed output, unknown publisher, or changed source must fail closed. The publisher cannot bypass a failing compatibility claim by weakening a hash or required check.

The child publisher commit introduces a provenance shape that must be revalidated during both assessment and immediate pre-merge checks. Previously accepted single-commit action update governance remains unchanged. Future changes to the publisher workflows, validators, source parser and test code themselves remain manual-review protected.

## Assurance impact

The trust transition is explicitly separated: untrusted PR-derived dependency resolution creates evidence without privileges; accepted-main code consumes it strictly as data; GitHub commit-signing and the configured owner identity control the atomic branch update; CI and CodeQL then qualify the exact new HEAD. No existing score thresholds, CodeQL zero-finding policy, audit checks, hash matching, minimum/latest contracts, or post-merge controls are loosened.

Negative regressions guard malformed artifact inventories, wrong direct versions, symlinks, bad publisher identity/signature, changed commit parents and unrelated privileged paths. CI must prove this implementation before it becomes authoritative on main.

## Non-claims

This decision does not authorize arbitrary AI-generated code changes, changes to workflow or runtime trust policy by Dependabot, silent dependency vulnerability waivers, unreviewed build hooks, weakened CSP, or merging on a failed required check. A successful resolver run is not publisher authentication, malware proof, package provenance proof or permission to bypass compatibility checks. It also does not guarantee that every upstream dependency change can resolve on every supported interpreter.
