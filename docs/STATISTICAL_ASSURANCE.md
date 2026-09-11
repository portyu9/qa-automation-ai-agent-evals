# Statistical Assurance

## Why repeated trials are mandatory

Agent outputs vary across attempts. One successful run establishes that success is possible, not that behavior is reliable.

The framework therefore treats each attempt as a trial, preserves unresolved execution separately, and aggregates resolved behavioral verdicts explicitly.

Every `EvaluationSession.run(...)` invocation has an explicit campaign identity. If the caller does not provide one, the runtime creates a collision-resistant identifier; the campaign plus attempt index is bound into each generated trial ID. This prevents separate evaluation campaigns over the same subject/scenario pair from accidentally reusing the same immutable trial/evidence-record namespace. Campaign IDs are opaque provenance identifiers, not authenticated principals, signatures, reset receipts, or evidence of statistical independence. Callers may provide a stable campaign ID when an external evaluation campaign already owns that namespace, and intentionally reusing the same campaign ID intentionally reuses that trial namespace.

Repeated execution does **not** by itself prove environmental independence. `EvaluationSession` snapshots the evaluator-owned subject/scenario contract but intentionally reuses the supplied subject adapter object; it does not reset provider state, application state, memory, external targets, or automatically apply `EvaluationScenario.initial_state`.

That distinction matters statistically. Success/failure counts and Wilson intervals remain exact summaries of the recorded resolved verdicts, but an independent-attempt interpretation of repeated outcomes—and especially the `pass@k` / `pass^k` extrapolations—requires the underlying attempts to be sufficiently independent and stationary for that approximation to be meaningful. A unique campaign identity prevents identity collisions; it is not evidence that this statistical precondition was satisfied.

### Independence qualification

`EvaluationSessionResult` records an explicit `IndependenceStatus` rather than allowing campaign identity or repeated execution to imply an independence claim:

- `unverified` is the default. No reset/isolation assertion is present, and session-level independent-attempt `pass@k` / `pass^k` interpretation is refused;
- `operator_asserted` is a weaker, explicit caller-owned assumption and requires a non-empty textual basis. The framework records that basis but does not verify it;
- `verified` requires an evaluator-owned reset/isolation receipt for every post-first attempt.

A verified campaign must have at least two trials and must supply a `ResetIsolationControl` separately from the subject adapter. Before each post-first attempt, `EvaluationSession` invokes that control with bounded context identifying the exact campaign transition, finalized predecessor evidence root, subject/scenario identities, runtime adapter name, and subject adapter/version. The control returns only a typed `ResetIsolationObservation` containing a SHA-256 identity for its bounded control evidence. The evaluator then constructs the versioned `agent-evals/reset-isolation-receipt/v1` receipt itself.

Each receipt is domain-separated and binds:

- campaign identity and exact attempt index;
- exact predecessor and next trial IDs;
- exact predecessor finalized evidence root;
- subject and scenario identities;
- runtime adapter name plus subject adapter/version;
- reset strategy name/version;
- bounded control-evidence identity.

A completed verified session must contain exactly `trials - 1` receipts in transition order. `EvaluationSessionResult.validate()` rederives every receipt from the finalized trial chain and stored control provenance; missing, duplicate, replayed, cross-campaign, rebound, or post-finalization-mutated transitions fail validation. A failed reset control stops the session before the affected next subject attempt executes.

`EvaluationSessionResult.independence_qualified_metrics()` refuses `unverified` sessions. For `operator_asserted`, it returns the algebraic transforms together with the assertion basis. For `verified`, it returns the reset strategy/version and exact receipt roots together with those transforms. The raw `ReliabilityReport.pass_at_k` and `pass_power_k` fields remain deterministic algebraic transforms for backward-compatible report/replay arithmetic.

The term `verified` is intentionally narrow. It means the framework verified the declared, evaluator-controlled reset/isolation **receipt relation** and its binding to the campaign transition. The receipt does not authenticate an external target, prove that an arbitrary provider or distributed system actually returned to a desired hidden state, establish stationarity, prove absence of shared latent state, or establish formal IID behavior. A dishonest or defective operator-supplied reset implementation is not made trustworthy merely because its invocation was receipt-bound.

The subject adapter cannot also be the exact reset-control object, and ordinary `AdapterResult` evidence cannot self-declare verified independence. This separation is an evaluator API boundary, not cryptographic proof of organizational separation of duties.

## Resolved versus unresolved attempts

`PASS` and `FAIL` are **resolved behavioral trials**: enough evidence existed for deterministic oracles to decide the scenario. `BLOCKED` and `INCONCLUSIVE` are not relabelled as behavioral failure merely to make arithmetic convenient.

This distinction prevents a provider outage from being reported as an agent-quality regression and prevents unavailable evidence from inflating the sample size required for release assurance.

Runtime statistical entry points require exact `TrialVerdict` members. Strings, booleans, arbitrary enum-like objects, or other malformed verdict values are rejected rather than silently omitted from reliability counts or coerced into failure buckets.

## Current reliability metrics

`ReliabilityReport` records:

- total attempts;
- resolved trial count;
- PASS count;
- FAIL count;
- BLOCKED count;
- INCONCLUSIVE count;
- empirical success rate over resolved trials;
- Wilson score interval over resolved trials;
- algebraic `pass@k`;
- algebraic `pass^k`;
- exact `k`;
- exact positive finite Wilson `confidence_z` used to derive the interval.

