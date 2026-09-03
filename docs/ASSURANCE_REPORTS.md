# Session Assurance Reports

## Purpose

`AssuranceReport` is a self-validating session-level artifact for review, CI handoff, and later audit. It binds the exact trial evidence roots used by one evaluation session to the deterministic grading outputs, reliability calculation, frozen release policy, and release-gate decision derived from that session.

The report is deliberately **not** another grading authority. It preserves conclusions and verifies their internal derivation whenever the artifact is loaded.

## Derivation chain

```text
exact evidence root per trial
        ↓ bound reference
oracle result snapshots
        ↓ recomputed for resolved trials
trial PASS / FAIL
        ↓ recomputed
reliability statistics
        ↓ + frozen ReleasePolicy
release-gate decision + reasons
        ↓ canonical domain-separated hash
report_root
```

For each trial the report records:

- `trial_id`;
- exact `evidence_root`;
- terminal trial verdict;
- deterministic oracle snapshots: oracle name, verdict, reasons, and critical flag.

At session level it records:

- exact subject identity;
- exact scenario identity;
- the frozen `ReleasePolicy`;
- the reliability snapshot;
- release-gate decision and reasons;
- a domain-separated `report_root` over all report content except the root itself.

## What is recomputed on every load

Pydantic model validation is not merely schema parsing. A loaded report must satisfy all of the following:

1. trial IDs are unique;
2. a resolved `PASS` or `FAIL` trial contains completed deterministic oracle results;
3. a resolved trial verdict recomputes from those oracle snapshots;
4. `BLOCKED` cannot carry completed oracle results;
5. reliability recomputes from the validated trial verdicts using the recorded `k`;
6. critical-violation count recomputes from failed critical oracle snapshots;
7. the release-gate decision and reasons recompute from reliability, critical violations, and the frozen policy;
8. the canonical report root matches the complete report content.

A schema-valid JSON object that forges a success rate, Wilson interval, gate decision, gate reasons, critical flag, trial verdict, evidence root, policy threshold, or report root therefore fails validation unless all dependent fields are coherently changed as well.

## Generation from a session

`AssuranceReport.from_session()` also verifies the in-memory session before creating an artifact:

- every trial evidence envelope must match the session subject identity;
- every trial evidence envelope must match the session scenario identity;
- trial IDs must be unique;
- resolved trial verdicts must agree with their deterministic oracle results;
- the session's `ReliabilityReport` must recompute from its trial verdicts.

Only then is the release gate evaluated and the report root produced.

```python
from agent_evals.assurance import AssuranceReport
from agent_evals.gates.release import ReleasePolicy

policy = ReleasePolicy(
    min_resolved_trials=20,
    min_success_rate=0.95,
    min_wilson_low=0.80,
    max_critical_violations=0,
    max_blocked_trials=0,
)

report = AssuranceReport.from_session(session_result, release_policy=policy)
serialized = report.model_dump_json(indent=2)

# Parsing performs derivation checks again; it is not a passive JSON load.
verified = AssuranceReport.model_validate_json(serialized)
assert verified.report_root == report.report_root
```

## Relationship to evidence persistence and replay

An assurance report references each trial through its `evidence_root`; it does not duplicate the full event stream, terminal state, or persisted evidence payload.

That separation is intentional:

- `LocalEvidenceStore` verifies and returns the actual persisted `TrialEvidence`;
- `EvidenceReplayAdapter` can submit those historical observations through deterministic policy/outcome grading again under the exact original identity;
- `AssuranceReport` verifies session-level derivation from its bound grading snapshots and evidence roots.

Therefore the report can answer, "Does this stored session conclusion internally follow from the trial verdict/oracle facts and policy it contains?" It cannot by itself answer, "Would the deterministic oracles produce those same oracle results if we load the underlying evidence again?" The latter requires evidence retrieval and replay.

## Integrity boundary

The `report_root` is a domain-separated SHA-256 integrity root. It detects unacknowledged changes relative to a trusted root value and creates a stable content identity for the report.

It is **not**:

- a digital signature;
- a MAC;
- authenticated publisher identity;
- a trusted timestamp;
- remote attestation;
- proof that the referenced evidence was honestly produced;
- proof of current provider or target-system state.

An actor who can coherently rewrite an unsigned report can recompute ordinary hashes. Strong writer authentication requires a separate signing/attestation boundary.

## Why derived values are still stored

Reliability and gate results are included because they are useful review surfaces and make artifacts self-contained for humans and CI. They are not trusted merely because they are serialized. Validation always recomputes them from lower-level bound inputs.

This makes a report auditable without turning a cached percentage or release label into an oracle.

## Failure semantics

A malformed or internally inconsistent report fails validation. There is no repair-on-read behavior and no rule that treats an invalid report as an `ACCEPT` or `PASS` result.

When the underlying trial evidence itself needs to be re-established, use the integrity-verified evidence store and exact-identity replay path described in [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md).

[← Documentation hub](README.md)
