# Mutation assurance

Mutation testing is a blocking test-quality signal for selected deterministic trust kernels. It complements line/branch coverage by checking whether focused tests detect small semantic changes in code that enforces security or assurance boundaries.

## Authoritative CI contract

The CI mutation job uses `mutmut==3.8.0` on Ubuntu with Python 3.11. Mutmut 3.x requires POSIX `fork` support; this lane therefore does not claim native Windows execution. The ordinary package/runtime dependency set does not depend on Mutmut: it is a development/CI dependency only.

Every authoritative mutation run starts by deleting `mutants/`. Cached classifications from an earlier commit therefore cannot satisfy the gate. CI runs Mutmut, exports `mutants/mutmut-cicd-stats.json`, records human-readable survivor diagnostics, and evaluates the exported JSON with `.github/scripts/check_mutation_score.py`.

The checked-in minimum mutation score is **95.00%**. For an accepted run:

- `total` must be a positive exact integer;
- every exported status count must be a non-negative exact integer;
- the exported schema must match the pinned Mutmut contract exactly;
- exported status counts must sum to `total`;
- `no_tests`, `skipped`, `suspicious`, `timeout`, `check_was_interrupted_by_user`, and `segfault` must all be zero; and
- `killed / total * 100` must be at least 95.00%.

Mutmut 3.8.0 includes `not_checked` and `caught_by_type_check` in `total` but does not export those fields from `export-cicd-stats`. The repository gate therefore treats any difference between `total` and the sum of exported statuses as unreported/incomplete authority and fails closed. Type-check filtering is not enabled for this mutation lane.

Surviving mutants are part of the denominator. A survivor is not automatically waived because it appears equivalent: equivalent-mutant claims require explicit review and either a test improvement, a narrowly justified mutation exclusion attached to the relevant code, or a deliberate policy change. The minimum score must not be lowered merely to make a particular CI run pass.

The mutation job is an explicit dependency of aggregate `ci-gate`. Its score is therefore merge-blocking wherever `ci-gate` is the required branch authority. The job uploads the machine-readable statistics, Mutmut result listing, and raw Mutmut exit code for diagnosis; terminal progress output is not treated as score authority.

## Initial bounded scope

Roadmap item 33 establishes the mechanism on two pure deterministic resource-boundary kernels:

- `src/agent_evals/evidence/limits.py`, exercised by `tests/unit/test_evidence_resource_limits.py`; and
- `src/agent_evals/statistics/limits.py`, exercised by `tests/unit/test_statistics_complexity_limits.py`.

The source selection is explicit in `[tool.mutmut]` in `pyproject.toml`. Keeping the first required mutation lane bounded makes runtime predictable and makes every survivor reviewable rather than hiding signal inside a repository-wide exploratory run.

## Nonclaims

This baseline does **not** establish mutation coverage for every trust surface. In particular, it does not complete roadmap item 34's broader authority, precondition, evaluator, deterministic-oracle, receipt-verification, evidence-store, or release-gate mutation requirements. It also does not replace property/state-machine testing, coverage, static analysis, dependency auditing, integration testing, or live-system validation.

A high mutation score means the selected tests detect the generated mutations in the selected kernels under this tool/version/configuration. It is not a proof that the code is defect-free, secure under every threat model, or semantically complete.