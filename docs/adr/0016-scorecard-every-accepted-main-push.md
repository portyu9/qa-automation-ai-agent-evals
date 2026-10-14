# ADR 0016: Scan every accepted main push with authentic OpenSSF Scorecard evidence

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** The *push-path narrowing decision* in ADR 0014; ADR 0013 and the remaining evidence/permission invariants of ADR 0014 remain accepted.

## Context

ADR 0013 ensured OpenSSF Scorecard could create its actual SARIF output in the
GitHub Actions workspace. ADR 0014 then introduced accepted-main execution
only when `.github/workflows/security-scorecard.yml` itself changed, in
addition to Tuesday scheduling and manual invocation. The first authentic
Scorecard result exposed 30 security posture alerts, including real release
workflow token-scope concerns. PR #350 narrowed workflow-wide release
permissions and introduced a required semantic workflow security validator,
but its ordinary accepted-main merge did **not** trigger Scorecard, because
only Scorecard workflow self-changes were eligible.

The original narrowly triggered scanner proved its implementation when
modified, but did not provide prompt posture visibility for ordinary accepted
merges. Security metadata may legitimately change without touching the
Scorecard producer workflow. A successful CodeQL, Bandit, or pip-audit gate
does not imply a passing repository-level OpenSSF Scorecard check.

Lineage-and-salvage preflight before branching:
- Latest accepted `main`: `8b033387c911f2a0d408a3ce3557645c8415920f`, accepted via
  PR #350 with exact-head CI, CodeQL, dedicated Security, deep fuzz,
  dependency governance, and platform smoke passing.
- Only the default `main` branch was present; no open PRs or divergent
  active Scorecard/security branches were found.
- Relevant accepted work: PRs #337, #347, #348 and #350. Their changes
  and ADRs 0013–0015 are already included on main and are preserved.
- Source Scorecard workflow blob: `4ce2ffd5cada74b25cf7fce75f5def25bd92b68c`;
  Scorecard contract test blob: `4ef2805798e6cfc58f935a16b39e32a755a6f135`;
  ADR 0014 blob: `e4fc209e488dfb93a856528599e96832a25b8ccb`.
  No valuable divergent, unmerged implementation needs to be salvaged.

## Decision

Run the pinned official OpenSSF Scorecard producer on **every accepted push
to `main`**, not only when its own workflow file changes. Retain the weekly
Tuesday schedule, manual dispatch, exact checked-out commit, immutable action
refs, true SARIF generation, explicit directory precondition, separate
GitHub code-scanning upload, missing-artifact hard failure, retained SARIF
evidence, read-only workflow default, job-level `security-events: write`,
and concurrency cancellation of stale post-merge assessments.

Do **not** add an untrusted `pull_request` or `pull_request_target` trigger
to this publisher, or grant untrusted PR code security-event publication
authority. Extend the existing Scorecard trigger regression to reject any
new `paths` or `paths-ignore` narrowing. Keep the independent required
CI/CodeQL/scanner gates unchanged.

## Consequences

Every accepted merge now schedules an actual supply-chain posture scan.
The latest accepted-main SARIF can disclose new or persisting alerts faster
than a weekly-only check. More scans consume Actions capacity and, when
multiple merges happen rapidly, the existing concurrency rule cancels
superseded runs; the final accepted main is the monitored subject.

An open Scorecard finding does **not**, by itself, prevent a merge in the
current governance policy. Making posture checks a pre-merge policy requires
a separate defensible baseline/regression threshold and GitHub ruleset
authority; enforcing absolute zero on known environmental/age-dependent
findings would deadlock PRs or incentivize alert dismissal.

## Assurance impact

This narrows the delay between acceptance and authenticated platform
visibility into repository posture, without granting any extra token
permissions, trusting agent-produced evidence, altering deterministic
grading, or relaxing any fail-closed check. The scanner retains genuine SARIF
and exact commit provenance. A pending run is not a successful scan.

## Non-claims

This decision does not claim the 30 baseline alerts are fixed, a perfect
OpenSSF score, successful SARIF publication before a verified run, a security
review by an independent human, or zero exploitable vulnerabilities. Scorecard
metadata is a monitoring domain; it cannot compensate for failed CI/CodeQL
authority or turn `BLOCKED` into `PASS`.
