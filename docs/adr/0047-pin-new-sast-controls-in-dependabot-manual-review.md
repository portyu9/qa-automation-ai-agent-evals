# ADR 0047: Pin accepted native SAST controls in Dependabot governance

**Status:** Accepted

## Context

PR #391 normally protected-merged onto `main@17f058d18b258e3dfdfcf8ebc14e0ee7ebb29c5c`.
All seven postmerge workflows completed green and the authentic, unfiltered
OpenSSF Scorecard SAST count recovered from 8/30 to 19/30. The new
ruleset-required Package integrity job enforces independently published
native GitHub Advanced Security CodeQL **success** and original, zero-alert
SARIF with distinct trusted publisher `analysis_key` and source-scanner
`category`. It never gives untrusted PR code a write-scoped token.

The separately trusted, scheduled Dependabot lifecycle intentionally
accepts a very narrow signed bot identity, current protected main,
verified signed original/lock-publisher chain, exact eligible action-pin
or Python dependency semantics, owner-token decision/veto, required
checks and protected merge. `.github/dependency-governance.json` carries
an explicit `manualReviewPaths` registry. That registry and its mandatory
validator were not expanded when the new SAST verifier and trusted
publisher were accepted. The `dependency-governance.yml` read-only PR
self-test path filter likewise did not include several newly accepted
security-control files. These are a **policy maintainability and future
drift gap**, not evidence that an unsigned actor could already merge:
current pure-pip vs strict one-for-one action-only semantic classification
already forbids non-workflow security-code edits.

The exact existing controller's action-pin-only workflow exception is
explicit and deliberately distinct: signed Dependabot may propose only a
one-for-one immutable pin + monotone version update in existing workflow
files, subject to the original policy checks. It is not authority for
arbitrary changes to a protected workflow.

## Decision

Make the accepted-main native SAST and governance security-critical
paths explicit as a common, immutable-in-contract registry in
`.github/scripts/dependency_governance.py` and the versioned
`.github/dependency-governance.json` manual-review registry, including:

- `.github/scripts/verify_native_pr_codeql.py` and
  `.github/scripts/verify_codeql_pr_publication.py`, distinct source and
  trusted publisher verification, and `.github/scripts/verify_required_codeql.py`;
- `.github/scripts/validate_workflow_graph.py` and
  `.github/scripts/validate_semantic_adr.py`, governance policy and
  `.github/semantic-adr-policy.json`;
- `.github/scripts/audit_live_repo_controls.py` and the security-related
  `codeql-pr-publisher.yml`, `security-scorecard.yml`, `security.yml`
  workflows.

The controller must reject any config that removes these paths. Its
existing adversarial offline self-test independently removes each one
and proves rejection, then proves each non-workflow control cannot be
treated as unprotected automatic-merge scope.

Every critical path must trigger the unprivileged `governance-self-test`
on a PR touching it. The exact workflow path triggers are checked against
the registry on trusted-main scheduled self-test. Expand compilation
and run existing provenance + native CodeQL adversarial tests on this
read-only PR job; never add a privileged PR event.

The accepted exact signing, bot source identity, eligible pure-action-pin
and pure-pip semantics, owner-review revocation, protected merge, and
all thirteen ruleset-required GitHub Actions checks remain unchanged.
No new bot authority, general automation or status is created.

## Consequences

Governance policy drift dropping a previously accepted critical
control is now refused before it can be accepted. PRs modifying critical
security controls execute the same read-only governance self-tests as
earlier dependency-governance edits. The existing action-pin-only
exception is still intentionally available for *genuinely signed,
canonical Dependabot* updates with exact one-for-one pin semantics;
non-action modifications to any control-plane workflow remain BLOCKED.
Extra PR self-checks cost time but do not bypass existing required CI.

## Assurance impact

A copied `manualReviewPaths` array cannot silently lose newly accepted
security-authority files without triggering the controller's fail-closed
contract test. The read-only PR self-test now covers both halves of
accepted native Code Scanning: the source CodeQL zero-alert evidence
and the separately authenticated accepted-main-only SARIF publication.
Authority separation, native PR-head premerge success, exact source SHA,
strict publisher analysis identity and the absent-is-BLOCKED distinction
remain noncompensatory.

## Non-claims

- This is preventive explicit trust-path coverage, not a demonstrated
  exploitable pre-existing bot auto-merge bypass.
- A signed, eligible Dependabot twelve-lock-profile and owner-token
  end-to-end merge is **not** created or proven by static fixtures;
  issue #360 retains that live acceptance requirement.
- An external-fork PR remains unqualified and intentionally BLOCKED
  by the existing native SAST merge gate; this ADR does not grant it
  trusted main-only publication authority.
- It does not add a second human reviewer, resolve age requirements,
  produce an OpenSSF Best Practices badge, or clear genuine
  Scorecard SASTID, BranchProtectionID, CodeReviewID or MaintainedID.
- No original SARIF or alert is filtered/dismissed; a hash is not
  authentication; unknown, conflicting, or unavailable security evidence
  never becomes PASS.
