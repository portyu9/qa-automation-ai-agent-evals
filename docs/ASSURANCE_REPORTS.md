# Session Assurance Reports

## Purpose

`AssuranceReport` is a self-validating session-level artifact for review, CI handoff, replay-oriented audit, and release-decision verification. The current contract is `agent-evals/assurance-report/v6` and is domain-separated with `agent-evals/assurance-report/v6\0`.

V6 binds all report-level material that can be revalidated from the artifact itself:

- exact subject and scenario identities;
- ordered trial IDs and final evidence roots;
- scenario-derived grading profile;
- deterministic oracle snapshots for resolved trials;
- explicit policy facts retained by blocked trials;
- subordinate semantic judgment receipts when required;
- **session provenance**: campaign identity, independence qualification, adapter provenance, reset/isolation receipts, and versioned sampling/randomness/stopping metadata;
- reproducible reliability configuration and derived values;
- frozen release policy;
- recomputed release-gate decision and reasons;
- a domain-separated report integrity root over every field except the root itself.

The report is not another execution authority. It preserves and revalidates bounded conclusions; it does not manufacture evidence that was absent from the evaluated campaign.

## V6 schema boundary

V6 is a deliberate behavior-bearing transition from v5. Historical v5 reports remain historical and are rejected by the v6 model. The framework does not reinterpret v5 `pass@k` / `pass^k` values as if they had carried campaign, independence, reset, sampling, seed, or stopping provenance.

A v6 report can be constructed only from a modern `EvaluationSessionResult` that contains:

- a canonical campaign identity;
- complete runtime/subject-adapter provenance;
- `agent-evals/session-sampling/v1` metadata.

Legacy session objects missing those fields are not silently upgraded with invented `unknown` values. They remain usable for their historical/raw runtime semantics but cannot mint a v6 assurance artifact.

The evidence schema remains independently versioned as `agent-evals/trial-evidence/v2`.

## Session provenance

`SessionProvenanceSnapshot` persists the exact repeated-trial qualification supplied by the session:

- `campaign_id`;
- `independence_status` (`unverified`, `operator_asserted`, or `verified`);
- bounded `independence_basis` only for `operator_asserted`;
- runtime adapter identity;
- subject adapter identity/version;
- reset strategy identity/version and full ordered reset/isolation receipts only for `verified`;
- full `SessionSamplingMetadata`, including sampling policy, randomness status, stopping rule, and evaluator-owned randomness-control receipts when applicable.

### Operator-asserted independence

`operator_asserted` persists the exact bounded operator basis. It does **not** acquire reset receipts, evaluator verification, authenticated operator identity, or a stronger trust class merely because it is stored in a report.

### Verified reset/isolation relation

`verified` requires the exact reset strategy identity and full ordered `ResetIsolationReceipt` sequence. On construction and on every report load, the framework rederives that sequence against:

- campaign identity;
- subject/scenario identities;
- runtime and subject-adapter identities;
- ordered report trial IDs;
- ordered report evidence roots;
- reset strategy name/version.

Missing, reordered, duplicated, cross-campaign, cross-subject/scenario, or mutated reset provenance is rejected.

This relation proves only the evaluator-owned reset/isolation control relation defined by the receipt contract. It does not prove stationarity, exchangeability, absence of hidden shared state, or IID sampling.

### Sampling, randomness, and stopping provenance

V6 persists the complete `agent-evals/session-sampling/v1` object rather than copying a subset into a second report-specific grammar.

On every load, sampling metadata is revalidated against the report trial vector. This preserves the #233 distinctions between:

- predeclared-all-attempts vs external/unknown selection;
- fixed-horizon vs adaptive/sequential/unknown stopping;
- evaluator-controlled vs externally controlled/unavailable/unknown randomness.

When randomness is evaluator-controlled, the full ordered `RandomnessControlReceipt` sequence is retained and rederived against the campaign, identities, adapters, strategy identity, and ordered trial IDs. Duplicate seed identities, reordered receipts, cross-campaign replay, or mutated receipt material fail validation.

A seed identity is an integrity-bound identifier for control material. Distinct seed identities do not prove independent random streams or that a provider honored hidden seed semantics.

## Trial authority separation

V6 retains the safety properties introduced before the session-provenance transition.

For resolved trials, deterministic oracle snapshots are authoritative for deterministic grading. Semantic judgment remains subordinate: it may narrow deterministic PASS into semantic FAIL or INCONCLUSIVE, but cannot rescue a deterministic failure and never creates critical policy authority.

