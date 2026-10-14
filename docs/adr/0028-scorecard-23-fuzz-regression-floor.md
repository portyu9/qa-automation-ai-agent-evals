# ADR 0028: Preserve authentically resolved native Fuzzing as a fail-closed Scorecard regression

**Status:** Accepted; post-merge independent rescan required.

## Context

The earlier ADR 0026 accepted the 24-finding vector from `main@23f5ffa9b1f9ee461bc37c8b2f0d481e5bc02335`, including one `FuzzingID`. It deliberately used per-rule **upper bounds**, not risk acceptance. Subsequently, PR #367 added a **genuine Atheris 3.1.0 coverage-guided libFuzzer campaign**, not a decorative import, with exact subject/seed binding and 5,000 executed inputs; it merged at `973f8ee5167a7d66c4b884de8f356da21d8d67ed`. PR #368 recorded its accepted-main SARIF evidence and merged at `ac0680f130e5ce17fd85de587d95b8728347ba4e`.

At `main@ac0680f130e5ce17fd85de587d95b8728347ba4e`, an independent real [OpenSSF Scorecard run 38653297427](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38653297427) / job 116157024809 succeeded and reported **23 actual findings**: eighteen `PinnedDependenciesID` plus one each `BranchProtectionID`, `CodeReviewID`, `SASTID`, `MaintainedID` and `CIIBestPracticesID`; `FuzzingID` is absent. An independently supplied GitHub Code Scanning GET export for the same exact main SHA lists **23 open alerts**, none with `FuzzingID` (alert #28 absent). A previous baseline upper bound of one `FuzzingID` could permit this genuine improvement to regress silently.

A new lineage-and-salvage preflight in issue #349 comment `6180806064` confirmed this exact main, only `main` branch, zero open PRs, all historical overlapping security work already accepted and no divergent, unmerged capability to salvage. Preserve the existing SARIF upload, read-only scanner evidence permissions, exact commit attestations and all other genuine 23 findings. Relevant original accepted classifier blob: `8669df7eeb3c91aa553580eb04f90061aae78b00`.

## Decision

Advance the **maximum** authentic Scorecard SARIF finding vector to the 23-finding `main@ac0680f130e5ce17fd85de587d95b8728347ba4e` baseline and explicitly set **`FuzzingID: 0`**. Retain the rule in the scanner-rule inventory so that a future reappearance is checked, not ignored. Extend fail-closed self-tests to reject one reappearing Fuzzing finding in a single SARIF run and one inserted into a separate run while the primary run remains valid. Test that the classifier is bound to the audited baseline SHA, that the accepted 23-vector classifies as `FINDINGS_OPEN`, and that an increase of other categories still fails.

The unchanged Scorecard job must continue uploading all **original unmodified SARIF** to real GitHub Code Scanning, retaining original SARIF and machine-readable triage result even on failure. A returned `FAIL` is a posture-regression signal requiring investigation, not a reason to dismiss or suppress genuine alerts. No additional write authority, bypass, untrusted PR execution or external authentication claim is introduced.

## Consequences

- A real reintroduced `FuzzingID` will now fail the independent accepted-main Scorecard monitoring job instead of silently scoring within the old 24-vector.
- Known existing 23 warnings remain open and classified `FINDINGS_OPEN`. Other decreases may be separately accepted only after authentic SARIF and GitHub alert-state verification; baseline changes require review and a new decision record.
- The narrower baseline deliberately makes genuine Scorecard changes require review rather than automatically waiving them.

## Assurance impact

The decision improves regression detection for a previously verified native fuzzing capability. It **does not** prove no bugs, authenticated third-party wheel provenance, full project fuzz coverage, independently reviewed merges, or the absence of other supply-chain risks. A SHA-256 value binds exact evidence bytes but does not authenticate its origin. Security authority stays with verified CI/GitHub, not repository-authored trust declarations.

## Non-claims

- Neither the 23 existing warnings nor a green Scorecard run proves the repository is vulnerability-free.
- The actual cleared `FuzzingID` detector result is separate from a claim that all trust boundaries are fuzzed.
- The 18 local-install detector warnings, SAST application-history detector limitation, independent human review, incomplete administrative controls, OpenSSF Best Practices enrollment and age-based Maintained finding remain independent open items under #349/#360.
- Never relabel `BLOCKED` governance observations as `PASS`; the existing GitHub ruleset and protections are unchanged.
