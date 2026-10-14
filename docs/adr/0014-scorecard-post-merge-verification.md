# ADR 0014: Verify Scorecard workflow changes on accepted main

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

ADR 0013 repaired the absent Scorecard SARIF output directory. It was implemented and
merged through PR #347 on accepted main `0c9b6c2b9c1c86662a8c1732bfbf46828ccbd267`;
both Python quality lanes, CodeQL, the dedicated Security workflow and CI passed.
However, the independent OpenSSF Scorecard workflow is scheduled weekly and manually
dispatchable only. A successful PR and push do not actually execute the Scorecard
container after its own workflow definition changes. That creates a several-day
verification blind spot for exactly the type of production failure ADR 0013 addressed.

The accepted Scorecard workflow's upstream blob is
`4500d6462bca73a2895d73770696a82d61bbde32` (PR #347).
Preflight found only the accepted `main` branch, no open PRs, and no unmerged
divergent Scorecard implementation to salvage. PRs #337 and #347 are already
accepted; no prior semantics are superseded.

## Decision

Add a precisely scoped push trigger to `.github/workflows/security-scorecard.yml`:
only accepted `main` pushes which change that exact workflow file will run
OpenSSF Scorecard. Retain the weekly cron and explicit manual dispatch. Do not
trigger untrusted pull requests: the job requires `security-events: write` to
publish a real SARIF result to code scanning.

Keep the official SHA-pinned Scorecard action, its existing parent-directory
precondition, genuine SARIF generation, CodeQL upload, `if-no-files-found: error`
artifact retention and permissions unchanged. Add a unit contract asserting the
post-merge self-change trigger and absence of a pull-request trigger.

## Consequences

The merge of this change itself will exercise Scorecard at the accepted main
revision, producing an independently observable Actions run and SARIF receipt
rather than inferring success from PR CI. Later workflow edits will receive
the same bounded qualification. Ordinary main pushes to unrelated paths incur
no extra Scorecard execution. Weekly scans and manual dispatch remain available.

## Assurance impact

A live Scorecard run at the precise accepted main SHA is required to substantiate
a green result. A successful CI or unit test alone remains insufficient. The
Scorecard producer and SARIF consumers continue to fail closed on missing,
corrupt or unacceptable evidence. Untrusted PR subjects cannot acquire SARIF
publication authority through this trigger.

## Non-claims

This ADR does not claim a particular run or finding is already green, nor that
the repository has no security vulnerabilities. It does not authorize simulated
SARIF, suppressed scanner failures, untrusted PR writes, or any bypass of CodeQL,
security scans, branch protections or the independent merge gates.
