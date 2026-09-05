# Session Assurance Reports

## Purpose

`AssuranceReport` is a self-validating session-level artifact for review, CI handoff, and later audit. Version `agent-evals/assurance-report/v2` binds the `agent-evals/trial-evidence/v2` schema and exact trial evidence roots used by one evaluation session to deterministic oracle snapshots, optional subordinate semantic judgments, reliability calculation, frozen release policy, and the release-gate decision derived from that session.

The report is deliberately **not** another grading authority. It preserves conclusions and verifies their internal derivation whenever the artifact is loaded.

## Authority separation

Assurance Report v2 makes two grading classes explicit instead of collapsing them into one score:

1. **deterministic oracle snapshots** — policy and outcome conclusions derived from normalized evidence;
2. **optional semantic judgment receipt** — a calibrated meaning-level judgment that may exist only after deterministic PASS.

The second class is subordinate to the first.

```text
bound TrialEvidence schema + exact final evidence root
        ↓
deterministic oracle snapshots
        ├─ deterministic FAIL ───────────────→ trial FAIL
        │                                     no semantic receipt is valid here
        └─ deterministic PASS
             ↓ optional SemanticJudgmentReceipt
             ├─ PASS ────────────────────────→ trial PASS
             ├─ FAIL ────────────────────────→ trial FAIL, non-critical
             └─ ABSTAIN ─────────────────────→ trial INCONCLUSIVE
        ↓ recomputed
reliability statistics
        ↓ + frozen ReleasePolicy
release-gate decision + reasons
        ↓ canonical domain-separated hash
report_root
```

A semantic result cannot rescue deterministic failure and does not contribute to the deterministic critical-violation count.

## Per-trial record

For each trial the report records:

- `trial_id`;
- exact final `evidence_root`;
- terminal trial verdict;
- deterministic oracle snapshots: unique oracle name, verdict, reasons, and critical flag;
- optional full `SemanticJudgmentReceipt`.

The semantic receipt itself binds the exact **pre-semantic** evidence root, rubric, judge profile, accepted calibration, bounded judge-input digest, structured-response digest, criterion results, derived semantic decision, and its own integrity root.

The final `TrialEvidence.evidence_root` necessarily differs from the pre-semantic root because the semantic event is appended afterward. The report keeps both relations without duplicating the complete event stream.

## Session-level record

At session level the report records:

- assurance-report schema version `agent-evals/assurance-report/v2`;
- bound `TrialEvidence` schema version;
- exact subject identity;
- exact scenario identity;
- the frozen `ReleasePolicy`;
- the reliability snapshot;
- release-gate decision and reasons;
- a domain-separated `report_root` over all report content except the root itself.

Binding the evidence schema matters because an evidence root is meaningful only with the serialization and hashing semantics that define it. A future incompatible `TrialEvidence` format therefore cannot be silently interpreted as v2 evidence inside this report format.

## What is recomputed on every load

Pydantic model validation is not merely schema parsing. A loaded report must satisfy all of the following:

1. the assurance-report schema and bound evidence schema are the supported versions;
2. trial IDs are unique;
3. deterministic oracle names are unique within each trial;
4. non-blocked trials contain completed deterministic oracle results;
5. deterministic oracle results themselves have resolved PASS/FAIL verdicts;
6. `BLOCKED` cannot carry completed oracle results or semantic judgment evidence;
7. a semantic judgment cannot coexist with deterministic oracle failure;
8. semantic receipt subject identity matches the report subject;
9. semantic receipt scenario identity matches the report scenario;
10. the trial verdict recomputes from deterministic results plus optional semantic decision using strict precedence;
11. `INCONCLUSIVE` requires an abstaining semantic judgment;
12. reliability recomputes from the validated trial verdicts using the recorded `k`;
13. critical-violation count recomputes from **failed critical deterministic oracle snapshots only**;
14. the release-gate decision and reasons recompute from reliability, deterministic critical violations, and the frozen policy;
15. the canonical report root matches the complete report content.

A schema-valid JSON object that forges a semantic decision, trial verdict, success rate, Wilson interval, gate decision, gate reasons, critical flag, evidence root, policy threshold, or report root therefore fails validation unless all lower-level bound relations also remain valid.

