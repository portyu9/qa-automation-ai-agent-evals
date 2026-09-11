# Repeated-Trial Sampling Provenance

## Status

`EvaluationSession` records a versioned `agent-evals/session-sampling/v1` contract for repeated-trial sampling, runtime/provider randomness provenance, and stopping semantics. This metadata qualifies how repeated outcomes may be interpreted; it does not change deterministic trial verdicts or the raw arithmetic stored in `ReliabilityReport`.

`agent-evals/assurance-report/v6` persists the complete session sampling object together with campaign, adapter, independence, and reset/isolation provenance. Report loading revalidates sampling/randomness/stopping relations against the ordered report trial vector; historical v5 and earlier assurance reports are not silently reinterpreted as carrying this provenance.

## Sampling policy

Version 1 distinguishes:

- `predeclared_all_attempts`: the evaluator requested a fixed set of attempts and includes every completed attempt from that campaign run;
- `external_selection`: an external process selected which attempts entered the sample; an explicit bounded basis is required;
- `unknown`: the evaluator does not claim how attempts were selected.

Normal `EvaluationSession.run(...)` executions produce `predeclared_all_attempts`. The runtime does not expose a post-hoc filter that can silently relabel a cherry-picked sample as predeclared.

This is still not a claim that the underlying task population was sampled randomly or representatively. Version 1 records attempt inclusion inside one evaluation campaign, not population-sampling validity.

## Stopping rule

Version 1 distinguishes:

- `fixed_horizon`: `planned_trials` is declared before subject execution and must equal the finalized trial vector length;
- `adaptive_sequential`: the campaign stopped under an explicitly described adaptive/sequential rule and must not claim a fixed horizon;
- `unknown`: no stopping-rule claim is available.

`EvaluationSession.run(...)` is fixed-horizon. If a direct or persisted result drops completed attempts while retaining the original horizon, validation fails. Adaptive/sequential metadata can be represented, but the current independent-attempt `pass@k` / `pass^k` interpretation refuses it rather than pretending that optional stopping is equivalent to a fixed design.

Version 1 does not implement a sequentially valid confidence sequence, alpha-spending rule, e-value, or optional-stopping correction. Those require separate explicit statistical contracts.

## Randomness provenance

Version 1 distinguishes:

- `evaluator_controlled`: a separately supplied evaluator/operator control is invoked before every subject attempt;
- `externally_controlled`: another system owns the randomness/seed semantics and an explicit basis describes that boundary;
- `unavailable`: the runtime/provider does not expose usable seed control and an explicit basis records that limitation;
- `unknown`: the evaluator makes no seed/randomness claim.

There is intentionally no convenience `seed=...` metadata field that can turn a caller assertion into evaluator-controlled provenance. The generic agent adapter contract does not itself provide a provider-neutral seed-injection operation. Therefore `evaluator_controlled` requires a separate `RandomnessControl` object that the evaluator invokes before each attempt.

The control returns only a typed `RandomnessControlObservation` containing:

- `seed_identity`: a SHA-256 identity for the control's per-attempt seed material;
- `control_evidence_identity`: a SHA-256 identity for bounded control evidence.

The evaluator constructs `agent-evals/randomness-control-receipt/v1` itself. Each receipt binds the exact campaign, attempt index, generated trial ID, subject/scenario identities, runtime adapter, subject adapter/version, randomness strategy name/version, seed identity, and bounded control-evidence identity. Receipt roots are domain-separated integrity values.

A completed evaluator-controlled sequence requires exactly one receipt per trial. Receipt roots and seed identities must be unique across attempts, and every receipt is reconstructed against the finalized campaign trial vector. Cross-campaign replay, reordered/rebound material, post-hoc mutation, or duplicate seed identities fails validation. A duplicate seed identity is rejected before the affected subject attempt executes.

## What a randomness receipt does not prove

The receipt proves only that the evaluator invoked the declared control boundary and integrity-bound the returned digest material to a specific campaign attempt. It does **not** prove that:

- an external provider honored a hidden seed;
- two distinct seed identities produce independent random streams;
- the provider/runtime is deterministic under a repeated seed;
- the evaluated environment is stationary or exchangeable;
- hidden provider, application, memory, session, or target state is absent;
- the sample is IID or representative of a wider population.

SHA-256 roots and seed identities are integrity identifiers, not signatures, MACs, authenticated operator identities, provider attestations, or non-repudiation proofs.

## Interaction with reset/isolation evidence

`IndependenceStatus.VERIFIED` continues to mean only that the framework verified the declared evaluator-owned reset/isolation receipt relation between attempts. Reset/isolation receipts and randomness-control receipts are separate evidence domains.

A reset receipt does not establish randomness provenance. A randomness receipt does not establish environmental reset. Having both still does not prove formal IID behavior, stationarity, exchangeability, unbiased sampling, or absence of hidden shared state.

`OPERATOR_ASSERTED` independence remains explicitly weaker and caller-owned. `UNVERIFIED` independence still refuses session-level independent-attempt interpretation.

## Qualification of pass@k and pass^k

`ReliabilityReport.pass_at_k` and `pass_power_k` remain deterministic algebraic transforms of the observed resolved success proportion for compatibility and replay arithmetic. Their presence is not an independence or sampling claim.

`EvaluationSessionResult.independence_qualified_metrics()` is the interpretation boundary. It requires:

1. independence status stronger than `unverified`;
2. versioned sampling metadata;
3. `predeclared_all_attempts` sampling; and
4. `fixed_horizon` stopping with a horizon that matches the finalized trial vector.

The returned qualification also exposes the explicit randomness status and any evaluator-owned randomness receipt roots or external limitation basis. `unknown` randomness remains visible as an unresolved assumption; the framework does not fabricate a seed claim merely to make the transform available.

External selection, adaptive/sequential stopping, unknown stopping provenance, or legacy session results without sampling metadata do not acquire independent-attempt interpretation through `pass@k` / `pass^k`. They may still retain raw reliability counts and arithmetic without being relabelled as behavioral failure.

Persisting these fields in assurance-report v6 does not make the algebraic transforms independently authoritative. V6 stores and revalidates the provenance needed to interpret them; it does not claim that the report hash proves the assumptions are true in the external world.

## Verdict semantics

Sampling, seed, or stopping uncertainty is statistical/evaluator provenance uncertainty. It does not convert a subject `PASS` into `FAIL`, and it does not flatten `BLOCKED` or `INCONCLUSIVE` trials into behavioral failures. Deterministic trial grading remains separate from repeated-trial statistical qualification.
