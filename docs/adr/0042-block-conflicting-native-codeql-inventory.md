# ADR 0042: Block conflicting native CodeQL inventory rather than reupload original SARIF

**Status:** Accepted

## Context

The accepted-main trusted CodeQL publisher is a privileged consumer of
original read-only PR CodeQL evidence. It authenticates the exact live
same-repository PR head, source workflow, immutable script inputs,
producer job steps and original evidence artifact digest, then independently
revalidates original two-file zero-alert SARIF before submitting to the active
`.github/workflows/codeql.yml:codeql-upload` category. Its token may write
Code Scanning reports but never executes PR-origin code with write authority.

A production anomaly was independently observed: trusted scheduled run
[38848732252](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38848732252)
at 04:04 UTC and scheduled run
[38877431090](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38877431090)
at 09:00 UTC on October 16, 2026 both authenticated and uploaded the
**same** original CodeQL evidence artifact `12016922945`, digest
`sha256:71e509e51f797c5db801e964ba569ef5366a0c0af828402f735a83e3a004e5eb`,
to exact `refs/pull/386/head`, exact commit
`6a65af3d5c1208bf4d358a2801c37f9e3029046f`, same active category,
with GitHub acknowledging processing completion each time.
A genuine native `github-advanced-security` CodeQL check concluded SUCCESS
on this head. Duplicate publication is not proof that the original source
scan was invalid; the exact cause of the GitHub analysis-list discrepancy
cannot be independently examined through the currently available connector.

The existing verifier fetched native GitHub check-runs **only when** the
bounded Code Scanning exact-ref analysis list already contained the exact
active category. When the native app check existed but that category was
missing from the returned inventory, the verifier selected the same verified
source run for another SARIF upload. Repeating privileged side effects to
paper over contradictory control-plane evidence is not a safe resolution.

## Decision

For each independently authenticated eligible PR head, the trusted publisher
must always read the bounded, exact-SHA GitHub native CodeQL app check-run
inventory, even when no matching active-category Code Scanning analysis was
returned:

- Require a complete, well-formed native check-run response.
- Count only exact SHA, name `CodeQL`, and app slug
  `github-advanced-security` or `github-code-scanning`. An ordinary GitHub
  Actions job named CodeQL is not native-app evidence.
- Reject ambiguous multiple native checks.
- When a matching active-category analysis exists, keep requiring empty
  warning/error strings and a **single completed successful native app check**.
  NEUTRAL, FAILED, SKIPPED, or missing remains BLOCKED, not PASS.
- When a matching active-category analysis does **not** exist, an already
  present native CodeQL app check of any conclusion signals a contradictory
  inventory. **BLOCK**, emitting an actionable reconciliation reason.
  Do not mark PASS, silently suppress or rewrite analyses, or resubmit SARIF.
- When neither an active-category analysis nor a genuine native CodeQL check
  exists, allow the original fully authenticated first publication.
- Preserve accepted-main SHA, current head/merge tree, original source/run
  job, verified artifact and zero-alert SARIF controls; no new authority is
  obtained from checksums alone.

Deterministic fake-GitHub-API self-tests exercise initial authenticated
publication, already-published native SUCCESS, same SHA wrong category
and native SUCCESS, no active-category inventory and native SUCCESS or
NEUTRAL, and a same-named GitHub Actions (non-native) check. Previous
negative fixtures continue to require that warnings and neutral native
results cannot be recast as success.

## Consequences

If the Code Scanning list endpoint omits an already published active-category
analysis even after GitHub has produced a native CodeQL check, scheduled
publisher runs may explicitly **BLOCK** until the owner reconciles the
backend's exact-ref analysis inventory. This is intentional rather than
spamming repeated authenticated uploads or hiding a possible category split.
The reason is observable in failed scheduled-run logs.

A failed scheduled publisher is not itself a failed PR code scan; the
untrusted PR producer's read-only zero-alert gate remains separate. A native
CodeQL app check is not an authentication substitute for matching active
analysis metadata or original immutable SARIF. We do not broaden delegated
publication to forks, turn BLOCKED into PASS, or restore any unqualified native
premerge rule.

## Assurance impact

This change narrows privileged write-side behavior when two authenticated
control-plane observations disagree. Existing successful native app checks
cannot compensate for absent exact-category analysis metadata; the state is
explicitly BLOCKED rather than PASS or a repeated publication. A first
publication remains possible only after the original source evidence passes
the complete fail-closed zero-alert and provenance gates. Any diagnostic
BLOCKED event should trigger owner investigation of the independent GitHub
Code Scanning API, not a bypass or a forged green check.

## Non-claims

- No claim that the upstream Code Scanning analysis-list discrepancy has
  been resolved, that a second upload was malicious, or that its record
  was necessarily absent. Current connector cannot read private analysis
  inventory to diagnose that root cause.
- No claim that a missing-category native SUCCESS is proof the accepted
  uploader's specific category already succeeded. It is a conflict to
  reconcile, not self-declared trust.
- No change to scanner, main-only publisher workflow triggers/permissions,
  original-SARIF requirement, live Protect Main 13 checks, or the accepted
  historical ADRs 0038–0041.
- No retroactive 30/30 SAST history, manual dismissal of Scorecard alert #27,
  or simulated fork PR/independent human reviewer.

**Tracking:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380),
[#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
