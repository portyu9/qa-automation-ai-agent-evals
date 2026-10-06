# Statistical Assurance

## Why repeated trials are mandatory

Agent outputs vary across attempts. One successful run establishes that success is possible, not that behavior is reliable.

The framework therefore treats each attempt as a trial, preserves unresolved execution separately, and aggregates resolved behavioral verdicts explicitly.

Every `EvaluationSession.run(...)` invocation has an explicit campaign identity. If the caller does not provide one, the runtime creates a collision-resistant identifier; the campaign plus attempt index is bound into each generated trial ID. This prevents separate evaluation campaigns over the same subject/scenario pair from accidentally reusing the same immutable trial/evidence-record namespace. Campaign IDs are opaque provenance identifiers, not authenticated principals, signatures, reset receipts, or evidence of statistical independence. Callers may provide a stable campaign ID when an external evaluation campaign already owns that namespace, and intentionally reusing the same campaign ID intentionally reuses that trial namespace.

Repeated execution does **not** by itself prove environmental independence. `EvaluationSession` snapshots the evaluator-owned subject/scenario contract but intentionally reuses the supplied subject adapter object; it does not reset provider state, application state, memory, external targets, or automatically apply `EvaluationScenario.initial_state`.

That distinction matters statistically. Success/failure counts and Wilson intervals remain exact summaries of the recorded resolved verdicts, but an independent-attempt interpretation of repeated outcomes—and especially the `pass@k` / `pass^k` extrapolations—requires the underlying attempts to be sufficiently independent and stationary for that approximation to be meaningful. A unique campaign identity prevents identity collisions; it is not evidence that this statistical precondition was satisfied.

## Attempt sampling, randomness, and stopping provenance

`agent-evals/session-sampling/v1` records the attempt-level statistical design separately from behavioral verdicts. Its current trust states make three questions explicit:

- **sampling policy** — whether all attempts came from a predeclared attempt set, an externally selected set, or an unknown selection process;
- **randomness status** — whether runtime/provider randomness was evaluator-controlled, externally controlled, unavailable, or unknown; and
- **stopping rule** — whether the campaign used a fixed horizon, an adaptive/sequential rule, or an unknown stopping process.

A fixed-horizon campaign records `planned_trials`; an adaptive/sequential campaign records a bounded stopping-rule basis instead. Unknown stopping provenance cannot silently claim a horizon. External selection requires an explicit basis, while unknown selection carries no asserted basis.

Evaluator-controlled randomness is a separate control boundary. The evaluator invokes a `RandomnessControl` before each attempt and constructs one `agent-evals/randomness-control-receipt/v1` receipt per attempt from bounded control observations. Those receipts bind campaign/attempt identity, trial ID, subject/scenario identities, runtime and subject-adapter identity, randomness strategy/version, a seed identity, and bounded control-evidence identity. A provider adapter cannot self-declare evaluator-controlled randomness merely by emitting a seed-like field.

The seed value is represented only by an identity digest. Distinct seed identities do not prove statistically independent random streams; a seed digest is not provider authentication, entropy attestation, or proof that a provider actually honored a seed. Externally controlled, unavailable, and unknown randomness remain explicit weaker states and cannot carry evaluator-owned control receipts.

`EvaluationSessionResult.independence_qualified_metrics()` validates this statistical provenance before returning an independent-attempt interpretation. The current implementation supports the fixed-horizon/predeclared-attempt interpretation; adaptive/sequential or externally selected samples remain representable provenance but do not silently inherit the same repeated-attempt interpretation.

### Independence qualification

`EvaluationSessionResult` records an explicit `IndependenceStatus` rather than allowing campaign identity or repeated execution to imply an independence claim:

- `unverified` is the default. No reset/isolation assertion is present, and session-level independent-attempt `pass@k` / `pass^k` interpretation is refused;
- `operator_asserted` is a weaker, explicit caller-owned assumption and requires a non-empty textual basis. The framework records that basis but does not verify it;
- `verified` requires an evaluator-owned reset/isolation receipt for every post-first attempt.

