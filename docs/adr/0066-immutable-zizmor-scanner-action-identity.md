# ADR 0066: Bind zizmor scanner coverage to immutable action identity rather than a historical SHA

**Status:** Accepted
**Date:** 2026-10-27
**Supersedes:** Only the single-SHA scanner-presence assumption in accepted security-stack inventory; prior scanner-governance ADRs and source remain authoritative.

## Context

Native Dependabot PR #417 upgrades the zizmor action from the immutable v0.6.4
commit to the immutable v0.7.1 commit without changing the pinned zizmor CLI
version or the scanner's policy and execution flags. Its candidate Repository
policy gate rejected this source as if the mandatory zizmor step had been
removed: `CI workflow is missing mandatory zizmor scanner contract`. The
existing scanner inventory conflates step presence with one historical GitHub
Action SHA. It therefore breaks precisely when legitimate Dependabot updates
the verified action pin. This also blocks the independent CI, Security and
CodeQL required check graph.

## Decision

Require exactly one literal `zizmorcore/zizmor-action` invocation in the
named Actions security job with a complete, lowercase 40-hex immutable Git
revision and semver release annotation. Preserve the exact pinned CLI version,
disabled online audits, advanced-security setting, annotations, persona,
minimum severity and confidence without widening permissions or triggers.
Evaluate the full step, rather than matching one obsolete release's Git SHA.

The separate trusted canonical Dependabot governance must still establish
original signed bot identity, one-for-one immutable action pin substitutions,
upstream release identity, exact current-main ancestry, owner veto and actual
native first-attempt required checks before protected merge. A 40-hex
candidate without that independent provenance is **not** thereby approved.
Run fail-closed adversarial mutations of the scanner source at every scanner
inventory verification: a mutable or short ref, alternate action owner,
missing or duplicate invocation, removed release annotation, network audit
mode or weakened scanner severity all remain rejected.

## Consequences

Future authentic semver releases of the same SHA-pinned scanner wrapper do
not appear absent solely because the accepted main inventory still contains
an earlier release's SHA. The existing CLI scanner configuration and all
GitHub permission boundaries remain unchanged. Native Dependabot PR #417
must receive a separate genuine rebase on accepted main and fresh qualified
checks; no previous failed run is retroactively converted to a pass.

## Assurance impact

Pre-branch lineage: accepted protected `main@3eb8ee21a447c5c0bb89db8403a45e8e7001ac60`
and tree `384be37dd327378ed299992800b78e41bad38b30`;
legacy scanner validator blob `89d1eabbb866b16a43497df8aebc4610df35bec8`.
Bot PR #417 `a03140e930cc0c124e2ea6501e62a6fa037d510f`
holds four unique workflow release-pin changes: **must preserve**.
Closed/merged bot #416 has `ahead=0` and no unmerged unique code.
This change touches only the scanner-inventory validator and this
append-only ADR. It introduces no privileged GitHub workflow, extra token,
security waiver, release trust shortcut or direct update to Dependabot's head.
The protected CI checks must still pass on the actual final head before merge.

## Non-claims

This ADR does not claim #417 is ready to merge, that all code-scanning
vulnerabilities are zero, that an arbitrary SHA is a legitimate release, or
that the repository's GitHub App access can enumerate sensitive GHAS alerts.
