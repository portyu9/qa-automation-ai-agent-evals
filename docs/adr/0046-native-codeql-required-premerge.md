# ADR 0046: Enforce genuine native PR-head SAST in protected Package integrity

**Status:** Accepted

## Context

Authentic OpenSSF Scorecard scans after protected PR #388, #389, and #390
reported 18/30, 12/30, and 8/30 recent commits recognized as SAST checked.
The underlying last-30 PR-association count was independently reconciled
byte-for-byte with the pinned Scorecard implementation and authentic GitHub
commit-to-PR and native check-run records. PRs #387–#390 all merged after
read-only GitHub Actions CodeQL checks passed but lacked a real native
GitHub Advanced Security CodeQL check on each final PR head. Scorecard
recognizes a specific native app, not arbitrary `github-actions` check names.
A native `neutral` counts for Scorecard's historical metric but is **not**
proof that a security gate succeeded. Issue #380 retains exact evidence.

A real self-hosted qualification experiment on this PR's exact head
`be6b4ee44b51071d3503c5ebdfa7be2324af7d43` subsequently established
that read-only CodeQL [run 38936834431](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38936834431)
completed with original zero-alert evidence and trusted-main publisher
[run 38926004305, attempt 2](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38926004305)
successfully uploaded the authenticated artifact. GitHub then created an
independently verifiable genuine `github-advanced-security CodeQL:success`
check on the identical PR head. Yet the new gate and accepted-main publisher
refused to count the Code Scanning analysis. This was a true fail-closed
identity-query mismatch, not a permission or scanner failure: GitHub's
[Code Scanning REST reference](https://docs.github.com/en/rest/code-scanning/code-scanning)
documents the **`pr`** analysis-list filter for PRs, whereas its `ref`
filter documents `refs/pull/N/merge` (the uploader accepts
`refs/pull/N/head`). Further, the returned SARIF-derived `category`
includes the authenticated `automationDetails.id` trailing slash, while
`analysis_key` names the workflow job without it. Earlier verifier
fixtures incorrectly assumed both fields were identical. Replace the
unqualified head-ref filter with bounded `pr=N` discovery and require
exact original source SHA, head ref, job analysis key, SARIF category
with slash, genuine native app check and error/warning veto. Preserve
negative tests for spoofed unrelated analysis categories and stale heads.

The existing `Package integrity` gate is one of thirteen nonbypassable
GitHub Actions contexts required by Protect Main ruleset #22191532. It
already binds genuine read-only CodeQL and independent Security workflows
to the exact PR subject, but did not reject the absence of independently
authenticated native Code Scanning on that final subject. The existing
trusted publisher runs separately with accepted-main authority on a
best-effort schedule and can safely rerun its accepted-main job while a
live, genuine same-repository PR remains open. A publisher that runs only
after the PR closes cannot retroactively qualify its old final head.

## Decision

Extend the *existing required* `Package integrity` PR job with a new
fail-closed read-only native CodeQL verifier and local adversarial fixtures,
without changing the required status list or adding an unprotected advisory
context. Bind the live open PR number, exact current head SHA and current
protected `main` base SHA. Query canonical GitHub check-runs and the bounded, documented `pr=N`
Code Scanning analysis inventory under read-only scopes:

- Require exactly one native CodeQL check issued by the real
  `github-advanced-security` or `github-code-scanning` app, concluding
  **completed success** on the exact final PR source head.
- Require exactly one corresponding authenticated CodeQL analysis with
  exact live `refs/pull/<number>/head`, matching commit SHA, the trusted
  `.github/workflows/codeql.yml:codeql-upload` analysis key and exact
  original SARIF category with the final `/` delimiter;
  reject warnings/errors, stale and contradictory evidence.
- Treat `neutral`, `skipped`, ordinary `github-actions CodeQL` green,
  missing/check-run-truncated evidence, base/head drift and unqualified
  external-fork PRs as **BLOCKED**, never PASS.
- Wait only a bounded 48 × 5 seconds for a genuinely absent pending native
  publication, preserving the 22-minute existing gate timeout. All other
  contradictory evidence fails closed rather than silently retrying an
  older green sample.
- Leave the PR scanner's `security-events: read`, original two-language
  zero-alert SARIF veto, and the main-only independent
  `security-events: write` publisher completely unchanged.
- Preserve all thirteen required Actions checks and zero ruleset bypass
  actors; retain independent CodeQL and Security subjects and tests.
  Semantic graph validation pins the exact protected-gate step sequence,
  trigger and read-only GitHub evidence authority.

The accepted-main-owned publisher's **duplicate-avoidance check** also uses
this documented PR analysis query and correct SARIF category after merge,
so a prior genuine native check and its source analysis remain jointly
qualified; no duplicate publisher upload is authorized by a missing
head-ref query result alone. A new real same-repository PR must receive
authentic current native publication while still open. This change's own PR must satisfy the
same binding and all original protections before protected merge.

## Consequences

A PR without a qualifying native analysis cannot merge under normal
protected checks, even if read-only CodeQL succeeds. GitHub's
best-effort scheduler can delay the separately authenticated publisher,
so an otherwise clean PR may be **BLOCKED** until a main-owned publisher
run safely completes and the required job is retried. This availability
cost is not a reason to skip, reclassify or forge security evidence.

Fork PR publication remains intentionally unqualified and BLOCKED
until independently authenticated fork-safe provenance exists. This
does not add `pull_request_target`, PR-side privileged uploads, an
untrusted workflow invocation, a human approval, or a synthetic status.

## Assurance impact

The mandatory merge path now refuses historical blind spots caused by
merging a PR whose final head never acquired recognized native SAST
evidence. Native check-run app identity is supplied by GitHub rather
than self-declared in PR content. A Code Scanning analysis is also
matched to the verified active category and exact source SHA, avoiding
the previously encountered obsolete category ambiguity. Missing
provider data remains BLOCKED, not FAIL or PASS. Source scanner
verification and independent original-SARIF authentication stay
non-compensatory; hashes bind artifacts but are not authentication.

## Non-claims

- This does **not** retroactively qualify any of the four older merged PRs
  or immediately lift authentic Scorecard 8/30 to 30/30.
- This does **not** close the live Scorecard SAST alert #27 or parent #349;
  verified future Scorecard evidence and Code Scanning alert lifecycle
  must justify closure.
- This does **not** independently qualify external forks or guarantee
  GitHub schedules or API reads run within a defined SLA.
- Scorecard's willingness to count `neutral` is **not** adopted as a
  security approval; only native exact-head **success** qualifies here.
- The remaining BranchProtection, CodeReview and Maintained findings
  reflect separate governance and age conditions and are not suppressed.
