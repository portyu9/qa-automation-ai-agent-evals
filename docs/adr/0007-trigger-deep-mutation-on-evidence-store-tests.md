# ADR 0007: Trigger deep mutation assurance on evidence-store tests

**Status:** Accepted
**Date:** 2026-10-12
**Supersedes:** None

## Context

The scheduled deep mutation assurance campaign found an evidence-store mutation score below the governed 95% minimum: 435 of 460 mutants killed (94.565%). The failure exposed surviving mutations that bypass a caller-specified evidence-minimization policy. The accepted regression test in `tests/unit/test_evidence_store.py` exercises the custom one-redaction ceiling, verifies fail-closed rejection of two credentials, and confirms that no durable evidence is published.

Despite that new test, the pull-request path filters in `.github/workflows/deep-mutation.yml` did not include `tests/unit/test_evidence_store.py`. General CI and security checks could therefore be green after an evidence-store test change without the independent, expensive mutation-assurance campaign being requalified.

## Decision

Include `tests/unit/test_evidence_store.py` in the existing pull-request path trigger of the deep mutation workflow. Changes to the executable evidence-store test contract now trigger the complete, independently scored deep mutation campaign, not a narrowed or artificially green substitute.

Retain the existing ten campaigns, minimum score of 95% for each campaign, deterministic subject SHA, pinned dependencies, bounded concurrency, and 180-minute workflow timeout. The trigger-only change does not expand mutation authority, adjust results, suppress surviving mutants, or edit production evidence handling.

## Consequences

Review of evidence-store test changes may take longer because the complete mutation campaign must finish. A failing campaign remains a legitimate CI failure and cannot be silently hidden behind otherwise passing unit/security checks. This PR's new workflow trigger runs the campaign on the exact PR subject; the result must be reviewed before merge.

Other unrelated test paths remain under their existing explicit trigger governance. Future additions to the governed deep mutation suite must be evaluated for trigger coverage rather than assumed to be covered by general CI.

## Assurance impact

This decision closes a blind spot between evidence-store regression-test evolution and mutation evidence. It requires mutation qualification when the test guarding the caller's strict minimization policy is modified, preserving the boundary against silent policy downgrade and evidence persistence after redaction-budget failure.

The underlying score calculation and its minimum remain unchanged. The campaign must produce its own terminal run result and score evidence against the changed subject.

## Non-claims

This ADR does not claim that a passing mutation score proves the absence of security vulnerabilities, all possible evidence-loss paths, or complete hostile-filesystem defenses. It does not make passing regular CI equivalent to passing deep mutation assurance. It does not authorize lower score thresholds, mutation exclusions, workflow permissions changes, or bypass of security and release governance.
