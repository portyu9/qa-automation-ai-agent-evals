# ADR 0050: Monitor live Code Quality and branch-creation enforcement

**Status:** Accepted
- **Date:** 2026-10-16
- **Applies to:** read-only accepted-main `.github/scripts/audit_live_repo_controls.py`
- **Issues:** #360 and #349
- **Prior:** ADRs 0046–0049 (preserved append-only)

## Context

The independently queried protected `main` ruleset #22191532 requires thirteen
exact GitHub Actions-app contexts, plus a separately configured
`code_quality` rule with `severity: warnings`. Its required-status-check rule
also explicitly has `do_not_enforce_on_create: false`. The existing accepted
governance monitor pinning the thirteen status identities did **not** verify
either separate policy field, so either rule could be removed or weakened
without affecting `verified_rule_checks=PASS`.

## Decision

1. Require the observed `code_quality` rule and its `warnings` severity
   in the canonical read-only GitHub ruleset snapshot. The rule is separate
   from check-run contexts; never claim that having CodeQL/Security
   jobs substitutes for it.
2. Require explicit `do_not_enforce_on_create: false` in the required
   status-check rule; omission is not an implicit positive attestation.
3. Extend the audit self-test with five distinct adversarial mutations:
   creation exemption set to true, missing creation-exemption field,
   missing Code Quality rule, weaker severity and missing severity.
   Each must cause a deterministic failure even with thirteen valid checks.
4. Retain exact ruleset ID, strict fresh statuses, action issuer binding,
   branch-target selector, no bypass actors when visible, and the
   independent **BLOCKED** classification for inaccessible admin fields.

## Consequences

A live rule deletion or reduction in these two independent enforcement paths
will now cause the next governance audit to fail rather than silently
accept the remaining thirteen healthy check contexts. No new privilege,
workflow trigger or ruleset administrator write is needed. Existing
local semantic regressions and the postmerge push audit exercise the change.

## Assurance impact

This adds two independently observed protections to live drift detection
without changing their native GitHub enforcement. A positive read-only
`verified_rule_checks=PASS` is still limited to ruleset fields actually
provided by GitHub, and does **not** claim independent human approvals,
CodeQL vulnerability absence or complete external fork qualification.

## Non-claims

- Repository-owned code and its hashes do not replace the canonical live
  ruleset API, and admin-hidden fields remain **BLOCKED**, not PASS.
- This change does **not** enable human-independent Scorecard CodeReview
  scoring; intentional single-CODEOWNER/zero required approvals remain a
  genuine governance choice. Repository age still generates Maintained.
- No genuine untrusted external fork PR or first eligible signed Dependabot
  owner-token/12-lock lifecycle is manufactured by these tests.
- No alteration of live branch rules, no bypass, no alert suppression and no
  fake SAST check are authorized.

## Evidence

Preflight and lineage reconciliation: issue #360 comment 6223380961.
Live accepted baseline: `main@9176e6029661735db0c296721a4087c8b6abf2c8`,
audit blob `ea556e9b02d908137d73477f394cea8dfd0eeef5`.
Only native protected PR and authentic accepted-main results can establish
subsequent deployment; update issue checkpoints after those results exist.