For `BLOCKED` trials, the report does not fabricate completed oracle results. It may preserve explicit `POLICY_VIOLATION` events already present in the blocked evidence as `BlockedPolicyViolationSnapshot` records. Those known policy facts can contribute release criticality while the trial remains `BLOCKED` in reliability statistics.

This preserves the non-compensatory safety rule without flattening evaluator uncertainty into behavioral failure.

## Construction-time verification

`AssuranceReport.from_session(...)` first requires a modern validated session-provenance snapshot, then verifies the exact scenario identity and every finalized trial relation available at construction time.

For each trial it checks:

- final evidence root equals the trial completion root;
- subject/scenario identities match the session;
- trial IDs are unique and campaign-ordered;
- blocked trials contain durable evaluator/runtime blocking evidence and no completed grading authority;
- non-blocked trials have no blocking evidence;
- shared pre-grading closure succeeds for resolved trials;
- deterministic grading recomputes exactly from scenario/evidence;
- semantic receipt/evidence relations agree when semantic grading exists.

After trial records are built, session provenance is rederived against the ordered trial IDs/evidence roots. Reliability is then recomputed from terminal verdicts, and release gating is recomputed from validated reliability, report-derived critical violations, and the frozen release policy.

No cached session reliability value, gate decision, receipt root, or report root becomes authority merely because it was serialized.

## What is recomputed on every v6 load

Standalone Pydantic loading is active verification, not passive parsing. It re-establishes:

1. exact v6 assurance schema and supported evidence schema;
2. session-provenance shape and independence-status constraints;
3. campaign-to-trial ordering;
4. sampling/randomness/stopping metadata consistency;
5. evaluator-controlled randomness receipt sequence when present;
6. verified reset/isolation receipt sequence when required;
7. unique trial IDs and valid blocked/resolved record shape;
8. deterministic oracle shape and known framework criticality semantics;
9. scenario grading-profile consistency available from serialized material;
10. semantic receipt subject/scenario/rubric relations available from the report;
11. terminal verdict derivation for non-blocked trials;
12. reliability from the trial verdict vector using exact `k` and `confidence_z`;
13. report-derived critical-violation count;
14. release-gate decision/reasons from recomputed reliability, criticality, and frozen policy;
15. the canonical v6 report root over the complete report content.

The release gate currently does not use `pass@k` or `pass^k` as an independent acceptance authority. Those fields remain deterministic arithmetic in the reliability snapshot. Session provenance prevents the report from implying that historical algebraic transforms themselves prove independent attempts.

## What standalone loading cannot prove

A v6 report still does not embed the complete scenario preimage or event stream. Standalone parsing cannot independently re-establish every event-level relation, including fresh deterministic regrading against exact event payloads, tool chronology, retrieval delivery, side-effect before/after observations, adversarial/protocol delivery, approval-interruption chronology, or semantic pre-event envelope reconstruction.

Those relations are established by `from_session()` while exact objects are present and can later be re-established from the evidence/replay layer under exact identities.

Likewise, valid reset/randomness receipts do not prove:

- formal IID sampling;
- stationarity or exchangeability;
- unbiased population sampling;
- absence of hidden shared provider/application/target state;
- provider compliance with unobservable seed semantics;
- human/operator identity or non-repudiation.

## Replay and compatibility

Evidence replay and report loading remain distinct operations:

- `LocalEvidenceStore` verifies persisted trial evidence;
- `EvidenceReplayAdapter` can replay historical evidence under exact subject/scenario identity;
- v6 report loading revalidates the report-level provenance and derivations that are actually serialized;
- historical v5 and earlier assurance schemas are not silently interpreted as v6.

An explicit future migration tool may convert a predecessor artifact only if it can supply the new provenance honestly. Mere presence of old reliability scalars is never sufficient.

## Integrity boundary

`report_root`, reset receipt roots, randomness receipt roots, evidence roots, and seed/control identities are domain-separated or content-addressed integrity values within their respective contracts. They are **not**:

- digital signatures;
- MACs;
- authenticated human/operator identity;
- authenticated provider identity;
- trusted timestamps;
- remote attestation;
- non-repudiation proofs;
- formal statistical independence proofs.

An actor able to rewrite an entire artifact can recompute ordinary hashes. Authenticated provenance requires a separate signing/attestation layer.

The v6 guarantee is narrower: the report cannot internally claim a stronger repeated-trial provenance class than the serialized campaign/reset/sampling/randomness/stopping relations can rederive, and its release decision must still recompute from verified report material while preserving `BLOCKED`/`INCONCLUSIVE` distinctions and non-compensatory safety facts.
