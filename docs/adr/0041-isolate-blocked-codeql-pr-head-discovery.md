# ADR 0041: Isolate blocked CodeQL PR-head discovery without trusting stale green scans

**Status:** Proposed, pending protected CI and independent accepted-main publication qualification

## Context

ADRs 0030, 0038, 0039, and 0040 establish a read-only CodeQL producer on
`pull_request` (including forks), an immutable accepted-main-only publisher
with the narrowly scoped `security-events: write` token, verification of
the exact live same-repository PR/head, and source-run-bound original SARIF
with a non-compensatory zero-alert veto. A genuine native
`github-advanced-security` success was independently observed on both
post-retirement PRs #384 and #385, and Scorecard's real SAST coverage
improved to 13 of 30 recent commits. The original historic sample remains
an actual, unsuppressed Scorecard finding.

The trusted publisher enumerates GitHub's canonical newest-first CodeQL
`pull_request` producer runs to find one eligible exact live PR head.
Its prior implementation raised a global `Blocked` as soon as the first
live PR's newest run had failed, been cancelled, or remained pending. A
separate active PR with an independently successful producer and complete
authentic evidence later in the bounded inventory would never be examined.
This is a genuine liveness and evidence-availability problem, not permission
to make a failed run pass.

The security-critical nuance: simply skipping a failed run *without* remembering
its PR-head identity would fall through to an older successful scan for that
same head. That would violate the native SAST claim, and might misattribute
an obsolete or superseded analysis as current.

## Decision

Confine the handling of an incomplete/failed newest producer to its own exact
live `(head_sha, head_branch)` subject:

- Enumerate only the bounded GitHub-authenticated live same-repository PR
  heads and canonical current `CodeQL` workflow runs, newest-first.
- Record a live head as seen **before** inspecting its newest run's status.
  Any earlier successful run for the same head is thereafter ineligible.
  No duplicate or stale run may rehabilitate a blocked head.
- Fail closed on a mismatch in canonical workflow ID or event. A genuine
  newest run that is not both completed and successful remains explicitly
  **BLOCKED** and is logged as such, not marked PASS, FAIL or skipped as proof
  of successful source verification.
- Continue discovery for **other distinct live heads only**. Such a head must
  independently pass the existing complete accepted-main SHA, branch/ref,
  merge-tree, original scanner input byte identities, successful producer
  steps, artifact origin/digest, SARIF zero-alert and active-category
  preconditions. The publisher can publish only one fully qualified
  result in a given run, never an unqualified head.
- If no eligible unpublished head exists and any live head is blocked,
  propagate `Blocked` so the scheduled run cannot silently report a clean
  no-work success. The retry/liveness behavior is not a waiver.
- Keep global failures on untrusted/malformed API inventory, incomplete
  pagination, ambiguous native categories, mismatched existing analyses,
  and absent or non-successful native Code Scanning checks. These do not
  become self-declared trust by candidate isolation.

Add deterministic Fake-GitHub-API regressions for a failed peer before a
genuinely eligible head, a pending peer before that head, a newest failed run
with an older successful run for the **same** head, and a blocked peer when
all other heads have already been correctly published.

## Consequences

One bad or unfinished same-repository PR cannot starve a different verified
green PR merely by appearing earlier in CodeQL's global run list. For the
blocked PR, native Scorecard coverage is never fabricated; it must get a new
genuine completed-success scan and original SARIF. A run containing only
blocked and already-qualified heads returns an explicit BLOCKED result rather
than a false all-green no-op.

This is a bounded improvement in scheduler throughput, not a guarantee
that GitHub Actions schedules execute promptly, that multiple PRs finish in
one execution, or that external forks can receive privileged delegated
publication. The published source and GitHub API trust subjects remain
separate; a digest is integrity evidence, not an authentication grant.

The CodeQL producer workflow, untrusted fork token permissions, trusted
publisher job permissions, immutable checkout identity, active
`.github/workflows/codeql.yml:codeql-upload` category, original SARIF,
required security checks and protected main ruleset are unchanged. Fork
delegated publication remains deliberately **BLOCKED** absent a distinct
end-to-end qualification.

## Assurance impact

The trust gate remains non-compensatory **per exact PR head**. Blocking one
head does not authorize weaker evidence for any other; recognizing an
independently eligible head does not turn a failed run or incomplete CodeQL
coverage into PASS. Honest GitHub-native check attribution should become
more reliable when multiple live PR heads coexist.

## Non-claims

- This does **not** establish Code Scanning SAST history of 30/30, resolve
  `SASTID`/security alert #27, or revise authentic Scorecard SARIF.
- This does **not** prove the updated candidate verifier runs with accepted
  privileged authority before normal protected merge and accepted-main
  requalification. All 13 existing required checks remain prerequisites.
- This does **not** enable trusted publication for external forks, execute
  fork code with write authority, or use `pull_request_target` or
  `workflow_run` elevation.
- This does **not** make every scheduled publisher run a green report;
  blocked-only runs remain explicitly BLOCKED.
- This does **not** alter, rewrite or reclassify accepted ADRs 0030,
  0038, 0039 or 0040.

**Tracked by:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380)
and [#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
