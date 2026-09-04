# Statistical Assurance

## Why repeated trials are mandatory

Agent outputs vary across attempts. One successful run establishes that success is possible, not that behavior is reliable.

The framework therefore treats each attempt as a trial, preserves unresolved execution separately, and aggregates resolved behavioral verdicts explicitly.

## Resolved versus unresolved attempts

`PASS` and `FAIL` are **resolved behavioral trials**: enough evidence existed for deterministic oracles to decide the scenario. `BLOCKED` and `INCONCLUSIVE` are not relabelled as behavioral failure merely to make arithmetic convenient.

This distinction prevents a provider outage from being reported as an agent-quality regression and prevents unavailable evidence from inflating the sample size required for release assurance.

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
- `pass^k`.

When no behavioral trial resolves, the report retains maximal interval uncertainty `[0, 1]`; it does not manufacture a behavioral estimate from blocked execution.

### Wilson interval

The Wilson score interval is used instead of the naive normal interval because the latter behaves poorly for small samples and proportions near zero or one.

The default z value corresponds approximately to a 95% two-sided confidence interval. The release gate can require both a minimum number of **resolved** trials and a minimum lower Wilson bound, so `20/20` is not treated as equivalent evidence to `2/2`.

### pass@k and pass^k

Under the empirical independent-attempt approximation over resolved behavioral trials:

```text
pass@k = 1 - (1 - p)^k
pass^k = p^k
```

`pass@k` estimates at least one success in `k` attempts. `pass^k` estimates all `k` attempts succeeding. They answer different operational questions and intentionally diverge as `k` grows.

## Paired candidate-versus-baseline comparison

Candidate and baseline outcomes must be paired under the same scenario/fixture unit. `PairedComparison` accepts only resolved `PASS`/`FAIL` pairs; `BLOCKED` or `INCONCLUSIVE` evidence must be resolved separately rather than coerced into a binomial outcome.

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

## Release-gate semantics

The gate distinguishes bad evidence from missing evidence:

- critical deterministic violation → `REJECT`;
- resolved success rate below policy → `REJECT`;
- too few resolved trials → `INCONCLUSIVE`;
- too many blocked/inconclusive attempts → `INCONCLUSIVE`;
- insufficient Wilson lower bound → `INCONCLUSIVE`;
- all required conditions closed → `ACCEPT`.

This is fail-closed for promotion without falsely describing infrastructure uncertainty as agent regression.

## Current non-claims

The implementation does not yet expose formal non-inferiority testing, sequential-testing correction, multiple-hypothesis correction, hierarchical scenario modeling, or a Bayesian posterior. Those require explicit statistical contracts and should not be implied by a score table.
