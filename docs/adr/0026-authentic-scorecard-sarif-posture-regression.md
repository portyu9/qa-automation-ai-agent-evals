# ADR 0026: Fail on new authentic Scorecard findings without erasing known warnings

**Status:** Accepted, with post-merge qualification required.

## Context

Accepted `main@23f5ffa9b1f9ee461bc37c8b2f0d481e5bc02335` has authentic OpenSSF Scorecard v5.5.0 push run [38647020387](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38647020387), job 116136275280, successfully uploading SARIF with **24 unresolved** posture findings (18 `PinnedDependenciesID` plus one each `BranchProtectionID`, `CodeReviewID`, `SASTID`, `FuzzingID`, `MaintainedID`, and `CIIBestPracticesID`). A successful scanning **workflow** currently could be wrongly equated with absence of warnings or newly introduced categories. SARIF contains multiple tool runs; parsing only the first run undercounts real results.

A preflight recorded in #349 verified only `main` exists, zero open PRs, all historical Scorecard/security/governance capabilities (#347–#365) are accepted and none survive on a divergent branch. Existing accepted workflow and scanner contract blobs were `e0b48384349c1598fbc0b0745948a120c6f58b8e` and `9836feb1ec781df9ddb02ca3023fcbb7595d9243`; no stranded code remains to salvage.

## Decision

Add an independent, **post-merge-only observational** Python standard-library SARIF parser after the real Scorecard tool and Code Scanning upload. It validates the SARIF schema, Scorecard tool identity, version string, all runs, declared checks and each result-to-rule binding, including `ruleIndex`. It counts actual `results` across runs (not declared rules and not a fabricated dashboard total). The accepted-main 24-finding vector becomes **maxima**, not an accepted residual-risk target or waiver. A new rule or an increase in any listed finding count fails the monitoring workflow; count decreases are observed, not auto-dismissed. Output classification is `FINDINGS_OPEN`, `NO_REPORTED_FINDINGS`, or `FAIL`; none means `SECURE`. Malformed/absent SARIF fails closed with retained failure report. Record input SHA-256 for byte identity only, not authentication.

The original SARIF is neither modified nor suppressed and is uploaded to GitHub Code Scanning **before** classification. The existing `if: always()` evidence-retention step retains both the original SARIF and the separate triage JSON. The self-test exercises the 24-finding authentic-shape baseline, smaller vectors, zero-result handling, unrecognized and increased findings, malformed scanner identity/version/rules/indices/messages and fail-closed report persistence. Required repository policy executes the self-test, and the security scanner contract guards presence of the classifier and evidence path. No new write permissions or untrusted trigger surface are introduced.

## Consequences

- Known findings stay visible and actionable; successful report upload no longer masks a **new** finding category or growth beyond the observed per-rule baseline.
- A Scorecard change introducing different legitimate rules or additional warnings will fail the monitoring job until explicitly reviewed, not secretly suppressed.
- A reduced count is **not** automatic closure of Code Scanning alerts; exact-head accepted-main scanner evidence and original messages must be inspected.
- Re-qualify on the first accepted postmerge `main` push and preserve any legitimate warning, including SAST detector-limited recognition.

## Assurance impact

A fail-closed observational gate strengthens *detection of posture drift*, not cryptographic authenticity. SHA-256 binds evidence bytes only, not source identity. The postmerge Scorecard job already has limited `security-events:write` to upload findings; the new parser needs no privileged token or network access. None of this alters merge-time CI, scoped owner governance, review authority, CodeQL zero-alert gating, retained release provenance, or the independence of Security/CodeQL checks.

## Non-claims

- The observed 24 findings are real scanner reports, **not** 24 proven exploitable CVEs, and they are **not** all fixed by this PR.
- `FINDINGS_OPEN` is never `PASS` for security posture; a green workflow means successful classification with no unreviewed increase.
- A zero-result SARIF does not establish absence of vulnerabilities; scanner errors cannot be silently represented as zero.
- Checks-in-repository do not independently attest GitHub admin controls, true qualified human review or SAST/Fuzzing detector support.
- Existing local-source/retained-distribution smoke tests, exact hashed third-party dependency installs, BLOCKED non-claims and authentic alert state are unchanged.
