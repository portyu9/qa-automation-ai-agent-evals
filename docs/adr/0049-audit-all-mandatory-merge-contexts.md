# ADR 0049: Audit all thirteen mandatory GitHub Actions merge contexts

**Status:** Accepted
- **Date:** 2026-10-16
- **Applies to:** `.github/scripts/audit_live_repo_controls.py`
- **Issue:** #360 (with #349 security umbrella)
- **Prior accepted decisions:** ADRs 0023–0024, 0046–0048; no amendment to accepted ADRs

## Context

The accepted protected `main` live ruleset #22191532 now requires **thirteen**
GitHub Actions-app contexts (integration ID 15368), but the independent read-only
governance drift auditor still checked only its original seven contexts. Therefore
the loss, or issuer substitution, of any of six newer required gates could leave
the auditor's `verified_rule_checks=PASS`. The report also inaccurately stated
that CodeQL and Security were required only indirectly by Package integrity.
The actual ruleset was read independently from GitHub; this file is not
its authority.

## Decision

1. Pin the complete currently observed set of **thirteen** mandatory check names
   and their exact GitHub Actions integration ID 15368 in the read-only drift
   auditor. Preserve the original seven and add `CodeQL`, `Security scanners`,
   `security-gate`, `Repository policy`,
   `Actions security / actionlint + zizmor`, and `ci-gate`.
2. Detect deletion or integration substitution for **each** mandatory context,
   not merely one representative fixture. Reject duplicates, malformed bindings,
   relaxed strict-check freshness, and loss of the existing PR and deletion protections.
3. Describe CodeQL/Security status enforcement as **direct required GitHub Actions
   contexts**, while leaving separate genuine native `github-advanced-security`
   CodeQL evidence to the independently protected exact-head SAST bridge.
4. Preserve all administrator-unobservable settings as **BLOCKED**, distinct
   from observable PASS and demonstrated FAIL. Keep current zero-bypass
   and single-CODEOWNER CI-authoritative policy unchanged.

## Consequences

The next genuine accepted-main governance audit fails closed if any of the
thirteen required contexts disappears or is rebound to a different app,
even when the remaining twelve are healthy. The extra self-test fixtures
execute locally in the same read-only scheduled or push workflow; no
write privilege or additional PR workflow authority is introduced. Additional
new controls beyond this accepted thirteen-context baseline can still be
proposed separately, and must be authenticated before pinning.

## Assurance impact

Closes the drift-auditor's six-context **coverage gap only**. The positive claim
is the correctness of an authenticated read-only ruleset snapshot's 13
mandatory GitHub Actions context identities, subject to API field observability.
This is not a replacement for independent premerge qualification or for the
native CodeQL application's original same-head checks.

## Non-claims

- This does **not** turn source-controlled policy into administrator
  attestation; absent administrator-only fields remain **BLOCKED**.
- It does **not** establish a real untrusted external-fork PR, token-downgrade
  exercise, signed Dependabot owner-token autonomous lifecycle, or independent
  human reviewer.
- It does **not** alter live GitHub settings, close #349/#360/#380, dismiss
  Scorecard findings, or claim that current branch-protection and CodeReview
  alerts are resolved. Repository age and maintenance history remain genuine.
- Hashes and status checks alone are not identity authentication without their
  independently read issuing app and exact subject.

## Evidence

Preflight and historical-branch salvage: issue #360, comment 6223226051.
The live 13-context snapshot was read independently from ruleset #22191532
on accepted `main@7882b40f18a13e6c82ba8092af83daa077d565fa`.
Record PR final-head CI, actual native CodeQL, protected merge, and accepted-main
live governance postmerge run separately *after* observing their real outcomes.