A verified campaign must have at least two trials and must supply a `ResetIsolationControl` separately from the subject adapter. Before each post-first attempt, `EvaluationSession` invokes that control with bounded context identifying the exact campaign transition, finalized predecessor evidence root, subject/scenario identities, runtime adapter name, and subject adapter/version. The control returns only a typed `ResetIsolationObservation` containing a SHA-256 identity for its bounded control evidence. The evaluator then constructs the versioned `agent-evals/reset-isolation-receipt/v1` receipt itself.

Each reset/isolation receipt is domain-separated and binds:

- campaign identity and exact attempt index;
- exact predecessor and next trial IDs;
- exact predecessor finalized evidence root;
- subject and scenario identities;
- runtime adapter name plus subject adapter/version;
- reset strategy name/version; and
- bounded control-evidence identity.

A completed verified session must contain exactly `trials - 1` receipts in transition order. `EvaluationSessionResult.validate()` rederives every receipt from the finalized trial chain and stored control provenance; missing, duplicate, replayed, cross-campaign, rebound, or post-finalization-mutated transitions fail validation. A failed reset control stops the session before the affected next subject attempt executes.

`EvaluationSessionResult.independence_qualified_metrics()` refuses `unverified` sessions. For `operator_asserted`, it returns the algebraic transforms together with the assertion basis. For `verified`, it returns the reset strategy/version and exact receipt roots together with those transforms. The raw `ReliabilityReport.pass_at_k` and `pass_power_k` fields remain deterministic algebraic transforms for backward-compatible report/replay arithmetic.

The term `verified` is intentionally narrow. It means the framework verified the declared, evaluator-controlled reset/isolation **receipt relation** and its binding to the campaign transition. The receipt does not authenticate an external target, prove that an arbitrary provider or distributed system actually returned to a desired hidden state, establish stationarity, prove absence of shared latent state, or establish formal IID behavior. A dishonest or defective operator-supplied reset implementation is not made trustworthy merely because its invocation was receipt-bound.

The subject adapter cannot also be the exact reset-control object, and ordinary `AdapterResult` evidence cannot self-declare verified independence. This separation is an evaluator API boundary, not cryptographic proof of organizational separation of duties.

## Population and sampling-frame provenance

Attempt provenance is still incomplete without saying what larger population or sampling frame the campaign is intended to represent. A campaign can have a fixed horizon, explicit randomness provenance, and verified reset/isolation receipts while saying nothing about the target population from which the observed attempts should be generalized.

Population provenance is therefore a separate trust domain. `agent-evals/population-provenance/v1` has three deliberately non-equivalent states:

- `identified` — a canonical, versioned `agent-evals/population-frame/v1` descriptor is present;
- `externally_declared` — a bounded caller/operator statement is recorded, but no identified frame is claimed; and
- `unknown` — no population claim is made.

An identified frame contains a canonical lowercase ASCII namespace, population/frame ID, explicit revision, a `definition_identity` digest supplied for external definition material, and a domain-separated `frame_identity` over the complete canonical descriptor. Changing the revision or definition digest changes the frame identity.

Those identities are integrity material, not authentication. The framework does not claim that `definition_identity` proves the existence, ownership, authenticity, completeness, or correctness of external definition bytes. An identified frame also does **not** prove that observed attempts were randomly or representatively sampled from it.

`externally_declared` intentionally carries only a bounded basis. It preserves that an operator or integration stated a population assumption without upgrading that statement into evaluator-owned verification. `unknown` carries neither a frame nor a declaration basis; unknown population provenance is a first-class state rather than an omitted field downstream consumers are expected to guess about.

### Population-aware session schema transition

Historical `agent-evals/session-sampling/v1` retains its original meaning: attempt inclusion, randomness/seed provenance, and stopping semantics. It is not silently reinterpreted as carrying population provenance.

`agent-evals/session-sampling/v2` is an additive population-aware envelope containing:

- the exact validated v1 attempt provenance;
- campaign identity;
- subject identity;
- scenario identity;
- explicit versioned population provenance; and
- a domain-separated v2 metadata root.

`PopulationBoundEvaluationSession` requires a valid `PopulationProvenance` object before delegating subject execution to the ordinary `EvaluationSession`. After that base session completes, the wrapper binds its exact v1 attempt provenance into v2 together with the validated population object.

