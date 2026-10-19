# ADR 0061: Bound repository qualification to the sole human maintainer and verified automation

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

The owner explicitly stated that this repository is maintained only by
`@portyu9`. Accepted existing governance already declares a single human
CODEOWNER, zero independent mandatory approving reviews, and authoritative
CI/status gates. Dependabot is the sole specialized autonomous PR updater
with independently validated canonical bot identity, signed source and
owner-account approval. An earlier issue backlog accidentally elevated
external-fork PR qualification and independent non-author human approval
into acceptance requirements without owner authorization.

That drift kept SAST #380 and governance #360 open despite genuine
same-repository evidence. Dependabot #399 additionally tracked an observed
authentic signed bot merge #397, whose postmerge CI *failed* as GITHUB_TOKEN
suppressed push-triggered Security; accepted #409 dispatched ordered
Security → CodeQL → CI explicitly and #410 aligned bounded scanner
observation windows. All seven exact-main postmerge **push** workflows
passed after #410; a second post-repair signed bot workflow_dispatch
lifecycle has **not yet been independently observed**.

## Decision

The supported maintenance/qualification model is:
- human owner `@portyu9` issuing same-repository PRs through protected
  merge; authenticated GitHub Dependabot updates may proceed only under
  the existing exact-source, signed-bot, vendor-release and owner-account
  authorization controls;
- no external-maintainer contribution onboarding, external-fork E2E
  qualification, or independent human review quorum is mandated;
- no expansion to general untrusted bot, third-party automation, or
  self-declared owner-like credentials.

This is a **scope of assurances**, not a security exemption. Should any
unknown or fork-origin PR appear, its code remains untrusted; it cannot
inherit the trusted-main publisher credentials, change source identity,
skip premerge evidence, or be automatically qualified as approved.
GitHub may permit public fork PRs, but no fork-origin merge guarantee is
claimed. Do not disable safe read-only handling as a way of enforcing
this maintenance policy.

Encode the approved exact contribution-scope declaration in
`.github/repository-governance.json`, require it in the existing
`validate_governance_policy.py` main validation, and use adversarial
self-tests to reject scope expansion, accidental owner/bot removal, or
misleading fork/reviewer claims. Document supported onboarding in
`CONTRIBUTING.md` and `docs/REPOSITORY_GOVERNANCE.md`.

## Consequences

Issue closure is based on **completed owner-supported source paths**:
same-repository native CodeQL SAST/real unfiltered Scorecard, signed
Dependabot provenance and a genuine protected bot merge, owner-only
CI-authoritative governance, and durable postmerge remediation. A new
external fork or independent reviewer is not a future issue prerequisite.

The mandatory 13 protected status checks, separate authentic native
CodeQL check, Package integrity, original unmodified scanning and
release provenance, exact-head owner review for governed bot updates,
zero bypass actors, and fail-closed absence/failure distinctions are
unchanged. Only later explicit owner authorization can widen scope.

## Assurance impact

Prebranch lineage/salvage evidence and exact accepted blobs are recorded
in issue #360 comment 6278383994. Main before this decision was
`2479fd91a064925f7dec3e4bb6b5fa7f625e33e5`, one remote
`main` branch, zero open PRs, previously merged #397/#409/#410
accepted and #389 concurrency experiment superseded by #390.
No unmerged unique code was found.

## Non-claims

This policy is not live GitHub administration attestation, nor an
enforcement guarantee against someone submitting a public fork PR.
No actual external-fork PR, independent human review, or later second
signed-bot post-#410 Security→CodeQL→CI workflow_dispatch completion
is asserted. Signed bot history is not signing of all working commits.
Original OpenSSF Scorecard BranchProtectionID, CodeReviewID and
MaintainedID remain **real unsuppressed findings**; repository age
and the owner's voluntary single-human-review structure cannot
be presented as repaired security scanner failures. A future
platform/vendor outage is possible; tests and verified main-push runs
do not magically turn unobserved future bot runs into PASS.
