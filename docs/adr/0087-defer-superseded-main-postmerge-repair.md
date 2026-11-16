# ADR 0087: Defer superseded-main post-merge qualification repairs

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** Only the prior requirement to mark a trusted post-merge recovery run failed when **the accepted main branch advances while a different, previously authenticated bot merge is being requalified**. It does not supersede any original-bot identity, exact-head verification, Security, CodeQL, CI, owner approval, or merge gate.

## Context

The main-owned Dependabot controller reconciles missing post-merge CI/CodeQL/Security workflow registrations after a verified signed bot PR merges. Only the canonical uniquely identified most recent merged Dependabot PR may be a post-merge repair target; it must be bound by its exact merge SHA, canonical PR identity and both Git parents. The repair checks the live main SHA before **each** required workflow dispatch. GitHub may accept an unrelated protected PR onto main while an earlier trusted recovery is still active. Run [43952512864](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/43952512864) observed this exact race: its original main was `16fe42850846a5ce47e41e97998abca5efa53679`, but PR #450 merged onto main during registration. A `GovernanceError` correctly prevented stale workflow dispatch but turned a normal supersession into a red governance workflow even though the newer main received its own independent push-triggered qualification.

Failing to register a stale-main workflow must not be treated as permission to succeed on that stale subject, repeat privileged dispatch, or replay a non-idempotent merge. However, a separately authenticated new main commit has its own CI/Security/CodeQL runs, and an old recovery may safely **defer** without fabricating a receipt.

## Decision

Introduce a typed, SHA40-bound `MainSuperseded` subclass of `GovernanceError` that can only be raised when an authenticated read of the accepted main ref differs from the specific previously verified post-merge subject SHA. Raise it before any newly requested dispatch both at the per-workflow precondition and at each inter-workflow registration boundary.

Handle this subclass **only** in `_repair_current_main_bot_qualification`, after the canonical latest bot-merge identity, parents, base, and repository checks have already passed. Re-read the main ref and require it still differs from the original subject; reject a wrong-subject exception, a vanished/rolled-back transition, or any other `GovernanceError`. When supersession is verified, emit a structured `deferred-superseded-main` receipt that contains the exact old/new main SHA but **no qualified run IDs, no passing statuses, and no authorization**. Return an empty evidence inventory. The next trusted main push/workflow-run wake independently qualifies the newer main, following all original gates.

Do not catch `MainSuperseded` around the terminal `_merge` operation. A just-committed bot merge whose verification races a subsequent main advancement still raises and is investigated/reconciled by a later trusted run; non-idempotent merge attempts are never replayed. The distinction between a deferred **repair** and a failing **merge transaction** is mandatory.

Add source-level negative tests proving partial old-main registration stops immediately when main moves, that subsequent workflow dispatches are not attempted, that a real superseded main returns no qualified run receipt, that unchanged-main or wrong-subject supersession claims are rejected, and that genuine post-merge dispatch errors remain hard failures.

## Consequences

A completed previous-main repair run can conclude successfully with a truthful deferral when the main branch advances during its recovery window. The new main runs independently on its own SHA, and existing red/missing required checks still remain hard blockers. Under rapid consecutive protected merges, a stale recovery may defer repeatedly without merging or dispatching anything; it cannot manufacture Security, CodeQL or CI evidence. If upstream GitHub refuses a required dispatch without main advancement, the controller still raises a failure.

## Assurance impact

The repair retains all existing provenance checks: the canonical signed bot's merged PR, unique merge commit and two exact parents, current accepted-main lease, immutable head, and real workflow-run registration. Only an independently proven **different** live main SHA authorizes a deferred empty result. The mandatory repository-policy and governance self-tests cover both authorized race handling and malicious or malformed evidence. No token scope, workflow permission, branch bypass, dependency allowance, Code Scanning status, or owner approval is changed.

## Non-claims

- This does not claim that the superseded old main's CI, CodeQL, Security, package-integrity or post-merge checks passed.
- It does not turn an unexpected GitHub 403/404/5xx, missing dispatch, failed workflow, wrong merge parent, or unsigned bot commit into a harmless deferral.
- It does not permit another merge PUT, replaying approval, overriding a ruleset, or unreviewed dependency adoption.
- It does not resolve missing live provider API credentials (issue #447), external Dependabot refresh delays, or GitHub capacity failures.
