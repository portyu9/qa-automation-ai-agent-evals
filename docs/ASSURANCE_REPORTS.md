# Session Assurance Reports

## Purpose

`AssuranceReport` is a self-validating session-level artifact for review, CI handoff, and later audit. Version `agent-evals/assurance-report/v4` binds the `agent-evals/trial-evidence/v2` schema, exact trial evidence roots, a minimal scenario-derived grading profile, deterministic oracle snapshots, subordinate semantic judgments when required, reproducible reliability configuration, frozen release policy, and the release-gate decision derived from that session.

The report is deliberately **not** another grading authority. It preserves conclusions and verifies their internal derivation whenever the artifact is loaded.

## Why v4 exists

A scenario identity is a content hash of the complete `EvaluationScenario`. It identifies an exact scenario, but the hash is not invertible. Assurance Report v3 stored only that identity, so a standalone report could not know whether the scenario required semantic grading or side-effect idempotency grading.

That created two fail-open omission shapes for manually reconstructed session objects:

- a semantic-rubric scenario could be represented as deterministic `policy=PASS` + `outcome=PASS` with no semantic event or semantic receipt and still look like an ordinary PASS;
- a side-effect-idempotency scenario could omit both the observation and the `side-effect-idempotency` oracle, satisfying v3's observation/oracle co-presence check by making both absent.

Real `TrialRunner` behavior is stricter. A configured semantic rubric requires semantic completion after deterministic PASS, and a configured side-effect contract requires verified observation plus its deterministic oracle. V4 preserves that **grading shape** explicitly rather than trying to infer it from a one-way scenario hash.

Version 4 therefore adds `ScenarioGradingProfile`, requires the exact scenario contract during `AssuranceReport.from_session(...)`, verifies that scenario's identity against the session, and persists only the two scenario commitments that alter report-level grading structure:

- `semantic_rubric_identity` — exact rubric identity, or `null` when no semantic rubric is configured;
- `side_effect_idempotency_identity` — exact idempotency contract identity, or `null` when no side-effect contract is configured.

The profile intentionally does **not** serialize the full scenario objective, initial state, authority, retrieval material, approval intent, required/forbidden outcomes, or tags. Those remain represented by `scenario_identity` and require the exact scenario/evidence replay path when their historical relations must be re-established.

## Authority separation

Assurance Report v4 keeps deterministic and semantic grading as separate authority classes:

1. **deterministic oracle snapshots** — required core `policy`/`outcome` conclusions plus the scenario-required `side-effect-idempotency` conclusion and any additional deterministic conclusions produced by an extending runtime;
2. **semantic judgment receipt** — calibrated meaning-level grading that is required only when the scenario grading profile contains a semantic rubric identity **and** deterministic grading has passed.

Semantic grading remains subordinate to deterministic grading. It can narrow deterministic PASS into semantic FAIL or evaluator uncertainty, but it cannot rescue deterministic failure and can never create critical policy authority.

```text
exact scenario contract
        ↓ identity check + grading-profile derivation
ScenarioGradingProfile
        ├─ semantic rubric identity / explicit absence
        └─ side-effect contract identity / explicit absence
        ↓
bound TrialEvidence schema + exact final evidence root
        ↓
deterministic oracle snapshots
        ├─ deterministic FAIL ───────────────→ trial FAIL
        │                                     semantic grading short-circuits
        └─ deterministic PASS
             ↓ profile requires semantic?
             ├─ no  ─────────────────────────→ trial PASS
             └─ yes → exact SemanticJudgmentReceipt
                        ├─ PASS ──────────────→ trial PASS
                        ├─ FAIL ──────────────→ trial FAIL, non-critical
                        └─ ABSTAIN ───────────→ trial INCONCLUSIVE
        ↓ recomputed with exact k + confidence_z
reliability statistics
        ↓ + frozen ReleasePolicy
release-gate decision + reasons
        ↓ canonical domain-separated hash
report_root
```

## Scenario grading profile

`ScenarioGradingProfile` is a deliberately minimal disclosure surface. It answers only, "Which report-level grading stages must exist for this exact scenario?"

