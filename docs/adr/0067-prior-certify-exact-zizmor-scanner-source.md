# ADR 0067: Prior-authorize exact owner scanner source before protected migration

**Status:** Accepted
**Date:** 2026-10-27
**Supersedes:** Temporarily extends ADR 0057 for the exact frozen source of PR #418; the original source-equality requirement remains the default.

## Context

The read-only CodeQL scanner executes checked-out PR validation source. The
trusted main-owned CodeQL publisher must never accept an arbitrary candidate's
modifications to executable scanner authority, even when the candidate itself
passes native CI. The accepted publisher correctly rejected scanner repair
PR #418 with `PR alters CodeQL producer authority; publisher BLOCKED:
.github/scripts/validate_security_stack.py`. This stopped real CodeQL
PR-head publication, so a protected Package integrity check failed on #418.

ADR 0052–0054 introduced a separate accepted-main exact-blob approval
before scanner changes in PR #401; ADR 0057 deliberately revoked it after
the certified scanner source had merged. A newly discovered obsolete
zizmor-action SHA literal in the current scanner inventory requires the
same staged, explicit, temporary authorization. A generic exemption,
candidate-owned approval or waiver of source provenance is unacceptable.

## Decision

Independently certify the exact frozen, Ruff-corrected scanner validator
Git blob `f755168b966a9f5ded03351d7c2e09029fa72e6a` from already
open owner PR #418. This blob has the strict action-identity and complete
scanner flag contract with eight adversarial source mutations; accepted
trusted source remains Git blob `89d1eabbb866b16a43497df8aebc4610df35bec8`.

Before accepting any PR-head SARIF, the **trusted-main-only** publisher
must still verify the full native PR identity, current exact base/head/tree,
real successful read-only CodeQL scan and source step/results/artifact.
In addition to its normal exact-main producer source equality, permit
precisely this one reviewed script blob transition **only** on PR number
418, originally authored by user `portyu9`, user ID `35150859`.
Reject any other PR, untrusted actor/ID, noncanonical PR number, other
producer path, different accepted-main script or other candidate blob.
This preapproval is fixed in separately merged trusted publisher source;
the untrusted PR cannot assert or change its own authorization.

After this certificate PR itself passes genuine required checks and
merges through ordinary protections, reconcile the existing PR #418
with accepted main; do not create duplicate scanner implementation.
The exact new scanner source must still pass all real CI, Security,
CodeQL PR-head publication, package integrity, governance and owner
requirements before a normal protected merge. Then retire this exception
with another separately protected source-only PR, not by reverting or
weakening the validated scanner.

## Consequences

The certificate cannot promote an arbitrary 40-hex candidate source,
fake a CodeQL analysis, waive security, or approve a bot's workflow
release from candidate-controlled policy. It adds a single explicit
temporary source equality tuple and adversarial rejection fixtures.
After PR #418 is accepted, leaving the tuple forever would permit
rollback if trusted scanner source evolves; follow-up revocation is
therefore required.

## Assurance impact

Exact accepted main before branching:
`3eb8ee21a447c5c0bb89db8403a45e8e7001ac60` tree
`384be37dd327378ed299992800b78e41bad38b30`;
trusted publisher source blob `c5016c0e5efe7909ef3587c48b4a616db78babb7`.
Open #418 at `736fe405a9c270f0f9edc39585716ff590632d3a`
has unique, **must preserve** validated scanner blob
`f755168b966a9f5ded03351d7c2e09029fa72e6a` plus
ADR 0066. Open signed Dependabot #417 at
`a03140e930cc0c124e2ea6501e62a6fa037d510f`
retains four distinct **must preserve** workflow updates; its branch
is never modified by this authorization. Historical merged #416
has no unmerged unique capability. This separately scoped PR edits
only the trusted publisher verifier and this append-only ADR.
It does not change protected workflow triggers, permissions,
tokens, rulesets, review/merge authority or immutable SARIF checks.

## Non-claims

Certification of the exact scanner script is not a claim of a zero
CodeQL alert count, successful native CodeQL publication, complete
dependabot automation, or that GHAS administrator-only alert APIs
are available. Protected native CI remains mandatory and verifiable.
