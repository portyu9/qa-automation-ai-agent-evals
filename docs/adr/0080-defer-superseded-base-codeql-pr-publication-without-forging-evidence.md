# ADR 0080: Defer superseded-base CodeQL PR publication without forging evidence

**Status:** Accepted
**Date:** 2026-11-09
**Supersedes:** The scheduler-level failure behavior in ADR 0078/ADR 0038 for a genuine open PR that is already known, at discovery time, to have an obsolete base. The exact-head, exact-current-base, origin, identity, zero-alert and preupload revalidation requirements are unchanged.

## Context

Accepted main advanced to `5e5649ac5d50c4c2405fb3d740da8ac6de035326` when governed native Dependabot stall recovery PR #438 merged. Pending signed Dependabot PR #437 retained older base `06621081e0f2e8442ae06a5f4dd7397f23063c05`, with unique `zizmorcore/zizmor-action` immutable pin at signed head `127ef3eb418f7c2149294d07fa3780111ae7f163`. An owner-authenticated `@dependabot rebase` was pending, and the original CodeQL results for the bot head were not reusable on the new accepted main.

The main-owned `Trusted CodeQL PR-head publication` workflow, triggered on every accepted-main push or independently verified CodeQL completion, correctly refused to publish the obsolete PR's result, but marked the *whole publisher run* failed with `base moved after candidate scan` (for example run 42666381844). This conflates an expected **ineligible source** with a failed **trusted publication operation** and creates red main workflows even when main CI, CodeQL and Security are green. A separate legitimate current-base PR may be publishable, and a stale peer must not starve it.

## Decision

At the start of `discover` in accepted main's trusted `verify_codeql_pr_publication.py`, independently re-read the canonical live `refs/heads/main` and validate its SHA and ref identity. When the workflow provides `TRUSTED_MAIN_SHA`, it must still exactly match this live current-main ref; a moved main is a fatal block.

Before admitting candidate PR heads into the CodeQL discovery set, inspect the canonical open PR inventory (not caller-supplied candidate content). For every same-repository PR returned by the `base=main` query, require a valid SHA and exact `base.ref=main`. If its `base.sha` **already differs** from the independently authenticated live main, classify it as **deferred, not publishable**. Emit an explicit diagnostic count and exclude that stale head from selection. When no current-base PR remains, return `has_target=false`, leave SARIF download/upload steps unexecuted, and let this main-owned workflow succeed as a no-work reconciliation run.

The distinction is intentional: a base **already stale at admission** cannot yield a valid current-base CodeQL publication and must wait for a native signed bot refresh. By contrast, if the accepted main changes after trusted-workflow source pinning, or the PR base/head changes **after initial admission** (during full original-run verification, artifact download or immediately before upload), retain the original hard refusal and a failing workflow. Do not invent, requalify, or publish evidence for a stale head. Only genuine current-base PRs can pass through the existing CodeQL provenance, trusted source-blob identity, signed bot action-pin policy, SARIF zero-alert validation, original run/artifact digest, native analysis inventory and postdownload lease checks.

## Consequences

Main-push publisher runs no longer become red solely because an outstanding bot PR needs a native rebase/recreate. Stale PRs remain unqualified, visible through the explicit `DEFERRED` log, and independently governed by exact-head CI/Security/CodeQL, native bot signature and owner review. Genuine other PRs can still receive CodeQL SARIF publication even while a stale Dependabot PR is open. The PR's own protected checks do not become green through a scheduler-level no-op.

A malformed candidate, forged main ref, stale trusted workflow source, unexpected branch, ambiguous publication subject, missing/contradictory CodeQL run or native check, and TOCTOU base movement **after admission** remain blocking. Current-base PRs with a terminal failed newer CodeQL analysis retain existing fail-closed behavior; older green reports cannot shadow them. A scheduled publisher may legitimately do no work; the following separate authenticated dependency-governance controller remains responsible for remediation and never uses the no-op publisher run as proof of a current bot head.

## Assurance impact

Before creating this lane, accepted main was `5e5649ac5d50c4c2405fb3d740da8ac6de035326` (#438, including ADR 0079). The live branch inventory contained exactly `main` and signed Dependabot PR #437 `dependabot/github_actions/routine-actions-401d4b32a3@127ef3eb418f7c2149294d07fa3780111ae7f163`. The bot branch's one unique immutable action pin is **must preserve**; historic merged governance #420, #421, #434, #435, and #438 are **already accepted**, older closed alternative branches are **superseded** or absent with no live must-salvage content. No bot branch is rewritten or replaced.

The trusted-source script blob before this lane was `0ccb890b8134c369933486bf95eb66dc38f7fbcd`; workflow blob `da60a7f67b84d3fda440855497d544f38890c449` is intentionally unchanged. Add self-tests proving (1) a sole genuine stale PR produces no upload, (2) a malformed base remains blocked, (3) a stale peer does not starve a separately qualified current-base head, and (4) movement between PR list and PR detail remains a hard block. Retain original adversarial source and artifact provenance tests and independently passing full CI, security, CodeQL, semantic ADR, package integrity, and postmerge main verification.

## Non-claims

A successful no-target publisher run does **not** assert that stale PR #437 is safe to merge, that it has fresh CodeQL evidence, or that its signed source was regenerated. It does not guarantee Dependabot availability or a fixed recovery time, remove any protected check, change the security event token permissions, or accept alternate scanner identities. It does not hide an authentic current-base CodeQL failure or authorize publishing without exact artifact and current-main evidence.