For every non-`BLOCKED` trial, v4 enforces:

- `policy` and `outcome` must both exist exactly once;
- `side-effect-idempotency` must exist when `side_effect_idempotency_identity` is present and must be absent when the profile says no side-effect contract is configured;
- if deterministic grading fails, semantic grading must be absent even when a rubric is configured because runtime short-circuits the semantic judge;
- if deterministic grading passes and `semantic_rubric_identity` is present, one semantic judgment is required;
- if no semantic rubric is configured, semantic judgment evidence is not valid;
- any semantic receipt carried by the report must bind the exact rubric identity committed by the profile.

Unknown additional deterministic oracle names remain extensible. The profile controls only framework-known grading stages whose required presence is determined by the scenario contract.

The profile is included in `report_root`, so unacknowledged profile changes alter the report content identity. As with the rest of the report, this is ordinary integrity hashing, not authenticated authorship.

## Construction-time verification with the exact scenario

`AssuranceReport.from_session()` now requires the exact `EvaluationScenario`:

```python
report = AssuranceReport.from_session(
    session_result,
    scenario=scenario,
    release_policy=policy,
)
```

Construction first snapshots and revalidates the supplied scenario and requires:

```text
scenario.identity == session.scenario_identity
```

A caller therefore cannot generate a v4 report for one session while supplying a different grading contract.

For each non-`BLOCKED` trial, construction now reuses the same **pre-grading closure** that `TrialRunner` requires before deterministic oracle execution. This is intentionally one shared runtime boundary rather than a second, partially duplicated verifier list. The ordering is behavior-bearing and remains:

1. reject evidence that already contains `EVALUATION_ERROR` or `RUNTIME_ERROR` as impossible for a resolved trial;
2. `verify_attack_delivery(scenario, evidence)` — adversarial scenarios must prove one exact controlled delivery;
3. `verify_protocol_delivery(evidence)` — every present protocol-delivery receipt must be a supported, semantically valid bridge relation;
4. `verify_retrieval_delivery(scenario, evidence)` — a configured retrieval contract must close its exact request/delivery/result relation;
5. `verify_side_effect_observation(scenario, evidence)` — a configured side-effect contract must close its observation relation and absence is enforced for ordinary scenarios;
6. `verify_approval_intent(scenario, evidence)` — configured stronger approval intent must close its exact request→decision→continuation relation before deterministic grading.

After that shared pre-grading closure succeeds, report construction performs the post-deterministic checks that cannot live in the shared boundary:

- the side-effect oracle's presence must match the grading profile;
- `verify_semantic_judgment(scenario, evidence)` validates semantic event authority, exact scenario/rubric identity, pre-semantic evidence root, and the exact judge-input relation when a semantic receipt is present;
- semantic field presence must match the receipt committed by final evidence;
- completion evidence root, subject identity, scenario identity, trial-ID uniqueness, oracle criticality, reliability, and gate derivation retain their existing checks.

Historical `BLOCKED` trials deliberately do **not** have their failed precondition re-run as though it must now succeed. They remain valid report inputs only when they carry no completed oracle results or finalized semantic authority, preserving evaluator/runtime uncertainty instead of rewriting history.

This construction boundary is intentionally stronger than loading a standalone report because construction still has the full scenario and full trial evidence available.

## Per-trial record

For each trial the report records:

- `trial_id`;
- exact final `evidence_root`;
- terminal trial verdict;
- deterministic oracle snapshots: unique oracle name, verdict, reasons, and critical flag;
- optional full `SemanticJudgmentReceipt`.

The runtime contract also constrains known framework-oracle criticality. `policy` and `side-effect-idempotency` are critical exactly when they fail; `outcome` is never critical. Report validation rechecks those structural semantics rather than trusting a serialized criticality label.

The semantic receipt binds the exact **pre-semantic** evidence root, rubric, judge profile, accepted calibration, bounded judge-input digest, structured-response digest, criterion results, derived semantic decision, and its own integrity root. The final `TrialEvidence.evidence_root` differs from the pre-semantic root because the semantic event is appended afterward.

