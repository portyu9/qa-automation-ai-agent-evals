# ADR 0079: Bound an ignored Dependabot rebase with faster native recreate escalation

**Status:** Accepted
**Date:** 2026-11-09
**Supersedes:** Only ADR 0068's initial 120-minute native `recreate` escalation interval. Retains ADR 0068's finite-state recovery and evidence boundaries, ADR 0069's native owner-command provenance, ADR 0077's ten-minute scheduled phase, and ADR 0078's trusted main-owned publisher wake.

## Context

Repository `portyu9/qa-automation-ai-agent-evals` accepted PR #436 at main commit `106200d743f115ac3af87c3859aa22dd152a37df` on 2026-11-09, after an earlier bot update. Open Dependabot PR #437 proposes one immutable `zizmorcore/zizmor-action` SHA change (0.8.0 to 0.8.1) on a superseded main base `06621081e0f2e8442ae06a5f4dd7397f23063c05`. Its native signed head `127ef3eb418f7c2149294d07fa3780111ae7f163` passed initial CI, security and CodeQL but cannot be merged on a stale base.

The existing controller requested a rebase at 2026-11-09 16:59:09 UTC through the **native repository owner**; GitHub records `performed_via_github_app=null` and the expected owner login. Dependabot recorded a mention event at 16:59:11 UTC but had not issued a new head at investigation. The previously configured 120-minute escalation leaves that otherwise eligible signed patch stranded even when all controller checks are green. ADR 0068 already permits a finite, authenticated `@dependabot recreate` command after an explicitly bounded 30–1440 minute delay. ADR 0077/0078 reduced wake latency but could not accelerate the recovery stage before its configured delay elapsed.

## Decision

Set `.github/dependency-governance.json` `nativeRefreshEscalationMinutes` to **30 minutes**, the existing minimum permitted by the fail-closed validator. Leave the finite state machine intact: at most one authentic `@dependabot rebase`, then at most one `@dependabot recreate`, per exact signed bot head and accepted main SHA, never before the owner's timestamp passes the configured threshold. Eligibility to send either command still requires native signed bot provenance, acceptable dependency-only semantic changes, valid fresh base/head leases, a non-expired PR and no manual-review vetoes. Any GitHub App-attributed owner impersonation, duplicate command, malformed/missing/future timestamp, shifted main/head, or unexpected service response remains a hard block.

Refactor the governance self-test time fixtures to derive the **last premature minute**, exact boundary and first overdue minute from the configured interval rather than assuming the old 120-minute value. Keep automated approval and merge separately gated by exact-head CI, zero-alert CodeQL, `Package integrity`, authentic Security runs, current-main merge ancestry, owner-authorized review and post-merge requalification. This change never edits a bot branch, modifies or re-signs Dependabot commits, or turns an absent bot response into green evidence.

## Consequences

Ignored native rebase requests can now be escalated at the next eligible reconciliation after 30 minutes, rather than 120 minutes. The ten-minute cron remains **best effort** and the independently authenticated trusted publisher completion can wake reconciliation sooner; neither mechanism provides a real-time SLA. This increases the probability of a bot recreation shortly after a temporary GitHub service delay, but does not increase the maximum command count, permission scope or merge authority. A native `recreate` may refresh the Dependabot PR and legitimately restart all exact-head CI/security checks. If Dependabot ignores both commands, the PR must remain open and visible for manual investigation.

## Assurance impact

The accepted preflight base is `main@106200d743f115ac3af87c3859aa22dd152a37df`. The only other live branch before creating this lane was `dependabot/github_actions/routine-actions-401d4b32a3@127ef3eb418f7c2149294d07fa3780111ae7f163`, `main...head` ahead 1/behind 3, unique changed file `.github/workflows/ci.yml` (+1/-1 immutable action pin). That signed source is **must preserve**. Prior merged fixes #420, #421, #434, #435 and accepted pip update #436 are **already accepted**. No other historical divergent live branch or unique orphaned work was found, so no new lane reuses or drops bot content.

The changed artifacts are the bounded policy JSON, the parameterized Python regression self-test in `.github/scripts/dependency_governance.py`, this new append-only ADR, and operator documentation. Require exact-head governance selftest, semantic ADR gate, comprehensive CI/security/CodeQL and protected merge gates on the normal PR before acceptance; post-merge verify `main`, native bot response, signed update qualification and final main evidence. Regression coverage must keep rejecting premature or duplicate escalation, forged owner/App origin, invalid timestamps and stale/head-changed input.

## Non-claims

A successfully posted `@dependabot recreate` request does **not** prove that Dependabot regenerated the PR. This change does not guarantee a 30-minute response, validate an external GitHub service's uptime, claim existing open CodeQL alert inventory is empty without evidence, or authorize human/bot bypasses. It does not change any root dependency, signed source payload, required approval, security scanner, or branch-protection control.
