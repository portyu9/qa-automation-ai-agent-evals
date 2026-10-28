# ADR 0071: Native exact-protected-main push wake for signed Dependabot lifecycle

**Status:** Accepted
**Date:** 2026-10-28
**Extends:** ADRs 0068 through 0070, preserving native signed Dependabot source, publisher, and protected gates.

## Context
After native Dependabot itself superseded stale #417 with signed #422, #423 amended policy for the signed fifth PyPI action revision and merged to protected main. Signed #422 remains tied to an older accepted base and retains ineligible earlier first-attempt CI. The existing dependency-governance privileged controller runs only on its hourly schedule or manual dispatch. No native schedule event was observed between the previous 2026-10-27T20:03Z governance run and the 2026-10-28T01:55Z audit, so the controller cannot automatically request a new signed bot head when main advances. The bot PR event independently runs only unprivileged governance-self-test.

## Decision
Add a native push trigger only for accepted protected main. Retain existing schedule, manual dispatch, unprivileged PR path self-test, and concurrency. The privileged govern job for a push executes only when both the GitHub native ref and repository default branch equal main. Its **first step** independently fetches the live protected main SHA through the native GitHub API, comparing it with GITHUB_SHA, and authenticates exact GITHUB_WORKFLOW_REF. Abort before checkout or owner-token use on any drift. Run the same reviewed default-main code and bounded owner-authenticated reconciliation with allow-merge on this qualified native main push. The already-reviewed controller enforces exact signed bot owner/commit, permitted path + semantic pin changes, live base, immutable native App CI/Security/CodeQL/Package-integrity checks, owner review veto and protected merge. No privileges or token sources are widened; no bot source can alter its own privileged caller.

## Consequences
A governance/policy fix to accepted main now immediately wakes the existing controller, rather than waiting indefinitely for scheduler admission, and may produce one owner-token native rebase request against a stale signed bot head. A later command escalation remains bounded by the source-validated 120-minute threshold and one command per immutable head/main. A push run whose accepted main moves during execution fails closed, leaving later schedule recovery. This adds a native privileged workflow run per accepted main push; no PR byte execution or new token issuance pathway is introduced.

## Assurance impact
Exact-source mutation tests reject push scope broadening, wrong job event/ref, removed live-main SHA check, foreign workflow identity, extra owner credential presence and missing allow-merge event mapping. Native CI, security, CodeQL, semantic ADR policy and rule-protected merge independently qualify the real change. After merge, verify a genuine native push govern-dependabot run, independently authenticated native Dependabot request and new bot-signed current-main PR head before considering the bot lifecycle restored.

## Non-claims
The PR cannot force GitHub's native Dependabot backend to acknowledge commands or regenerate signed releases. Success of governance-self-test or a push wake alone is not evidence of successful protected merge; original bot #422 must remain open until first-attempt all-native checks prove release compatibility. No owner-token secret, repository administration, human approval, ruleset, CodeQL publisher or bot branch is changed.