## Session-level record

At session level v4 records:

- assurance-report schema version `agent-evals/assurance-report/v4`;
- bound `TrialEvidence` schema version;
- exact subject identity;
- exact scenario identity;
- `ScenarioGradingProfile`;
- frozen `ReleasePolicy`;
- reliability snapshot, including exact `k` and Wilson `confidence_z`;
- release-gate decision and reasons;
- a domain-separated `report_root` over all report content except the root itself.

The report-root domain is `agent-evals/assurance-report/v4\0`. V3 artifacts are rejected rather than silently interpreted under v4 hashing or grading semantics. No `TrialEvidence` schema migration is implied; v4 still binds `agent-evals/trial-evidence/v2`.

## Historical version boundary

Assurance Report v3 remains an important historical format because it added exact `confidence_z` persistence to make Wilson intervals reproducible. V2 had recorded `k` but omitted the configurable Wilson z value, so non-default confidence contracts could not round-trip exactly.

V4 retains v3's statistical closure unchanged and adds the missing scenario-derived grading-shape commitment. The migration is therefore an assurance-artifact change, not a reliability-formula or trial-evidence change.

## What is recomputed on every load

Pydantic model validation is not passive JSON parsing. A loaded v4 report must satisfy all of the following:

1. assurance-report schema is v4 and evidence schema is the supported v2 schema;
2. trial IDs are unique;
3. deterministic oracle names are unique within each trial;
4. every non-`BLOCKED` trial contains core `policy` and `outcome` results;
5. known framework-oracle criticality matches runtime semantics;
6. non-blocked deterministic oracle verdicts are resolved PASS/FAIL values;
7. `BLOCKED` cannot carry completed oracle results or finalized semantic grading authority;
8. side-effect oracle presence exactly matches `ScenarioGradingProfile.side_effect_idempotency_identity` for every non-blocked trial;
9. semantic judgment cannot coexist with deterministic failure;
10. deterministic PASS requires semantic judgment exactly when `semantic_rubric_identity` is configured;
11. semantic judgment is forbidden when the profile contains no semantic rubric;
12. any semantic receipt rubric identity matches the grading profile;
13. semantic receipt subject identity matches the report subject;
14. semantic receipt scenario identity matches the report scenario;
15. trial verdict recomputes from deterministic results plus semantic decision using strict precedence;
16. `INCONCLUSIVE` requires an abstaining semantic judgment;
17. reliability recomputes from validated trial verdicts using exact `k` and `confidence_z`;
18. critical-violation count recomputes from failed critical deterministic oracle snapshots only;
19. release-gate decision and reasons recompute from reliability, critical violations, and frozen policy;
20. the canonical v4 report root matches the complete report content, including the grading profile.

A schema-valid object that deletes a required semantic receipt, removes a required side-effect oracle, invents a semantic rubric profile, forges a verdict, changes reliability, changes confidence configuration, changes gate policy, or alters a report root therefore fails validation unless all lower-level persisted relations are coherently changed as well.

## What standalone loading still cannot prove

A v4 report still does not contain the complete event stream or the complete scenario preimage. Standalone loading therefore cannot reconstruct event-level facts such as:

- exact tool request/result chronology;
- side-effect before/after observations and operation-key binding;
- retrieval-delivery chronology;
- approval-intent chronology and evaluator-owned source roles;
- adversarial/protocol delivery relations;
- exact semantic pre-event envelope reconstruction from raw events.

Those relations are checked at `from_session()` while the full scenario/evidence objects are present and can later be re-established through exact-identity evidence replay.

The grading profile closes **presence/absence and identity requirements for report-level grading stages**. It is not a compressed replacement for scenario or evidence replay.

## Reliability integrity before release gating

`ReliabilityReport` validates direct construction: count totals reconcile, all derived metrics recompute from counts plus `k` and `confidence_z`, and stored floating-point values must be finite.

