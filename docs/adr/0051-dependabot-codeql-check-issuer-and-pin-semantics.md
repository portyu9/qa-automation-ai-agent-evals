# ADR 0051: Authenticate distinct CodeQL check issuers in Dependabot governance

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Accepted-main Dependabot governance was tested against live signed bot PRs #396 and #397. The
read-only PR CodeQL job successfully qualified #396 and the trusted main-only SARIF
publisher produced a second, authentic native Code Scanning check for the same exact
head. Both checks have the visible name `CodeQL`, but only the GitHub Actions app
(ID 15368) is an existing ruleset-required status. The later genuine native
Code Scanning app (ID 57789) unintentionally shadowed that required Actions
check in the controller's name-only index. All mandatory checks passed, yet
the controller refused to review or merge the qualified dependency change.

Dependabot #397 also changes immutable workflow action commit pins in two existing
workflows whose `uses:` lines do not carry optional version comments. The
existing action-only semantic validator mistakenly demanded a `# v...` suffix,
blocking valid SHA-only pin updates even while retaining valid signed bot provenance.

The accepted CI/Security/CodeQL/native-PR-head vetoes, protected branch rules,
release evidence, and owner review requirements must remain authoritative.
Prior concurrency experimentation in PR #389 was explicitly reverted by PR
#390 and is **not** revived here.

## Decision

1. During GitHub Actions required-check qualification, ignore only a
   **genuine exact-head native CodeQL check** whose issuer has both the
   canonical GitHub Advanced Security app ID 57789 and slug
   `github-advanced-security`. Keep the separate GitHub Actions `CodeQL`
   job bound to app ID 15368. A foreign same-name app remains a veto;
   no check can manufacture a substitute required Actions result.
2. Permit one-for-one, signed Dependabot pinned action SHA replacements when
   both old and new workflow `uses:` lines omit version comments. Preserve
   immutable full-SHA syntax, changed SHA, equal action identities, signed bot
   provenance, same-repository head, exact base/head/merge tree binding, and
   the prohibition on all non-action semantic changes.
3. Require consistent version annotation presence across each old/new pair.
   When `# v...` annotations are present on both sides, retain the strict
   monotonically increasing semantic-version requirement.
4. Add adversarial self-tests for a real native CodeQL collision, spoofed
   native-app identity, valid SHA-only changes, and inconsistent version
   annotations. The native CodeQL publication veto remains independently
   mandatory in the existing ruleset-required `Package integrity` gate.

## Consequences

Correctly qualified bot PRs can advance without a human detecting an
unrelated newer Code Scanning check or adding documentation comments to
previously unannotated action pins. Other app identities continue to be
blocked, and omitted version comments reduce the amount of semver evidence
available for those particular pins; they do **not** constitute proof that
a semantic version increased. Automated action changes remain limited to
pinned one-for-one replacements and all other existing policy preconditions.

The repository's scheduled trusted publisher can still be delayed, and
other validators can still reject action pin changes that alter their own
trusted source contracts. This decision does not resolve those independent
operational issues or authorize relaxing them.

## Assurance impact

This repairs the join between two authenticated and distinct check issuers,
without inventing evidence or promoting native Code Scanning into an Actions
status. Live exact-head completion and authenticated issuer metadata remain
required; any missing, failed, stale, spoofed, or contradictory mandatory
evidence remains **BLOCKED**. The self-tests must pass in PR CI, followed by
protected ordinary workflow checks and native CodeQL qualification. Accepted
historical replay semantics and existing evidence schema are unchanged.

## Non-claims

- This is not proof of independence between the owner identity and an
  owner-scoped automation token.
- A hash is an immutable object identifier, not authentication of a source
  or author; signed Dependabot identity and authority preconditions remain
  separate.
- A green CI result alone is not authentic native CodeQL PR-head publication.
- No code-scanning alert suppression, branch-protection bypass, fabricated
  attestation, altered review veto, or automatic approval of arbitrary
  workflow edits is authorized.
- This decision does not assert all bot PRs merge automatically or that
  scheduled GitHub Actions are punctual.

## Evidence

The live controller run `39257383613` (attempt 2) reported the issuer
collision and the SHA-only action false rejection. The exact source commit
for this ADR is PR #398, originally `ba624362bcc44ac31a19a4ff8bcf7a905fb0c92d`;
its original changed governance blob was
`ccc1d0c2fa78f8fd7cf1e980d4274fe1333c7194`, replaced by
`787ce19e555f8de30511e12553bc147ddca933fb`.
The correctly gated recovery of bot PR #396 merged at
`d66447defee72f019e5510c8e65ca7521b59e147`.
PR #397 remains subject to every independent validator and qualified
security-evidence precondition.