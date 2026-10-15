# ADR 0031: Bound the protected CodeQL bridge to its authenticated two-job publication lifecycle

**Status:** Accepted, subject to independent accepted-main push qualification.

## Context

ADR 0030 and merged [PR #371](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/371) eliminated a real permissions boundary flaw: all pull-request CodeQL analysis now uses **read-only** GitHub token permissions; only an independently verified, successful CodeQL scan on trusted `main` can run the separate `security-events:write` SARIF uploader. The trusted publisher's actual Code Scanning upload step succeeded, and CodeQL [push run 38659476011](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38659476011) completed **SUCCESS** on accepted `main@874ef7116be5909e67d2837ab66e3a73675efe3d`.

However, the protected `Package integrity` job in independent [CI 38659476043](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38659476043) began verifying the exact same-SHA CodeQL run at 00:22:42Z and exhausted the inherited default **36 attempts × 5 seconds**, reporting `GateError: all exact-subject CodeQL successes did not register before the bounded gate timeout` at 00:25:53Z, before the new two-stage scan-and-publish completed. The historical `Package integrity timeout-minutes: 7` was similarly sized for the previous one-job workflow. The failure is a **real accepted-main CI regression**, not a CodeQL vulnerability or an acceptable override.

The lineage-and-salvage preflight in issue #349 comment `6181521047` verified latest accepted main `874ef7116be5909e67d2837ab66e3a73675efe3d`, only `main` branch, zero open PRs, and that all previous code/bridge/fork control capabilities through #371 are already merged; none needs salvage or duplicate work. The exact accepted source blobs are documented there.

## Decision

Extend **only the protected CodeQL verification step's bounded wait** with explicit `--attempts 90 --delay-seconds 10` (~15 minutes maximum, with early success return) and raise the *separate* protected `Package integrity` job timeout from 7 to 22 minutes. Retain the independent subsequent Security verifier's previous stricter default polling and exact job-level Security status checks. The existing CodeQL/Security bridge still requires all matching runs for the correct SHA, branch, event, official workflow identity, completed and genuinely successful; it does **not** accept merely successful `Analyze` while verified SARIF publication fails.

Add an independently exercised repository runtime-policy contract that requires the extended bounded wait and exact subject argument bindings in the **CodeQL** bridge step, a sufficiently large but fixed job timeout, and the **independent Security bridge** step following CodeQL. Never insert sleep before the main scan or force synthetic check completion; polling is a read-only observation of the actual GitHub workflow runs and terminates on success or definitive timeout.

## Consequences

- Authentic main CodeQL scan and trusted SARIF publisher can now finish without a premature Package integrity failure, even when they execute after most of the main CI matrix.
- A genuine failed, skipped, cancelled, mismatched or absent CodeQL workflow will **still fail the protected gate**. Neither CodeQL nor Security status is fabricated or optional.
- Run time may increase only when independent CodeQL evidence is genuinely pending; fast runs exit the poll early. If the bound is truly exhausted, the gate must fail closed and retain the existing logs.
- The existing seven ruleset-required GitHub Actions contexts, including `Package integrity`, and native MERGE-only semantics are unchanged.

## Assurance impact

This restores the *liveness* of a strict, non-compensatory protected security gate while preserving its *safety* invariants: exact-commit evidence, every matching run successful, independently successful Security scanners and final `security-gate`, and separately authorized trusted CodeQL Code Scanning publication. No broad workflow privilege or additional external dependency is introduced.

## Non-claims

- Widening the observer's finite window does **not** turn a failed CodeQL scan into success, eliminate Code Scanning alerts, or change Scorecard's historical app-recognition `SASTID` 0/30 limit.
- A green pipeline does not attest freedom from vulnerabilities; SHA-256 binds bytes but does not authenticate a publisher.
- The 23 observed Scorecard warnings, review/branch protection governance, future signed Dependabot current-policy end-to-end run, external fork qualifier, OpenSSF Best Practices enrollment and 90-day Maintained eligibility remain separately open under #349/#360. Never promote `BLOCKED` to `PASS`.