`ReleaseGate.decide(...)` validates reliability integrity immediately before applying thresholds. Release authority therefore does not depend on caller discipline, static typing, or a stale cached percentage.

A semantic FAIL is a resolved trial failure and contributes to reliability failure counts. It is not a critical policy violation. `critical_violations` is derived only from deterministic oracle snapshots marked critical after framework criticality semantics are validated.

A semantic ABSTAIN maps to `INCONCLUSIVE`, preserving evaluator uncertainty rather than converting it into subject failure.

## Example

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

report = AssuranceReport.from_session(
    session_result,
    scenario=scenario,
    release_policy=policy,
)
serialized = report.model_dump_json(indent=2)

# Parsing performs derivation checks again; it is not a passive JSON load.
verified = AssuranceReport.model_validate_json(serialized)
assert verified.schema_version == "agent-evals/assurance-report/v4"
assert verified.evidence_schema == "agent-evals/trial-evidence/v2"
assert verified.scenario_identity == scenario.identity
assert verified.grading_profile == report.grading_profile
assert verified.reliability.confidence_z == report.reliability.confidence_z
assert verified.report_root == report.report_root
```

## Completion-root binding

`EvaluatedTrial.completion_evidence_root` remains a runtime-only finalization commitment, not a persisted Assurance Report field. It prevents report construction from pairing post-finalization-mutated evidence with stale grading facts.

For semantic trials it captures the final envelope root after the terminal semantic event, while the nested semantic receipt binds the distinct pre-semantic root. This does not make returned Python evidence tamper-proof; it makes later mutation detectable at the report boundary.

## Relationship to evidence persistence and replay

An assurance report references each trial through its final `evidence_root` and binds the evidence schema that defines that root. It does not duplicate complete `TrialEvidence`.

The layers remain intentionally separate:

- `LocalEvidenceStore` verifies and returns persisted `TrialEvidence`;
- `EvidenceReplayAdapter` can submit those historical observations through deterministic grading again under exact subject/scenario identity;
- semantic replay reconstructs the pre-semantic envelope and revalidates historical semantic receipts without calling a fresh semantic model;
- v4 report construction uses the supplied exact scenario plus in-memory evidence to run the same pre-grading closure as `TrialRunner`, then validates side-effect grading shape and post-deterministic semantic relations before producing the artifact;
- standalone v4 parsing uses the grading profile to enforce which grading stages must be present, but exact evidence replay is still required to re-establish event-level chronology and receipt relations;
- `AssuranceReport` verifies session-level derivation from bound grading facts, grading profile, evidence schema/roots, exact statistical configuration, release policy, and release-gate result.

The report can answer, "Does this stored session conclusion internally follow from the grading facts, grading-shape contract, statistical contract, and policy it contains?" It cannot by itself answer, "Would fresh execution produce the same observations now?"

## Integrity boundary

`report_root` is a domain-separated SHA-256 content-integrity root. It detects unacknowledged changes relative to a trusted root value and creates a stable content identity for the report.

It is **not**:

- a digital signature;
- a MAC;
- authenticated publisher identity;
- a trusted timestamp;
- remote attestation;
- proof that the referenced evidence was honestly produced;
- proof that the persisted grading profile is an authenticated claim from a trusted publisher;
- proof that the semantic provider actually produced an embedded response;
- proof of current provider or target-system state.

An actor who can coherently rewrite an unsigned report can recompute ordinary hashes. Strong writer authentication requires a separate signing/attestation boundary. The grading profile improves internal derivation closure; it does not convert hashing into authentication.

## Failure semantics

Malformed or internally inconsistent v4 reports fail validation. There is no repair-on-read behavior and no rule that converts invalid assurance material into `ACCEPT` or `PASS`.

When historical event-level relations need to be re-established, use the integrity-verified evidence store and exact-identity replay path described in [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md). For semantic authority, see [Calibrated Semantic Judging](SEMANTIC_JUDGING.md). For side-effect assurance, see [Side-Effect Idempotency Assurance](SIDE_EFFECT_IDEMPOTENCY.md).

[← Documentation hub](README.md)
