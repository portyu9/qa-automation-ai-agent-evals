# Statistical Assurance

## Why repeated trials are mandatory

Agent outputs vary across attempts. One successful run establishes that success is possible, not that behavior is reliable.

The framework therefore treats each attempt as a trial, preserves unresolved execution separately, and aggregates resolved behavioral verdicts explicitly.

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
- `pass@k`;
- `pass^k`;
- exact `k`;
- exact positive finite Wilson `confidence_z` used to derive the interval.

When no behavioral trial resolves, the report retains maximal interval uncertainty `[0, 1]`; it does not manufacture a behavioral estimate from blocked execution.

`ReliabilityReport` is self-validating even when constructed directly. Counts must reconcile exactly, scalar types must be valid, derived rates/intervals must recompute from those counts plus `k` and `confidence_z`, and all stored floating-point statistics must be finite. `ReleaseGate` revalidates the report immediately before making a promotion decision, so stale or bypass-mutated cached percentages cannot become release authority.

### Wilson interval

The Wilson score interval is used instead of the naive normal interval because the latter behaves poorly for small samples and proportions near zero or one.

The default z value, `1.959963984540054`, corresponds approximately to a 95% two-sided confidence interval. Callers may supply another positive finite float when a different interval contract is intentional. Because `confidence_z` changes the resulting assurance claim, it is behavior-bearing statistical configuration rather than an incidental implementation parameter.

The release gate can require both a minimum number of **resolved** trials and a minimum lower Wilson bound, so `20/20` is not treated as equivalent evidence to `2/2`.

### pass@k and pass^k

Under the empirical independent-attempt approximation over resolved behavioral trials:

```text
pass@k = 1 - (1 - p)^k
pass^k = p^k
```

`pass@k` estimates at least one success in `k` attempts. `pass^k` estimates all `k` attempts succeeding. They answer different operational questions and intentionally diverge as `k` grows.

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

Assurance Report v3 persists both `k` and `confidence_z` inside its reliability snapshot. On construction and every later load, reliability is rederived from the bound trial verdicts with those exact parameters before the release gate and report root are accepted.

This is an intentional schema change from Assurance Report v2. Version 2 did not persist `confidence_z`, so a report created from a non-default Wilson configuration could not prove which interval contract produced its stored bounds. Version 3 uses a separate domain-separated report root and does not silently reinterpret a v2 artifact under v3 semantics.

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

## Current non-claims

The implementation does not yet expose formal non-inferiority testing, sequential-testing correction, multiple-hypothesis correction, hierarchical scenario modeling, or a Bayesian posterior. Those require explicit statistical contracts and should not be implied by a score table.