## Generation from a session

`AssuranceReport.from_session()` verifies the in-memory session before creating an artifact:

- at least one evaluated trial must exist;
- every trial evidence envelope must match the session subject identity;
- every trial evidence envelope must match the session scenario identity;
- trial IDs must be unique;
- deterministic oracle names must be unique within each non-blocked trial;
- deterministic and semantic precedence must rederive each trial verdict;
- any semantic receipt must revalidate under its own contract;
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
    max_inconclusive_trials=0,
)

report = AssuranceReport.from_session(session_result, release_policy=policy)
serialized = report.model_dump_json(indent=2)

# Parsing performs derivation checks again; it is not a passive JSON load.
verified = AssuranceReport.model_validate_json(serialized)
assert verified.schema_version == "agent-evals/assurance-report/v2"
assert verified.evidence_schema == "agent-evals/trial-evidence/v2"
assert verified.report_root == report.report_root
```

## Semantic FAIL and criticality

A semantic FAIL is a resolved trial failure, so it contributes to reliability failure counts and can cause a release gate to reject because success-rate requirements are not met.

It is **not** a critical policy violation. `critical_violations` is recomputed exclusively from deterministic oracle snapshots marked critical. This prevents a model grader from inventing safety-critical authority merely by returning FAIL.

Conversely, a deterministic critical failure can never be offset by a semantic PASS because the runtime does not call the semantic judge after deterministic failure and the report rejects any artifact that tries to combine those claims.

## Semantic ABSTAIN

A semantic ABSTAIN maps to trial `INCONCLUSIVE`, not PASS and not FAIL.

That distinction preserves evaluator uncertainty. Release policies may bound `max_inconclusive_trials`; a report can therefore remain release-ineligible without falsely converting uncertainty into subject failure.

## Relationship to evidence persistence and replay

An assurance report references each trial through its final `evidence_root` and explicitly binds the evidence schema that defines that root; it does not duplicate the complete event stream, terminal state, or persisted evidence payload.

That separation is intentional:

- `LocalEvidenceStore` verifies and returns the actual persisted `TrialEvidence`;
- `EvidenceReplayAdapter` can submit those historical observations through deterministic grading again under exact identity;
- if semantic evidence is present, replay reconstructs the pre-semantic envelope and revalidates the historical semantic receipt **without calling a fresh semantic model**;
- `AssuranceReport` verifies session-level derivation from its bound grading facts, evidence schema, evidence roots, optional semantic receipts, reliability, and release policy.

Therefore the report can answer, "Does this stored session conclusion internally follow from the grading facts and policy it contains?" It cannot by itself answer, "Would the deterministic or semantic evaluators produce those same observations if run again now?" The latter requires fresh execution, not report parsing.

## Integrity boundary

The `report_root` is a domain-separated SHA-256 integrity root. It detects unacknowledged changes relative to a trusted root value and creates a stable content identity for the report.

It is **not**:

- a digital signature;
- a MAC;
- authenticated publisher identity;
- a trusted timestamp;
- remote attestation;
- proof that the referenced evidence was honestly produced;
- proof that the semantic provider actually produced an embedded response;
- proof of current provider or target-system state.

An actor who can coherently rewrite an unsigned report can recompute ordinary hashes. Strong writer authentication requires a separate signing/attestation boundary.

## Why derived values are still stored

Reliability and gate results are included because they are useful review surfaces and make artifacts self-contained for humans and CI. They are not trusted merely because they are serialized. Validation always recomputes them from lower-level bound inputs.

The same rule applies to semantic decisions: the receipt stores the structured criterion results and derived decision, but validation rechecks rubric identity, threshold semantics, response digest, calibration/profile identity, and the receipt root.

This makes a report auditable without turning a cached percentage, model verdict, or release label into an oracle.

## Failure semantics

A malformed or internally inconsistent report fails validation. There is no repair-on-read behavior and no rule that treats an invalid report as an `ACCEPT` or `PASS` result.

When the underlying trial evidence itself needs to be re-established, use the integrity-verified evidence store and exact-identity replay path described in [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md). For the semantic authority model, see [Calibrated Semantic Judging](SEMANTIC_JUDGING.md).

[← Documentation hub](README.md)
