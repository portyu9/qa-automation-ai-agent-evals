# ADR 0083: Bound transient GitHub GET recovery without replaying privileged mutations

**Status:** Accepted
**Date:** 2026-11-10
**Supersedes:** The single-attempt behavior for transient authenticated GitHub API GET responses in the trusted dependency-governance client. It does not supersede any protected merge, CodeQL, Security, owner identity, dependency-review, or exact-subject qualification policy.

## Context

The trusted dependency-governance controller authenticates GitHub API reads to establish the exact repository, owner identity, PR head, status checks, and post-merge evidence. Its `GitHubApi._urlopen` previously attempted each request once and raised `GovernanceError` on any HTTP error. A transient upstream GitHub 500, 502, 503, or 504 during an idempotent GET could terminate an otherwise valid autonomous reconciliation before it could form any authorization or qualification decision. The existing strict error, path, token, response-byte and JSON contracts should not be weakened to resolve this availability defect.

Review/merge and workflow-dispatch endpoints have non-idempotent or externally committed effects. A caller cannot infer from an HTTP 500 that an attempted mutation was rolled back. Retrying a write risks duplicate owner review, workflow dispatch or merge transactions. HTTP 401/403 or 429 indicates an authentication, permission or rate-limit decision, not evidence of safe transient server failure.

## Decision

For the existing path-restricted, authenticated GitHub API client, apply bounded retry **only** when the HTTP method is exactly `GET` and the GitHub response status is one of **500, 502, 503, or 504**. Make at most three total attempts, with deterministic 0.25-second and 0.50-second delays between attempts. If the final attempt also fails, raise the existing `GovernanceError`; do not turn the failure into an approval or synthetic status.

Treat HTTP 4xx (including 401, 403, 404 and 429), transport exceptions, invalid JSON and oversized responses as fail-closed, single-attempt failures. Do **not** replay POST, PATCH or PUT even on server-side 5xx. Retain URL allowlisting to canonical repository paths or the exact authenticated-user endpoint, the explicit token parameter for owner-specific calls, bounded 4096-byte error sampling, and the existing bounded success response-size limit. Do not alter signed Dependabot provenance, immutable owner identity, exact-head lease, premerge CI, CodeQL, Security, release and post-merge gate conditions.

The executable governance `selftest` uses the actual GitHub API client with mocked upstream responses. It exercises all retryable status classes, three-attempt exhaustion and backoff, explicit owner-token header continuity, 4xx non-retry, POST/PATCH/PUT non-replay and oversize response rejection. Successful PR CI and required Security and CodeQL checks are independent acceptance evidence, not consequences inferred from this ADR.

## Consequences

A brief GitHub server response failure on an authenticated read can recover without reopening or modifying a signed bot branch. Persistently unavailable GitHub responses still block autonomous reconciliation after a deterministic, bounded delay. Mutations retain their single-shot safety profile and the existing post-merge repair logic remains responsible for separately reconciling already-committed merges; the retry layer does not invent or replay those transactions.

This ADR adds no dependency or workflow permission and requires no repository configuration change. It may increase one affected read's elapsed time by up to 0.75 seconds of scheduled retry delay plus the existing per-attempt network timeouts. The controller's existing fail-closed error handling remains authoritative.

## Assurance impact

The change is confined to the transport availability behavior of the trusted governance read path. The affected trust domains are exact owner authentication, signed Dependabot PR eligibility, Security/CodeQL/CI evidence and protected post-merge reconciliation. Mandatory new append-only ADR validation, actual controller self-tests, first-attempt final-head CI, Security, CodeQL, and accepted-main requalification are required before claiming full completion. Any failed required gate remains a hard blocker.

## Non-claims

- This ADR does not assert that HTTP 500 is always transient or that a successful retry establishes PR eligibility.
- It does not authorize retrying non-idempotent review, merge, approval, dispatch or other writes.
- It does not treat HTTP 403/404/429 as retryable or claim that GitHub-native Dependency Review returned HTTP 200.
- It does not resolve the separate native dependency-comparison administrative/authorization prerequisite tracked by issue #440.
- It does not override CodeQL, Security, package-integrity, required CI, owner veto or release provenance gates.
