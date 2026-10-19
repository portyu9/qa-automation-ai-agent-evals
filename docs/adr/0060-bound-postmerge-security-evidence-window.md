# ADR 0060: Bound post-merge Security evidence to the independently dispatched scan window

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Authentic protected Dependabot PR #397 merged autonomously via the main-owned
owner-token governor. The original governed post-merge CI failed correctly
because GITHUB_TOKEN merges suppress ordinary push workflow events and no
Security workflow was dispatched. Accepted protected PR #409 / ADR 0059
fixed this by requiring ordered explicit main-only Security, CodeQL and CI
dispatch on the exact merged SHA. At that accepted main
`b8986b6d354f05afd2ac1646dcc98c9b896bd75e`, all three
independent *push*-triggered workflows succeeded. A new signed-bot
*workflow_dispatch* post-merge lifecycle has not yet been observed.

The #409 controller registers those workflows sequentially but does not
wait for Security to *finish* before starting CI. CI's mandatory independent
Security verifier had a bounded default of 36 attempts spaced five seconds
(~3 minutes), whereas the same Package integrity job explicitly waits
up to 90 attempts spaced ten seconds (~15 minutes) for CodeQL. A legitimately
queued, exact-subject Security run could therefore time out in CI despite
later completing successfully. That is an observable timing-contract gap,
not permission to ignore missing or unsuccessful security evidence.

## Decision

For the required protected Package integrity Security step, explicitly
pass `--attempts 90 --delay-seconds 10`, matching CodeQL's separately
bounded observation window. Keep the exact `--workflow security` selector,
source SHA, branch, trigger event, authenticated GitHub API, original
Security scanner and gate job verification, and fail-closed terminal
failure/missing/ambiguous/foreign-run logic. The existing 22-minute
protected-gate job budget bounds the combined verification.

Extend the independent semantic workflow validator to pin the entire
Security veto command and read-only evidence environment. Add negative
mutation fixtures refusing shortened Security polls, zero delay,
wrong workflow selector and removed subject binding. No original
scanner workflow, upstream pin, ruleset, token scope or release authority
is changed.

## Consequences

A delayed but genuine Security dispatch has the same bounded opportunity
to finish as CodeQL before the mandatory Package integrity check evaluates
it; the gate still fails if independent evidence is not received by the
deadline, fails, is forged, or is inconsistent. This does not fix arbitrary
GitHub downtime, and a governor lacking post-merge retry after an
unrecoverable dispatch error remains a separately testable limitation.

## Assurance impact

Lineage-and-salvage preflight is recorded on issue #399 immediately before
branch creation. Base protected main was
`b8986b6d354f05afd2ac1646dcc98c9b896bd75e`, only remote main,
zero open PRs; #397 and current governance PRs accepted and old #389
concurrency experiment intentionally superseded by protected #390.
The accepted source blob identities are recorded in that preflight.
This ADR is append-only and does not replace ADR 0059.

## Non-claims

Neither fixtures nor green PR CI prove a future signed bot
Security/CodeQL/CI workflow_dispatch lifecycle. Owner-token approval
is not independent human review. External fork qualification,
admin-only settings, genuine Scorecard governance findings and future
upstream availability remain separately unresolved. BLOCKED stays
distinct from FAIL; no synthetic check, scanner downgrade, suppressed
SARIF or branch-protection bypass is authorized.
