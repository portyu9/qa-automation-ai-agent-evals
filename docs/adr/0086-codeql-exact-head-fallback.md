# ADR 0086: Recover current PR CodeQL source from bounded exact-head discovery

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** The trusted CodeQL publisher's assertion that exhausting three unfiltered 100-run workflow pages is necessarily a terminal source-evidence failure. It does not supersede any CodeQL qualification, author/signer, exact-head, security, or merge authorization policy.

## Context

The trusted main-owned PR-head CodeQL publisher must authenticate a canonical read-only source scan before it can publish the original exact-head SARIF. Its existing discovery searches up to 300 globally ordered CodeQL workflow runs and chooses the newest run for each live PR head. On November 16, 2026, a fresh Dependabot PR head was created by the trusted lock publisher shortly before its own new CodeQL scan was registered. The completed [publisher run 43949885997](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/43949885997) returned `CodeQL workflow run inventory exceeds bounded 300-run lookback` even though no registered CodeQL scan for that new head could yet be published. The bot's independent exact-head CodeQL run subsequently registered and succeeded.

The existing distinction from ADR 0085 between a queued producer run and a *completed failing* producer run remains correct. A freshly published PR head can additionally have **no producer run registered yet**, which a historical 300-result lookback cannot distinguish from an overfull unrelated workflow feed. The GitHub REST workflow-run listing supports the canonical `head_sha` parameter to restrict results to a single immutable source commit.

## Decision

Keep the existing main-owned, bounded global discovery and its newest-first `seen_heads` ordering. Only after the third full historical page, for still-unseen live PR heads, perform at most 20 additional read-only queries to GitHub's established CodeQL workflow listing using **the exact SHA-40 head** from the authenticated canonical PR inventory. No user-supplied run ID or mutable source branch is accepted as a query target; validate head and branch syntax before constructing an API path. The endpoint, workflow ID, event, page size, and query structure are fixed and URL-safe.

Validate each filtered response as a bounded, typed workflow-run listing (canonical SHA matching, valid result count, at most 100 first-page rows). Prefer the newest returned record matching the canonical PR branch. Feed it into exactly the **same** source-run identity, completed-status, original SARIF, CodeQL-native category, exact-base/head and post-download checks already used by the historical path, before any privileged publication. The newly authenticated head is processed before older global page-three observations, and `seen_heads` prohibits substituting an earlier green run for a newer pending or failed scan.

If the exact filtered inventory has **no matching registered run**, record `DEFERRED`, return no SARIF target, and rely on the already-existing authenticated CodeQL-completed and periodic workflow wake. This is not a passing scan or permission to merge. A completed unsuccessful source, malformed filtered response, changed head, contradictory CodeQL check, invalid authorization, or excess outstanding targets continues to produce a hard `BLOCKED` outcome.

Add self-tests saturating all three historical pages while exercising an exact-head authenticated success, latest pending source shadowing an older success, absent/not-yet-registered source deferral, and wrong SHA, malformed result count, malformed row and completed failed-run negatives. The mandatory CI policy job already executes the publisher's full self-test, so this contract is exercised on every PR before the trusted implementation may reach `main`.

## Consequences

Fresh PR heads no longer make the trusted publisher fail solely because unrelated historical CodeQL runs fill the lookback or because GitHub has not registered their first source scan yet. Registered exact-head scans can be authenticated by a bounded, direct lookup instead of requiring broad search pagination to happen to contain them.

The fallback is deliberately read-only and conditional. It does not add an action secret, increase GitHub API write permissions, fabricate native checks, upload SARIF on a deferred head, replay any mutation, or bypass dependency review. A GitHub Actions API outage, malformed response, contradictory scan, wrong signer or a genuinely failed completed run remains fail-closed. The separate CodeQL required check continues to prevent merging a PR with no completed successful analysis.

## Assurance impact

The change is confined to discovery liveness and evidence retrieval order. The trusted PR's SHA, head branch, CodeQL workflow identity, current accepted base, signed source and lock provenance, original scan artifacts, native analysis identity and preupload revalidation remain mandatory. The main-owned workflow still runs only trusted source with nonprivileged PR content treated as data. This ADR is append-only, and CI/CodeQL/Security/required checks remain prerequisites for merging the implementation.

## Non-claims

- A deferred or absent CodeQL source scan is not an approved, passing, or uploaded CodeQL analysis.
- The fallback does not permit arbitrary historical run selection, invented artifacts, unbounded pagination, external origin calls, or mutation retries.
- A valid SHA-filtered response does not by itself authorize upload; the entire existing provenance and native Code Scanning verification still applies.
- This does not resolve missing live provider credentials (issue #447) or native Dependabot refresh outages in other repositories.
