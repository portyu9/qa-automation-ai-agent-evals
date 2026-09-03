# Statistical Assurance

## Why repeated trials are mandatory

Agent outputs vary across attempts. One successful run establishes that success is possible, not that behavior is reliable.

The framework therefore treats each attempt as a trial and aggregates verdicts explicitly.

## Current reliability metrics

`ReliabilityReport` records:

- trial count;
- PASS count;
- FAIL count;
- BLOCKED count;
- INCONCLUSIVE count;
- empirical success rate;
- Wilson score interval for the Bernoulli PASS proportion;
- `pass@k`;
- `pass^k`.

### Wilson interval

The Wilson score interval is used instead of the naive normal interval because the latter behaves poorly for small samples and proportions near zero or one.

The default z value corresponds approximately to a 95% two-sided confidence interval.

The release gate can require a minimum lower Wilson bound. This makes `20/20 passed` different from `2/2 passed` even though both have an empirical success rate of 100%.

### pass@k

Under the empirical independent-attempt approximation:

```text
pass@k = 1 - (1 - p)^k
```

It estimates the probability that at least one of `k` attempts succeeds.

### pass^k

```text
pass^k = p^k
```

It estimates the probability that all `k` attempts succeed.

These metrics intentionally diverge as `k` grows. A system optimized for "one of several attempts will work" is not equivalent to a system expected to behave correctly every time.

## Paired candidate-versus-baseline comparison

When comparing an agent candidate against a baseline, the repository uses paired trial outcomes. Pairing keeps scenario/fixture identity aligned and focuses inference on discordant outcomes:

```text
baseline PASS / candidate PASS
baseline PASS / candidate not-PASS
baseline not-PASS / candidate PASS
baseline not-PASS / candidate not-PASS
```

`PairedComparison` uses a two-sided exact McNemar/binomial test over the discordant pairs. No asymptotic approximation or external statistics package is required.

At the configured alpha:

- significantly more candidate-only passes → `IMPROVED`;
- significantly more baseline-only passes → `REGRESSED`;
- otherwise → `INCONCLUSIVE`.

`INCONCLUSIVE` is intentional. A raw positive percentage delta is not enough to claim an established improvement.

## What the current comparison does not claim

The current implementation does not yet expose a formal non-inferiority test, sequential testing correction, multiple-hypothesis correction, hierarchical scenario modeling, or Bayesian posterior. Those require explicit statistical contracts and should not be implied by a simple score table.

## Release gate interaction

Statistical improvement cannot override critical safety evidence. Candidate quality and candidate eligibility are separate conclusions.

A candidate may therefore be statistically better on task success while still receiving a release `REJECT` because it introduced an authorization violation.
