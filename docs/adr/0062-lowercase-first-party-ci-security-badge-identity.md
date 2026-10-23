# ADR 0062: Use lowercase first-party workflow display identities for portfolio status badges

**Status:** Accepted
**Date:** 2026-10-23
**Supersedes:** None

## Context

The portfolio's Selected Engineering Systems cards must display consistent lowercase
`ci` and `security` labels using GitHub's native Actions workflow badges.
Native `badge.svg` uses the workflow's top-level `name:`; it cannot override
that visual text independently of the workflow definition. This repository
previously used top-level `CI` and `Security`, so its two statuses appeared
capitalized even when sibling engineering repositories had already adopted
lowercase names. Replacing native status badges with a third-party rendering
service is not the approved target.

## Decision

Change *only* the top-level `name:` in `.github/workflows/ci.yml` from
`CI` to `ci`, and in `.github/workflows/security.yml` from `Security`
to `security`. The canonical workflow file paths, trigger/event inventory,
jobs, permissions, implementation, branch-bound native status URLs and
protected required status-check contexts remain untouched.

Workflow **display names** are deliberately not reclassified as evidence
identity. Existing CI/Security evaluations remain run-specific, exact-subject,
fail-closed, and independently verifiable. Consumers should match a workflow
by canonical file path and exact commit/run identity, not by an untrusted label.
Where a webhook or guarded workflow_run dispatcher explicitly matches a
workflow's human-readable name, it must be updated and tested in the same
controlled change; this repository has no such dispatch change in scope.

## Consequences

GitHub first-party `/actions/workflows/ci.yml/badge.svg?branch=main` and
`security.yml/badge.svg?branch=main` will render lowercase text after the
protected change lands and GitHub recognizes the new workflow definitions.
No status conclusion is rewritten, no stale result is treated as passing, and
no artifact is published by this naming-only update.

## Assurance impact

The latest accepted `main` before the lane branch was
`e5a828ea66a7ad6905c2b897c402d2b8ec1f38ff`; the two accepted workflow
blob identities were `baa9a0958efe17f52c649bea63a5af639600cb7b`
and `d9c8dd104fc90ab78d1f8b2ccb39ab3f7fa9d958`. The repository had
no open PR and no unmerged named sibling branch. The changed workflow
blob identities are reviewed as part of PR #413. Exact CI/security checks
and this append-only ADR gate remain mandatory for merge.

## Non-claims

Changing case does not repair a failing CI/Security check, guarantee that a
scheduled workflow executes on time, or provide evidence that a workflow result
is trustworthy. First-party badges are presentation only; the portfolio's
attested evidence ledger remains its separate validation authority.