When no behavioral trial resolves, the report retains maximal interval uncertainty `[0, 1]`; it does not manufacture a behavioral estimate from blocked execution.

`ReliabilityReport` is self-validating even when constructed directly. Counts must reconcile exactly, scalar types must be valid, derived rates/intervals must recompute from those counts plus `k` and `confidence_z`, and all stored floating-point statistics must be finite. `ReleaseGate` revalidates the report immediately before making a promotion decision, so stale or bypass-mutated cached percentages cannot become release authority.

### Wilson interval

The Wilson score interval is used instead of the naive normal interval because the latter behaves poorly for small samples and proportions near zero or one.

The default z value, `1.959963984540054`, corresponds approximately to a 95% two-sided confidence interval. Callers may supply another positive finite float when a different interval contract is intentional. Because `confidence_z` changes the resulting assurance claim, it is behavior-bearing statistical configuration rather than an incidental implementation parameter.

The release gate can require both a minimum number of **resolved** trials and a minimum lower Wilson bound, so `20/20` is not treated as equivalent evidence to `2/2`.

### pass@k and pass^k

Under an explicit empirical independent-attempt assumption over resolved behavioral trials:

```text
pass@k = 1 - (1 - p)^k
pass^k = p^k
```

`pass@k` estimates at least one success in `k` attempts. `pass^k` estimates all `k` attempts succeeding. They answer different operational questions and intentionally diverge as `k` grows.

The formulas themselves do not create or verify independence. If an adapter carries state across attempts, an external target is not restored to the intended baseline, provider/session memory leaks between trials, or the evaluated process is otherwise correlated or non-stationary, the values remain arithmetic over the observed `p`. A verified reset/isolation receipt narrows one control uncertainty; it does not turn those arithmetic transforms into a formal proof of the independent-attempt model.

## Paired candidate-versus-baseline comparison

Candidate and baseline outcomes must be paired under the same scenario/fixture unit. `PairedComparison` accepts only exact resolved `TrialVerdict.PASS` / `TrialVerdict.FAIL` pairs; `BLOCKED` or `INCONCLUSIVE` evidence must be resolved separately rather than coerced into a binomial outcome, and malformed runtime values are rejected before classification.

For resolved pairs, the implementation uses a two-sided exact McNemar/binomial test over discordant outcomes:

```text
baseline PASS / candidate PASS
baseline PASS / candidate FAIL
baseline FAIL / candidate PASS
baseline FAIL / candidate FAIL
```

At the configured alpha:

- significantly more candidate-only passes → `IMPROVED`;
- significantly more baseline-only passes → `REGRESSED`;
- otherwise → `INCONCLUSIVE`.

A raw positive percentage delta is not enough to claim an established improvement.

## Assurance-report reproducibility

The current Assurance Report schema persists exact `k` and `confidence_z` inside its reliability snapshot and rederives reliability from the bound terminal trial verdicts with those parameters before report-level release claims are accepted. The current schema also retains the predecessor schema's scenario grading-profile binding and preserves explicit `POLICY_VIOLATION` facts from terminal `BLOCKED` evidence as bounded blocked-policy snapshots that affect non-compensatory release criticality without turning the blocked trial into completed deterministic grading.

Campaign identity is indirectly bound into reports produced from campaign-bound sessions because each assurance trial record preserves the exact generated trial ID and the report root binds those records. The current report schema does not expose campaign identity as a separate authenticated or typed principal field, and this documentation does not claim that it does.

The current assurance-report schema also does not persist `EvaluationSessionResult.independence_status` or reset/isolation receipts. Consequently, a persisted assurance report must not be treated as independently carrying an `operator_asserted` or `verified` repeated-attempt claim merely because its reliability snapshot contains algebraic `pass@k` / `pass^k`. Binding independence provenance into assurance reports remains a separate schema-versioned hardening step.

The schema history is explicit rather than silently reinterpreted: the legacy schema did not persist `confidence_z`; an earlier schema added it; the predecessor schema added `ScenarioGradingProfile`; the current schema added blocked explicit-policy preservation and a new domain-separated report root. Older report schemas are rejected by the current report model rather than read under the current schema's semantics. See [Session Assurance Reports](ASSURANCE_REPORTS.md).

## Release-gate semantics

The gate distinguishes bad evidence from missing evidence:

- malformed or internally inconsistent reliability input → rejected as invalid input before a gate decision exists;
- critical deterministic violation → `REJECT`;
- resolved success rate below policy → `REJECT`;
- too few resolved trials → `INCONCLUSIVE`;
- too many blocked/inconclusive attempts → `INCONCLUSIVE`;
- insufficient Wilson lower bound → `INCONCLUSIVE`;
- all required conditions closed → `ACCEPT`.

This is fail-closed for promotion without falsely describing infrastructure uncertainty as agent regression.

The current release gate does not use `pass@k` / `pass^k` as acceptance thresholds, so explicit session independence qualification does not silently change existing release decisions.

## Current non-claims

The implementation does not expose formal IID proof, authenticated reset-operator identity, external-target reset attestation, formal non-inferiority testing, sequential-testing correction, multiple-hypothesis correction, hierarchical scenario modeling, or a Bayesian posterior. Those require explicit statistical contracts and should not be implied by a score table.
