# ADR 0085: Defer incomplete PR CodeQL evidence without hiding failed scans

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** Only the trusted PR-head publisher's previous classification of a *still-running* CodeQL source job as a completed qualification failure. No CodeQL check, evidence requirement, or merge policy is superseded.

## Context

The main-owned `Trusted CodeQL PR-head publication` workflow is awakened by CodeQL completions, main pushes, schedules, and owner dispatch. It discovers open PRs and their newest canonical read-only CodeQL source run and may publish an independently verified, exact-head, same-base SARIF artifact using a privileged API. Newly opened PR scans frequently remain `queued` or `in_progress` while a main push or another scan completion triggers this discoverer. The prior code grouped all non-`completed/success` source runs into a failed `BLOCKED` state and exited nonzero, yielding a recurring red publisher run despite the source scan merely being unfinished.

Blocking publication of an unfinished scan is mandatory. Failing a *completed* unsuccessful scan is also mandatory. However, an unfinished source run is a scheduling state, not evidence of scan failure. A completed CodeQL workflow event and a main-owned periodic schedule already provide subsequent trusted reconciliation wakes; there is no need to misclassify a queued scan as a final failure.

## Decision

In the trusted main-owned verifier's canonical newest-first PR run discovery, permit an explicit **deferred/no-target** state only for a newest CodeQL source run with status `queued`, `in_progress`, `waiting`, `requested`, or `pending` **and** literal null conclusion. Mark its exact PR head as already seen *before* this classification so no earlier successful run can substitute. Do not call the SARIF verifier, download anything, or emit `has_target=true` for a deferred head.

A newest run with status `completed` but any conclusion other than `success` remains `BLOCKED` and exits nonzero when there is no separate verified eligible PR. An unknown status or an incomplete run claiming a terminal conclusion must also fail closed. Other valid PRs may be published independently even if a peer is pending or failed; the trusted subject must pass all existing provenance, base, head, checks, category, artifact, and post-download revalidation.

When every current eligible PR head is pending, return a no-target result with an explicit `DEFERRED` log. The workflow's already-existing `if: steps.provenance.outputs.has_target == 'true'` conditions skip download, SARIF verification and upload. This is NOT a CodeQL success attestation. The distinct canonical required CodeQL checks remain pending and prevent merge until they pass. The existing `workflow_run: CodeQL completed` and scheduled wakes re-evaluate when safe.

Add executable self-test fixtures for all five pending statuses, older-run shadowing, malformed non-null pending conclusion, and existing completed-failure rejection. Keep the trusted verifier on accepted `main`, and do not expand any privileged trigger, API permission, URL allowlist, run inventory window, or retry of mutation endpoints.

## Consequences

Ordinary temporary CodeQL queueing no longer creates false-negative trusted publisher workflow conclusions. A newly completed successful run becomes eligible only when canonical current-base, source artifact, scan category, and live PR controls all satisfy exact-head proofs. Completed unsuccessful scans, conflicting evidence, and transport failures remain hard blockers.

No synthetic SARIF, check-run, attestation, credential, or uploaded artifact is produced for a deferred scan. If GitHub never completes a queued source job, that job and the required branch check remain pending; the publisher cannot pretend to repair GitHub runner capacity or override source failure. A later regression in scan source results in a red publisher again rather than silent acceptance.

## Assurance impact

This change narrows the control-plane interpretation of the **temporal** CodeQL source-run status without weakening trust in a final scan. The source run's authenticated identity, original exact-head SARIF, native active-category check, and trusted-main upload revalidation remain prerequisites. The verifier must still reject a newer failed run over an older success and enforce all negative provenance fixtures. Repository policy must require this new append-only ADR and exact-head CI, Security and CodeQL qualification; downstream Dependabot merging continues to require its own checks.

## Non-claims

- The deferred publisher result is not a completed CodeQL analysis, security pass, merge authorization, or Code Scanning upload.
- No failed, cancelled, skipped, timed-out, or malformed source scan is reclassified as passing.
- No stale-base or changed-head evidence may be uploaded, and earlier successful runs never supersede a newer pending or failed run.
- No privileged merge, review, dispatch, or source mutation is retried.
- This does not resolve separate missing live-provider canary credentials or upstream Dependabot-native service delays.
