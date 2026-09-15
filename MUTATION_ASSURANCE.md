# Mutation assurance

Mutation testing is a **test-strength check over selected evaluator trust kernels**. It deliberately lives outside ordinary PR `ci-gate` feedback because a full mutation run is substantially more expensive than linting, type checking, deterministic tests, and package verification.

The deep-assurance lane is `.github/workflows/mutation-assurance.yml`. It is manually dispatchable and runs weekly on Ubuntu with Python 3.12. The workflow has `contents: read` permission only, uses commit-pinned actions, refuses stale `mutants/` state, and retains the exact policy, raw mutmut logs/results/stats, and evaluated report for 30 days.

## Tool and scope

The toolchain entrypoint is pinned independently in `requirements-mutation.txt`:

```text
mutmut==3.8.0
```

`mutmut` is intentionally **not** part of the normal runtime or `dev` extras. `mutation-policy.json` is the source of truth for the tool version, interpreter lane, threshold, score semantics, and trust-class target manifest. `[tool.mutmut]` in `pyproject.toml` must exactly match that target list; ordinary unit tests enforce the relationship.

The initial target set covers:

- handoff/delegated authority attenuation;
- evaluation-precondition closure;
- deterministic evaluator facade/grading composition;
- deterministic outcome/policy oracles;
- attack, retrieval, semantic, and side-effect receipt verification;
- immutable evidence-store publication/verification/replay loading;
- release-gate derivation/revalidation.

The large private evaluator implementation remains reachable through the selected facade and tests, but v1 does not claim every line in every evaluator module is directly mutated. Target expansion belongs in an explicit policy change with a new measured baseline, not an opportunistic glob.

## Score contract

`mutmut export-cicd-stats` is machine input. Progress-bar emoji or console rendering is never score authority.

Version 1 uses the intentionally conservative score:

```text
mutation score = killed / total * 100
required score >= 80.00%
required total >= 100 mutants
```

There are **no hidden denominator exclusions**. `survived` and `no_tests` remain in the denominator. Any `skipped`, `suspicious`, `timeout`, interrupted, or segfault result fails the lane. The exported status counts must add exactly to `total`; any unexplained count also fails closed. Type-check filtering and blanket `do_not_mutate` exclusions are forbidden by the v1 configuration policy.

The 80% threshold is a required floor, not a target to game and not a claim that 80% of the system is safe. Raising it should follow survivor review and stronger tests. Lowering it requires an explicit policy change with rationale and review; the workflow never rewrites its own baseline.

## Survivor review

A green score does not make survivors acceptable by default. Every baseline or material target/test change must inspect surviving mutants. For each semantically observable survivor, do one of the following:

1. add or strengthen a deterministic regression test that kills it;
2. fix a real production defect exposed by the mutant;
3. document a narrow equivalent/unreachable mutation with the exact mutant identity and reasoning before considering any future exclusion mechanism.

Version 1 intentionally provides no blanket equivalent-mutant ignore list. `mutation-artifacts/mutmut-results.txt` records survivor identities, and the retained exact commit/tool/policy allows reproduction and `mutmut show <mutant>` inspection.

## Determinism and authority

Mutation execution uses deterministic unit tests only and fixes the Hypothesis seed. It does not call providers, remote MCP servers, or Internet services. A mutation score is evidence about whether the selected local tests distinguish injected source changes; it is not a trial verdict and cannot authorize a release by itself.

The following invariants remain unchanged:

```text
BLOCKED       != FAIL
INCONCLUSIVE  != FAIL
hash/root     != authentication
mutation kill != proof of production behavior
mutation score != formal verification or security certification
```

Deterministic safety remains non-compensatory. Optional semantic judgment remains subordinate. Mutation tooling does not gain evaluator, evidence-producer, or release authority.

## Reproduction

From a clean Linux checkout:

```bash
python -m pip install -e '.[dev]' -r requirements-mutation.txt
python -m pip check
python .github/scripts/mutation_gate.py validate --check-installed
mutmut run
mutmut results
mutmut export-cicd-stats
```

The CI workflow then evaluates `mutants/mutmut-cicd-stats.json` with `.github/scripts/mutation_gate.py evaluate`, binds the report to the exact commit/run/tool/policy/stats digests, and uploads the evidence artifact.

This lane is deliberately scheduled/manual. Promoting mutation testing into required per-PR merge authority is a separate governance decision and is not implied by this implementation.
