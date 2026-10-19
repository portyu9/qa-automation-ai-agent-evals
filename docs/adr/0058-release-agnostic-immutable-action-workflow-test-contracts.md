# ADR 0058: Make immutable workflow action tests release-agnostic, not issuer-agnostic

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Live canonical signed Dependabot PR #397 refreshed itself from current
accepted main using the configured owner-authenticated governance flow.
The head commit `756717037dc1f19b63cea611013325a6888dcb5c`
is the single GitHub-verified signature from Dependabot user ID
49699333, with 13 workflow files changed only by immutable one-for-one
official pinned-action updates and base main
`b3d4166598b8ca58bbecc3540e73c7f4c7a589e5`.
Its CodeQL and Security workflows succeeded. CI nevertheless failed on
`tests/unit/test_deep_mutation_policy.py` and
`tests/unit/test_live_provider_workflow_policy.py`: both tests
hard-coded the previous `actions/upload-artifact` release's exact SHA,
rejecting every legitimate version advance forever. This is the
same structural pin-rot defect already corrected in protected workflow
validators and scanner-policy code (PR #400/#401/#405).

## Decision

For the narrowly controlled Deep mutation and Live provider canary
workflows, require the complete canonical approved action **identity
set** (checkout, setup-python, upload-artifact), exactly the existing
number of action invocations, and lowercase 40-character Git commit
SHAs in every `uses:` reference. Drop release-specific historical
40-hex constants from these *test* expectations. Do **not** relax any
workflow triggers, permissions, exact-subject checkout, cost/timeout
limits, artifact guarantees, PR path scope or release non-authority.

Add independent negative fixtures for mutable tag refs, mutable branch
refs, uppercase/invalid SHA text, foreign action issuer replacement,
and an additional unauthorized action step. The test helper checks
issuer, scope, count and immutable commit ref together rather than
treating a hash as authentication.

The trusted main-owned signed-bot action-pin verification separately
requires canonical Dependabot author and signature, full one-for-one
workflow diff, official upstream tag identity for the CodeQL producer
updates, verified upstream commit target, authentic original SARIF and
native exact-head CodeQL. GitHub branch protections still require all
thirteen authenticated Actions checks and Package integrity.

## Consequences

Future approved releases of an action with the same canonical identity
and full Git SHA do not require manually editing a brittle *test*
expectation just because the commit changed. Suspicious mutable refs,
foreign actions, missing or extra action steps are refused, and
independent governance still binds the source and update provenance.
Any broader new action ecosystem still needs explicit new governance
authorization where the privileged producer is affected.

## Assurance impact

This is not a blanket version-update bypass. All noncompensatory safety
gates and the trusted-main source authority remain. Commit SHA denotes
immutable equality, never publisher authentication or intrinsic code
safety. A previously reviewed vendor release is not a guarantee against
upstream compromise.

## Non-claims

- Tests enforce observable workflow action identity/immutability, not
  universal authentication of every third-party package or action.
- Native CodeQL and signed bot verification are separate independent
  prerequisites, not substitutable with passing tests.
- An unavailable provider, scheduler delay, failed upstream API or
  unobserved admin-only setting remains BLOCKED/FAIL as appropriate.

## Evidence and lineage

Base accepted main `b3d4166598b8ca58bbecc3540e73c7f4c7a589e5`; only remaining divergent branch is canonical
signed Dependabot #397 at `756717037dc1f19b63cea611013325a6888dcb5c`,
which must be preserved untouched (not edited, rebased manually or
abandoned). All previous repair #400/#401/#402/#403/#405/#406
branches were accepted/cleaned; #389 was explicitly reverted by #390.
Live failing CI job IDs `118196557341` and `118196557340` show
exact historical SHA test assertions against the canonical bot update.
Issue #399 tracks the complete autonomous end-to-end acceptance.