This ordering is an evaluator API property, not a cryptographic timestamp or remote attestation. A serialized v2 artifact proves only that the recorded material is internally bound by its integrity root. Hashes alone cannot prove to an external verifier that the population assumption was chosen before outcomes were observed. Authenticated chronology or operator commitment would require a separate signed/attested evidence domain.

Population-aware qualified metrics expose the ordinary independence-qualified attempt metrics together with population schema/status/identity/basis. Population metadata is interpretive context; it does not strengthen the mathematical assumptions behind `pass@k` / `pass^k`.

In particular:

- an identified population is not evidence that attempts were sampled randomly from it;
- an external declaration is not evaluator verification;
- distinct seed identities do not prove independent random streams;
- reset/isolation receipts do not prove stationarity or absence of hidden shared state;
- a fixed horizon does not prove exchangeability; and
- no population state proves unbiased sampling, representativeness, or formal IID behavior.

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
- exact `k`; and
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

The formulas themselves do not create or verify independence. If an adapter carries state across attempts, an external target is not restored to the intended baseline, provider/session memory leaks between trials, or the evaluated process is otherwise correlated or non-stationary, the values remain arithmetic over the observed `p`. A verified reset/isolation receipt narrows one control uncertainty; it does not turn those arithmetic transforms into a formal proof of the independent-attempt model. Population provenance adds another explicit assumption boundary but likewise does not create representativeness or IID behavior.

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

Assurance Report v6 is the self-validating repeated-trial predecessor report. It persists exact reliability configuration (`k` and `confidence_z`) and a typed `SessionProvenanceSnapshot` containing campaign identity, exact independence status/basis, runtime/subject-adapter provenance, verified reset/isolation receipts where applicable, and the complete historical `agent-evals/session-sampling/v1` sampling/randomness/stopping object. V6 rederives that provenance against the ordered report trial IDs/evidence roots before accepting the report root.

V6 preserves the scenario grading-profile binding and explicit `POLICY_VIOLATION` facts from terminal `BLOCKED` evidence as bounded blocked-policy snapshots that affect non-compensatory release criticality without turning the blocked trial into completed deterministic grading. Its release decision is recomputed from validated trial/reliability/criticality material plus the frozen release policy; cached gate fields do not become authority.

Population-aware Assurance Report v7 is an additive envelope. It embeds the exact self-validating v6 predecessor report plus `agent-evals/session-sampling/v2` under a new domain-separated v7 root. V7 rechecks that campaign identity, subject identity, scenario identity, and the exact v1 attempt provenance agree across both layers before accepting its root. V6 remains historical and is never silently interpreted as if it contained population provenance.

The v7 population layer does not become release authority. The nested v6 report still owns reliability/release recomputation, and population metadata cannot rescue a critical deterministic violation, raise a weak statistical claim to verified independence, or turn `BLOCKED` / `INCONCLUSIVE` into behavioral `FAIL`.

Report roots, reset/randomness receipt roots, seed identities, population definition/frame identities, and the v2 metadata root are all integrity values. They are not signatures, authenticated human/provider identities, non-repudiation, remote attestation, proof of chronology, or proof of formal IID/representative sampling. An actor able to rewrite an unsigned artifact and recompute all hashes is outside what hash-only integrity authenticates.

The schema history is explicit rather than silently reinterpreted. Historical report versions are rejected by newer schema models rather than auto-filled with stronger provenance. V6 introduced durable repeated-trial session provenance; v7 adds population provenance without changing v6 semantics. See [Session Assurance Reports](ASSURANCE_REPORTS.md).

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

The current release gate does not use `pass@k` / `pass^k` or population provenance as acceptance thresholds, so statistical qualification does not silently change existing release decisions.

## Advanced paired inference and predeclared margins

`PairedSufficientStatistics` is a versioned integer-only 2×2 table over resolved paired PASS/FAIL outcomes. It stores no floating-point rate, interval, p-value, or verdict authority. Candidate-minus-baseline delta is derived from `candidate_only_pass - baseline_only_pass` divided by the exact pair count.

`ComparisonContract` requires a predeclared goal and margin:

- **superiority** establishes only when the conservative lower delta bound is above the positive/zero margin;
- **non-inferiority** establishes only when the conservative lower delta bound is above the negative margin;
- **equivalence** establishes only when the entire interval lies strictly inside the symmetric predeclared margin.

The interval is a two-sided Hoeffding bound for paired differences in `[-1, 1]`. It is deliberately conservative and does not assume a Gaussian variance estimate. The interpretation assumes the paired units used for inference are independent bounded draws from the target paired-unit population. It does not prove that assumption, stationarity, exchangeability, representative sampling, or correct pairing.

`BLOCKED` and `INCONCLUSIVE` are rejected from paired sufficient statistics and paired margin inference. They are not treated as candidate or baseline failures.

### Fixed-horizon power planning

`plan_paired_power(...)` computes a conservative fixed-horizon pair count from the same bounded-difference concentration contract. The caller must predeclare:

- comparison goal and margin;
- alpha;
- anticipated true paired delta; and
- target power.

The plan is self-validating: cached gap/radius fields are rederived from the exact contract, pair count, alpha, and target power. A requested design outside the alternative region fails before a plan exists, and any plan requiring more than the repository statistical work ceiling is rejected.

The power statement remains conditional on independent bounded paired units and the anticipated delta. It is not retrospective evidence that the effect size, IID assumptions, stationarity, or target population were correct.

## Multiple-hypothesis control

`adjust_p_values(...)` supports two explicit families over bounded, uniquely identified hypothesis collections:

- Holm step-down family-wise error-rate control; and
- Benjamini-Hochberg false-discovery-rate control.

Stable tie ordering uses `(p_value, hypothesis_id)`, adjusted values are monotone in the required direction, and results are restored to caller order. The method does not choose the hypothesis family after seeing outcomes and does not make exploratory family construction valid. FDR control also retains its usual dependence assumptions; this implementation does not prove those assumptions for arbitrary scenario slices.

Multiplicity adjustment is only as meaningful as the supplied p-values and predeclared family. It is not a substitute for population/sampling provenance.

## Cluster-aware estimation

`ClusterAwareEstimate` treats the cluster as the independent unit rather than pseudo-replicating attempts that share a prompt, task, tool, environment, fixture, or other declared cluster.

Each cluster contributes one equal-weight resolved success rate. Arbitrary dependence inside a cluster is permitted by the estimator; the confidence interval is a Hoeffding interval over cluster means in `[0, 1]`. Interpretation therefore assumes the supplied clusters themselves are independent and representative of the target cluster population.

A cluster with no resolved PASS/FAIL outcome is not silently dropped: construction fails. BLOCKED and INCONCLUSIVE attempts inside otherwise resolvable clusters remain explicitly counted but do not become failures or additional independent units.

This is cluster-aware estimation, not a full mixed-effects/hierarchical generative model. It does not estimate random-effect variance, cross-classified effects, shrinkage posteriors, or latent correlation structure.

## Sequential-safe monitoring

`bernoulli_confidence_sequence(...)` implements an anytime-valid sequence by assigning resolved time `t` the summable budget `alpha * 6 / (pi^2 * t^2)` and applying a two-sided Hoeffding interval. By the union bound, simultaneous coverage over all resolved times is at least `1-alpha` under independent bounded resolved observations.

BLOCKED and INCONCLUSIVE attempts advance wall/campaign attempt order and their own counters but do not advance resolved Bernoulli time. Unresolved steps receive zero new alpha allocation and repeat the current interval.

This construction does **not** make informative missingness ignorable. If the probability of becoming BLOCKED/INCONCLUSIVE depends on the latent behavioral outcome, the resolved-outcome sequence may not represent the intended population. The caller must analyze that availability/missingness process separately.

## Campaign drift and change-point scanning

`detect_binary_change_point(...)` scans a predeclared ordered resolved PASS/FAIL campaign for one rate shift. Candidate split points must leave the configured minimum number of trials on both sides. Each split receives a bounded two-sample Hoeffding upper bound, and the full scan uses Bonferroni correction across all admissible splits.

The detector can therefore flag a large corrected historical rate shift without pretending to identify a causal mechanism. It refuses BLOCKED/INCONCLUSIVE attempts rather than folding provider/evaluator uncertainty into behavioral drift.

