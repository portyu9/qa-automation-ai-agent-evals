# ADR 0023: Preserve BLOCKED for unobservable live administrator controls

**Status:** Accepted — supersedes the observation semantics of ADR 0022,
without modifying the accepted historical ADR.

## Context

ADR 0022 introduced an authenticated, read-only default-branch monitor
of GitHub repository settings and Protect Main ruleset. Its first real
post-merge job
[38617543213](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38617543213)
failed with `repository allow_auto_merge: expected True, got None`.
This GitHub Actions `GITHUB_TOKEN` cannot see the administrator-only
repository field, although the independent connected owner-authenticated
GitHub API had verified native auto-merge enabled, merge commits
allowed, and squash/rebase disabled. The runtime must not invent the
hidden value or report an unavailable administrative claim as false.

Mandatory lineage-and-salvage preflight is recorded in issue #360
before branch `fix/live-governance-admin-field-blocked-20261014`:
accepted main `3b0331310b535d3abbe6f1e12da7d5f072e07bb0`,
only main, no open PRs, PRs #321/#330/#350/#359/#361/#362
fully merged, exact baseline blob identities recorded and nothing
unique stranded on a divergent historical branch.

## Decision

Keep the live ruleset validation strict and **fail closed** on any
actually observed relaxation: wrong protected branch, bypass actor,
force push or deletion exposure, absent required approval-thread
resolution, non-merge history, wrong status integration identity,
missing protected checks, or loss of strict up-to-date checks.

For each administrator-only repository merge setting, classify its
value as follows:

- explicitly observed expected value: **PASS**;
- explicitly observed contradictory value: **FAIL**;
- absent or null in the read-only Actions token API response:
  **BLOCKED (admin visibility)**.

Do not fill missing values from checked-in metadata or operator
assertions. Keep independent `ruleset_controls: PASS` only after
actually reading and validating its live API representation; do not
allow one successful part to compensate for an unobservable part.

The trusted-main monitor is a **report-generation workflow**, not a
required PR merge-check context. It may exit successfully when its
report explicitly contains `merge_controls: BLOCKED`, but must also
emit a visible GitHub Actions warning and retain machine-readable
status evidence. Such a successful report-generation job cannot be
cited as `PASS` for the blocked underlying assurance assertion.
Malformed or contradicted *observed* authority continues to fail the
workflow.

Add adversarial self-tests for each absent/null administrator field;
retain existing tests for changed, disabled, missing or tampered
rulesets and check integrations. Remain read-only and main-only.

## Consequences

The monitor continues to expose real live ruleset drift without a
privileged owner PAT or untrusted-fork token escalation. Missing
administrator fields remain an honest external verifier prerequisite,
not masked by local confidence. The operator may independently check
them through owner-authorized GitHub settings and attach the dated
result to issue #360.

Previous runs' statuses and ADR 0022 meanings are **not retroactively
rewritten**. This ADR applies to monitors deployed at or after its
accepted merge and describes the narrower observable assurance domain.

## Assurance impact

The actual trust boundary is the GitHub API scope: a scoped
`GITHUB_TOKEN` sees some public repository facts but cannot prove
every administrator setting. Reporting `BLOCKED` retains the important
difference between a missing attestation, an observed violation and a
confirmed compliant setting. The protected `Package integrity`
bridge and independent CodeQL/Security evidence stay untouched.

## Non-claims

This does **not** prove human code review, an E2E Dependabot signed
merge, an external fork PR, private vulnerability reporting enablement,
or all repository security settings. It does not change the 24
genuine open Scorecard Code Scanning findings or silently dismiss
unrecognized Python fuzzing/local artifact heuristics. A successful
workflow conclusion only proves execution of this bounded monitor,
not universal GitHub governance compliance.
