# ADR 0039: Bind privileged CodeQL PR-head publication to its immutable accepted-main workflow subject

**Status:** Accepted

## Context

ADR 0038 introduced a read-only PR CodeQL producer and a separately privileged
main-owned schedule/dispatch publisher. At the accepted implementation
`main@c06089b33e14ece802ea3e66658c11a79b6fa4f5`, its publisher job
checked out `ref: main` while the workflow was selected by an immutable
`github.sha`. These are not synonymous under concurrency: `main` can move
between workflow selection, runner allocation, producer evidence discovery and
publication. Code located on a newer accepted main cannot silently inherit the
authority of a run admitted at a different trusted source revision.

Independent live GitHub evidence after merging PR #382 showed that Scorecard
still assigned SASTID 7/10, with zero of thirty prior PR-head check-runs
recognised as successful CodeQL application checks. The merged publisher
requires qualification on a new actual same-repo PR head, not a synthetic or
retrospective claim. The native Code Scanning *merge rule* was removed in an
explicit owner-governed bootstrap, leaving thirteen required GitHub Actions
checks and zero bypass actors. That change is not equivalent native protection.

## Decision

Supersede the mutable checkout aspect of ADR 0038 without weakening its
source, SARIF, or privilege restrictions:

- The trusted scheduled workflow checks out exactly the immutable
  `${{ github.sha }}` under `trusted/`, with credentials not persisted. It
  never checks out PR head code under privileged authority.
- Pass `TRUSTED_MAIN_SHA=${{ github.sha }}` from the GitHub workflow
  context. The trusted verifier rejects any missing, malformed or mismatched
  live `refs/heads/main` SHA before choosing a CodeQL run. The canonical
  producer revalidation additionally binds the exact same live main SHA to the
  workflow subject. The scheduled task may be conservatively BLOCKED when main
  changes; it must not continue on an unverified new trusted version.
- Pin both immutable inputs in semantic workflow policy; adversarial fixtures
  mutate the checkout to `main`, mutate the workflow-SHA input to an untrusted
  ref, and move the GitHub main ref between evidence checks.
- Keep existing Python and GitHub Actions source scanner files, zero-alert veto,
  original SARIF, exact artifact digest provenance, no fork delegated
  publication, no `pull_request_target`, and no PR-executed code with
  `security-events: write`.

## Consequences

A superseded queued scheduler run may fail closed even though a different
run on the latest accepted main could qualify. The next accepted-main schedule
can recover once it verifies its own trusted source and the current PR.
This is intentional; availability cannot overrule authority. Schedule
timeliness remains outside repository guarantees.

The new PR providing this hardening also supplies an authentic same-repository
PR-head CodeQL subject for separate end-to-end publisher and SAST qualification.
The job must be independently confirmed to have published a successful native
Code Scanning application check, not merely a successful Actions CodeQL job.

## Assurance impact

The trusted executable source identity is now cryptographically named by the
Git commit in the authenticated GitHub workflow context and bound to the
current GitHub main ref. GitHub evidence authentication derives from the
runner/API trust context; comparing hashes is **not by itself authentication**.
The SHA check is a fail-closed admission precondition, not blanket trust in
PR content, external data, or future main commits.

## Non-claims

This decision does not independently verify external fork PR publication, does
not restore the removed native GitHub Code Scanning merge rule, does not imply
GitHub scheduling service-level timing, and does not repair historical SAST
0/30 counts. It does not claim that a neutral CodeQL check meets Scorecard
SASTID or that #27 is fixed until real native app attribution and a subsequent
unfiltered genuine Scorecard scan prove it. All thirteen accepted protected
CI requirements and zero bypass actors remain mandatory.