The scan is post-hoc change-point detection, not a proof of stationarity before/after the split, root cause, seasonality handling, causal attribution, or arbitrary multi-break segmentation.

## Operational tail distributions

`OperationalSummary` records explicit per-attempt latency, cost, tool-call, and retry observations and derives deterministic nearest-rank p50/p95/p99 values. Inclusion policy is explicit:

- `all_attempts` includes resolved and unresolved attempts in the operational distribution;
- `resolved_only` excludes BLOCKED/INCONCLUSIVE attempts but retains exact exclusion counts.

The release gate defaults fail-closed when a resolved-only summary excluded unresolved attempts: unless policy explicitly allows that exclusion, the result is `INCONCLUSIVE`, not a clean operational acceptance. Resolved tail-threshold violations are `REJECT`.

Cost values remain as trustworthy as their upstream telemetry/pricing provenance. A numeric tail does not authenticate provider billing, tokenizer correctness, or price-table freshness.

## Worst-slice and risk-family release gates

`SliceReleaseGate` applies the existing non-compensatory `ReleaseGate` independently to every declared slice. It also groups slices into named risk families, reports the worst slice by Wilson lower bound/success rate, and can require that specific risk families are present.

One rejected slice makes the overall result `REJECT`; strong performance elsewhere cannot compensate. A missing required family or any inconclusive slice makes the overall result `INCONCLUSIVE` unless another slice already requires rejection. Critical deterministic violations retain their existing non-compensatory priority.

Slice identity/family labels are bounded evaluator inputs. This gate does not prove that a slice registry is complete, unbiased, immutable, or chosen before outcomes were seen. Scenario-registry governance remains a separate assurance domain.

## Cross-language-stable sufficient statistics

`BinarySufficientStatistics` and `PairedSufficientStatistics` serialize exact integer count material as canonical sorted-key ASCII JSON under explicit schema versions and domain-separated roots. Presentation rates, deltas, intervals, and tail values are derived rather than stored as authoritative statistical inputs.

These roots provide integrity relationships only. They are not signatures, authenticated producer identity, trusted timestamps, proof of chronology, or protection against an actor who can rewrite unsigned material and recompute hashes.

## Test vectors and failure behavior

Deterministic unit vectors cover:

- canonical integer sufficient-statistic JSON and root stability;
- unresolved paired-outcome rejection;
- small-sample positive deltas that remain unestablished;
- superiority, non-inferiority, and equivalence boundaries;
- conservative power planning and forged-cache rejection;
- known Holm and Benjamini-Hochberg adjusted-p vectors;
- duplicate-hypothesis rejection;
- resistance to cluster pseudo-replication;
- unresolved cluster accounting;
- confidence-sequence alpha spending only on resolved updates;
- corrected large-shift detection, stationary-noise non-detection, and unresolved drift refusal;
- deterministic operational quantiles;
- unresolved operational exclusion producing `INCONCLUSIVE`;
- non-compensatory worst-slice/risk-family rejection; and
- missing required risk families producing `INCONCLUSIVE`.

Malformed types, contradictory derived fields, unsupported work sizes, empty required inputs, and unresolved outcomes in methods that require resolved binary observations fail before a statistical/release claim exists.

## Current non-claims

The implementation still does not expose formal IID proof, authenticated reset/randomness/operator identity, external-target reset attestation, authenticated population-registry truth, cryptographic pre-outcome population commitment, proof of representative or unbiased population sampling, a full hierarchical/mixed-effects generative model, arbitrary dependence-robust FDR guarantees, causal drift attribution, multi-change-point segmentation, informative-missingness correction, Bayesian posterior inference, authenticated statistical chronology, or authenticated cross-language producer identity.

The conservative advanced methods provide explicit contracts under stated assumptions; they do not verify those assumptions merely because the arithmetic succeeds.

A future versioned scenario registry may provide canonical population-definition and slice-family material whose digest can be referenced by evaluator contracts. Registry membership alone must not silently upgrade a frame or slice set to representative sampling, authenticated truth, pre-outcome commitment, completeness, or evaluator verification; any stronger registry authority must be explicit, versioned, and independently verified through its own trust domain.
