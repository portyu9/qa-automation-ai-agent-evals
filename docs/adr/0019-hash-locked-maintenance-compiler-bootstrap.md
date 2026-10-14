# ADR 0019: Hash-lock executable maintenance compilers separately from runtime CI

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** None

## Context

OpenSSF Scorecard alert #16 identifies the un-hashed command
`python -m pip install ... pip==25.3 pip-tools==7.5.2` in
`.github/workflows/dependency-locks.yml`. This is a genuine artifact
integrity gap in the **lock compiler's executable bootstrap**, independent
of the already hash-locked runtime/test snapshots. The existing
`requirements/locks/core-py311.txt` through `core-py314.txt` pin
`pip==26.2.1`, whereas the deterministic maintenance generator asserts
`pip==25.3` and `pip-tools==7.5.2`. Substituting runtime locks,
omitting transitive dependencies, or using `--no-deps` would invalidate
that compiler identity or silently weaken executable-integrity evidence.

Before branching, the lineage-and-salvage preflight verified exact accepted
`main@28df1b7d44049bd9ec7b8dbaf593ba0987f348ac`, zero open PRs,
only the `main` branch, and no uniquely divergent/superseded implementation
left behind. Accepted historical work #296, #306, #342–#346, #350, #351,
#354 and #356 was explicitly preserved. Baseline blobs included
`dependency-locks.yml` `28cfb0277ad86ed575929308f9f381c1ba557ac2`,
generator `5d90aa2f132fef9b2575ec11234300a27d8fc145`,
workflow validator `344bc885f3b40cc721dbade8b75a5b210d7c9098`,
and trusted publisher `025a4abec110f3c5802e81f161a21be4979db173`.
Only one branch `security/compiler-hash-bootstrap-20261014` was created,
paired with draft PR #357.

## Decision

1. Keep the compiler's exact accepted `pip==25.3` and
   `pip-tools==7.5.2` identities in a reviewed **input-only**
   `requirements/compiler/bootstrap.in`; no executable workflow
   installs that unhashed input file.
2. Create separate reviewed, transitive SHA-256 closures
   `requirements/compiler/bootstrap-py311.txt` through `bootstrap-py314.txt`.
   The authentic read-only, no-secret candidate generator
   [run 38597296896](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38597296896)
   generated all four under the target GitHub Actions Python interpreters.
   The four package closures were identical at capture time: build 1.6.1,
   click 8.5.0, packaging 26.3, pip 25.3, pip-tools 7.5.2,
   pyproject-hooks 1.3.3, setuptools 84.0.0 and wheel 0.48.0.
   Each of eight exact pins was accompanied by two SHA-256 package-file
   hashes; these were extracted from authentic job output, not invented.
3. Execute the twelve existing Dependabot profile/boundary compiler
   matrix jobs only after installing the **matrix-interpreter-selected
   reviewed lock with `pip --require-hashes`**. Explicitly assert the
   two compiler distribution versions at runtime. Never fall back to
   un-hashed `pip install` or substitute the runtime CI dependency locks.
4. Bind a repository-owned compiler policy validator and adversarial
   self-test to the existing required `Repository policy` CI job and
   mandatory scanner inventory. It must reject missing/different closures,
   hash omissions/malformations, incorrect interpreter and source
   binding, drift from exact compiler versions or the eight transitive
   pins, untrusted index options, un-hashed compiler fallback or
   unintended compiler install operations.
5. Permit a **temporary read-only PR candidate generator** to resolve
   initial lock files and validate installation under the four target
   interpreters. This generator has no publishing capability and produces
   proposals, not authority. **Delete it from the final PR before merge.**
   No accepted workflow may continue to run the unauthenticated generator.

## Consequences

Dependabot's existing per-profile generation, artifact naming, selected
runtime Python versions, trusted downstream publisher and source-identity
verification remain unaltered. A compiler closure change now requires
review of exact hashes, direct input, transitive identities, validator,
compatibility boundaries and CI qualification. The project does not
need to install all runtime/test dependencies to run the compiler; the
eight-package compiler bootstrap is a separate, narrow, hash-checked
executable dependency graph.

The hash-pinned compiler can still run untrusted dependency resolution
inputs in the existing unprivileged Dependabot PR generation context.
The trusted publisher still treats those generated artifacts only as
untrusted data and independently verifies the signed source and output.

## Assurance impact

This closes the un-hashed **package-file integrity** control for the
specific compiler bootstrap without extending any evaluator, agent,
security-scanner or release trust authority. The source locks, tests,
CI policy and trusted publisher are separate controls. Release
qualification and the historical evidence domains retain their existing
non-compensatory, fail-closed invariants.

## Non-claims

A SHA-256 package digest is **not** authentication of package publishers,
malware freedom, signed provenance, or proof that a lock's dependency
selection is safe. Candidate generator results were not themselves
authoritative until the exact hashes were committed and the maintained
workflow was requalified. The ephemeral generator is not a production
feature. This ADR does not declare Scorecard alert #16 closed until a
genuine accepted-main scanner result confirms its state. Nor does it
solve repository-admin Code-Review/Branch-Protection alerts, Scorecard
detector limitations for local source installs, age-based Maintained
findings, or OpenSSF Best Practices registration.
