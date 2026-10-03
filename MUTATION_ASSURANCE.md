# Mutation assurance

Mutation testing is a test-quality signal for selected deterministic trust kernels. It complements line/branch coverage by checking whether focused tests detect small semantic changes in code that enforces security or assurance boundaries.

## Authoritative ordinary-CI contract

The ordinary CI mutation job uses `mutmut==3.8.0` on Ubuntu with Python 3.11. Mutmut 3.x requires POSIX `fork` support; these lanes therefore do not claim native Windows execution. The ordinary package/runtime dependency set does not depend on Mutmut: it is a development/CI dependency only.

Every authoritative mutation run starts by deleting `mutants/`. Cached classifications from an earlier commit therefore cannot satisfy the gate. CI runs Mutmut, exports `mutants/mutmut-cicd-stats.json`, records human-readable survivor diagnostics, and evaluates the exported JSON with `.github/scripts/check_mutation_score.py`.

The checked-in minimum mutation score is **95.00%**. For an accepted campaign:

- the Mutmut process must have completed with canonical exit code `0`;
- `total` must be a positive exact integer;
- every exported status count must be a non-negative exact integer;
- the exported schema must match the pinned Mutmut contract exactly;
- exported status counts must sum to `total`;
- `no_tests`, `skipped`, `suspicious`, `timeout`, `check_was_interrupted_by_user`, and `segfault` must all be zero; and
- `killed / total * 100` must be at least 95.00%.

Mutmut 3.8.0 includes `not_checked` and `caught_by_type_check` in `total` but does not export those fields from `export-cicd-stats`. The repository gate therefore treats any difference between `total` and the sum of exported statuses as unreported/incomplete authority and fails closed. Type-check filtering is not enabled for these mutation lanes.

Surviving mutants are part of the denominator. A survivor is not automatically waived because it appears equivalent: equivalent-mutant claims require explicit review and either a test improvement, a narrowly justified mutation exclusion attached to the relevant code, or a deliberate policy change. The minimum score must not be lowered merely to make a particular run pass.

The bounded mutation job is an explicit dependency of aggregate `ci-gate`. Its score is therefore merge-blocking wherever `ci-gate` is the required branch authority. The job uploads machine-readable statistics, the Mutmut result listing, and the raw Mutmut exit code for diagnosis; terminal progress output is not treated as score authority.

## Initial bounded scope — roadmap item 33

Roadmap item 33 establishes the merge-blocking mechanism on two pure deterministic resource-boundary kernels:

- `src/agent_evals/evidence/limits.py`, exercised by focused evidence-resource tests; and
- `src/agent_evals/statistics/limits.py`, exercised by focused statistical-complexity tests.

The source selection is explicit in `[tool.mutmut]` in `pyproject.toml`. Keeping this required PR lane bounded makes runtime predictable and makes every survivor reviewable rather than hiding signal inside a repository-wide exploratory run. Item 34 does **not** widen this ordinary PR target set.

## Deep mutation assurance — roadmap item 34

Item 34 adds a separate deep-assurance layer for named deterministic authority-bearing surfaces. `.github/mutation/deep_targets.json` is the checked-in scope authority for this layer. It defines ten independently attributable campaigns covering:

1. authority and typed-resource authorization;
2. evaluation preconditions;
3. evaluator/grading/verdict derivation;
4. deterministic behavioral and side-effect oracles;
5. attack-delivery receipt/root verification;
6. retrieval receipt/root verification;
7. semantic-judgment receipt/root verification;
8. side-effect idempotency receipt/root verification;
9. local immutable evidence-store publication/verification; and
10. release-policy derivation/revalidation.

The manifest identifies exact source files and deterministic test files for every campaign. Provider/network adapters are deliberately outside this mutation scope; broadening a mutation target is not evidence that provider behavior itself has been verified.

`.github/scripts/run_deep_mutation.py` validates the manifest strictly before execution. It requires the exact campaign set, the pinned Mutmut version, checked-in source/test paths, a score floor no lower than 95.00%, bounded worker concurrency, and bounded per-campaign runtime. For every campaign it:

- starts from a deleted `mutants/` workspace;
- temporarily replaces only the repository's `[tool.mutmut]` section with that campaign's explicit source/test selection;
- runs Mutmut under a per-campaign timeout;
- exports machine-readable statistics and human-readable results;
- records every survivor's generated diff;
- delegates acceptance to the same fail-closed `.github/scripts/check_mutation_score.py` used by item 33; and
- restores `pyproject.toml` exactly before returning.

The aggregate `summary.json` binds the result to the exact Git commit, pinned tool version, SHA-256 of the checked-in manifest bytes, per-campaign counts/scores/exit statuses, and the aggregate pass state. That digest is an integrity identifier for the manifest bytes, **not** authentication, attestation, or signer identity.

## Deep workflow and authority separation

`.github/workflows/deep-mutation.yml` runs the broad campaigns separately from ordinary `ci-gate`. It has only `contents: read`, checks out the exact subject commit, uses immutable action pins, bounds the job and campaign runtimes, and retains exact-commit campaign evidence as an artifact. It runs on a weekly schedule and by explicit dispatch. Pull requests trigger it only when the deep-mutation policy/runner/workflow/tests/documentation themselves change, so normal product PR feedback does not inherit the broad campaign's cost.

A successful deep workflow is assurance evidence about test sensitivity for the selected deterministic code. It does **not** grant deployment/release authority, reinterpret an evaluator verdict, compensate for a failed mandatory release criterion, or convert `BLOCKED`/`INCONCLUSIVE` outcomes into `FAIL`/`PASS`. Release decisions remain governed by the repository's release policy and evidence hierarchy.

The ordinary item-33 mutation gate remains merge-blocking and retains its independent 95.00% floor. The deep item-34 lane cannot silently weaken or replace that gate.

## Survivor review

Meaningful surviving mutants are defects in the test-assurance story until reviewed. The preferred resolution order is:

1. add or strengthen a semantic regression test;
2. fix a real production defect if the mutant exposes one; or
3. narrowly document an equivalent/unreachable mutation when the claim can be defended from the code contract.

Blanket exclusions, survivor baselines that silently redefine success, and threshold reductions used merely to make a run pass are not acceptable substitutes for review.

## Nonclaims

Mutation assurance is selected-code test-strength evidence, not formal verification. A 95–100% score does not prove absence of defects, complete security under every threat model, correctness of unmutated modules, provider/network behavior, production deployment state, or semantic completeness.

Mutation artifacts and hashes are not authentication, signatures, attestation, or provenance of an external actor. Mutation testing does not replace property/state-machine testing, coverage, static analysis, dependency auditing, integration testing, replay, live-system validation, protocol-specific preconditions, or evidence-bound release revalidation. It does not widen adapter trust, oracle authority, or release authority.
