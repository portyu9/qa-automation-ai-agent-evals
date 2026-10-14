# ADR 0013: Preserve OpenSSF Scorecard SARIF destination and fail-closed evidence

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

The scheduled OpenSSF Scorecard workflow failed in Actions run `38430296172` (job `115410402030`) on
2026-10-13. The official, immutable-SHA-pinned Scorecard container attempted to create the result at
`/github/workspace/reports/security/scorecard.sarif`, but its parent `reports/security/` was not present
in the checked-out workspace. The producer reported “no such file or directory,” and the independent
`actions/upload-artifact` retention step also rejected the absent SARIF. The failure is an output
directory precondition error, not evidence that the security scan succeeded or that SARIF was produced.

The source of authority is accepted main `403d9dc676ba6ac00a06ff1314bb656e685630bf`, with
`.github/workflows/security-scorecard.yml` blob `29662a4d5ab7eeabf6e5057ff867a5ba4195a6de`.
Its distinct CI, CodeQL, security, Scorecard, release and governance contracts must remain intact.
This change proceeds on PR #347 after confirming that only main exists and no competing open PR was found.

## Decision

Prepare the required parent directory with a dedicated `mkdir -p reports/security` step **after checkout
and before** invoking the existing pinned `ossf/scorecard-action` container. Do not touch the SARIF content,
replace the scanner, soften its errors, alter the pinned action identities, or change the scanning policy.
Keep the same canonical result path for the Scorecard writer, the CodeQL SARIF upload, and the retained
artifact, and retain `if-no-files-found: error` for mandatory Scorecard evidence.

Add deterministic unit tests that assert this ordering, the exact shared SARIF path and the fail-closed
artifact policy. Record this numbered, append-only ADR because GitHub workflow changes are governed by
the repository's assurance-semantic ADR policy.

## Consequences

OpenSSF Scorecard now receives an existing parent directory in the host workspace used by its container;
the scan remains responsible for creating real SARIF. There is one extra local filesystem preparation
step, with no new network, package, credential, or write-permission requirement.

A fresh workflow execution on the accepted post-merge main commit is still required to demonstrate that
the live Scorecard implementation can produce and publish independently validated evidence. Unit tests,
PR CI, and this ADR alone cannot prove the historical scheduled failure is resolved.

## Assurance impact

This correction removes an accidental filesystem failure without transforming missing evidence into a
PASS. The independently pinned CodeQL upload and artifact retention still require the genuine SARIF
file, and the repository's CI, Security, CodeQL and branch-protection checks remain separately mandatory.
If the scanner fails to generate SARIF for another reason, the run must still fail.

## Non-claims

This decision does not assert that a previously failed Scorecard run became successful, that all
vulnerabilities are absent, or that any pending scheduled or on-demand scan has passed. It does not
authorize suppressed findings, synthetic SARIF, skipped required work, or security-rule bypass.
