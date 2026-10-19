# ADR 0055: Retry transient GitHub Security evidence transport without relaxing gate

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Live Package integrity on protected PR #402, exact head `69ee9adcec0df40eea4e7b28c15607ace01ed142`,
failed solely due to GitHub API HTTP 502 during
`verify_required_codeql.py` `fetch_security_jobs`.
The separate native CodeQL, Security and CI checks had succeeded; a
manual retry of the unchanged Package integrity job subsequently passed.
A single transient API response currently aborts the aggregate instead
of retrying the exact immutable evidence request.

## Decision

Retry only `TransientApiError` from reading **the same**
`/actions/runs/<run_id>/attempts/<attempt>/jobs` endpoint, at most
three total calls separated by deterministic one- and two-second delays.
Retry must not switch run/attempt, substitute older evidence, skip the
required scanners or accept incomplete, mismatched or failed results.
On exhaustion propagate the original fail-closed transport error.
Do not retry structural/permission/identity errors or scanner FAIL.
Tests assert exact request call arguments, retry count/delays, exhausted
retry refusal and permanent denial single-attempt refusal.

## Consequences

A transient upstream 502 can recover within the same protected job,
rather than requiring a manual re-run. A persistent outage remains
BLOCKED/FAIL, never PASS. The test suite verifies transport resilience
separately from the scanner-policy semantics.

## Assurance impact

This is operational resilience only. Both real Security jobs for
*every* independently successful exact-head Security workflow still
must have matching run ID, attempt, completed state and success.
The full thirteen protected checks, native Code Scanning, CodeQL
evidence provenance, owner token and no-bypass rules are unchanged.

## Non-claims

- Short retries do not guarantee GitHub uptime or unrestricted future
  autonomy.
- Neither passing CI nor artifact hashes authenticate vendor intent.
- No ignored CodeQL alerts, weakened scanner contracts, code-review
  bypass or self-declared candidate trust are allowed.
- Unobservable administrator settings remain BLOCKED.

## Evidence

Accepted base main `6d6b62d37e4b67be2ea6ac4a4bf1960302805d58`, preflight open bot #397 and separate
preapproved scanner migration #401; the latter's unique source and ADR
are being preserved on its existing branch. Previous #400/#402 are
accepted and historical #389 remains explicitly reverted by #390.
Observed live Package integrity job `118145991546` failed with GitHub
Security jobs API HTTP 502, and its exact-head rerun
`118146692010` succeeded without source changes.
