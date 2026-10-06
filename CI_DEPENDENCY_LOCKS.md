# CI dependency locks

The repository keeps broad supported dependency ranges in `pyproject.toml`, but executable CI does not resolve those ranges afresh. CI consumes repository-owned, exact, SHA-256-checked lock profiles under `requirements/locks/`.

The committed profiles are:

- `core-py311.txt`, `core-py312.txt`, `core-py313.txt`, and `core-py314.txt` for provider-neutral quality, mutation, package, release, and related core jobs;
- `mcp-py311.txt` for deterministic MCP protocol/auth and deep-fuzz jobs;
- `openai-mcp-py311.txt` for the OpenAI adapter lane that intentionally composes OpenAI and MCP dependencies.

Each profile includes the selected runtime/test dependencies plus the exact executable build frontend/backend used by CI, including `build==1.6.1` and `hatchling==1.32.4`. Optional provider/protocol dependencies are kept out of the core profiles.

## Execution contract

Third-party dependencies are installed with pip hash checking:

```bash
python -m pip install --require-hashes -r requirements/locks/core-py311.txt
```

The local project is then installed without dependency resolution or build isolation:

```bash
python -m pip install --no-deps --no-build-isolation .
```

Package builds use the already-installed locked backend environment:

```bash
python -m build --no-isolation
```

Retained wheels are installed with `--no-deps`; retained source distributions additionally use `--no-build-isolation`. Repository policy rejects workflow drift back to extras-based dependency resolution, the old build-only requirements install path, or isolated package builds.

`.github/scripts/validate_ci_locks.py` checks the exact profile set, interpreter binding, exact pins, SHA-256 presence for every package entry, direct-project/build requirement coverage, exact-version drift, and optional-profile separation. The ordinary CI policy job executes this validator before trust-bearing test lanes.

## Maintenance

`.github/scripts/generate_ci_lock.py` is a maintenance helper, not a release authority. Regeneration is performed under the target interpreter using the pinned maintenance compiler combination `pip==25.3` and `pip-tools==7.5.2`, one profile at a time. A regenerated lock is not accepted merely because a resolver produced it: it remains a code-reviewed repository change and must pass the lock validator plus the exact-head CI/CodeQL gates.

The generator intentionally derives direct inputs from `pyproject.toml`, the selected optional extras, the PEP 517 build requirements, and `requirements-dev-ci-build.txt`. The latter remains an input manifest for the build frontend; workflows do not install it directly.

## Integrity boundary and non-claims

`--require-hashes` makes pip reject a distribution file whose bytes do not match a committed SHA-256 digest. That is a package-file integrity constraint.

It is **not** publisher authentication, package-index authentication, a digital signature, OIDC provenance, DSSE/in-toto attestation, non-repudiation, or proof that the locked dependency itself is non-malicious. Hashes also do not replace dependency vulnerability, license, or source-review policy. Those remain separate assurance domains.

The primary lock profiles are CI execution snapshots, not the package's public compatibility declaration. Supported ranges remain in `pyproject.toml`. Ordinary quality qualification intentionally exercises the supported interpreter endpoints—Python 3.11 and Python 3.14—rather than repeating the same full quality suite on every intermediate minor. The package metadata continues to declare Python 3.11 through 3.14 support; endpoint qualification is a CI-cost/coverage policy, not a claim that 3.12 or 3.13 were removed.

## Compatibility boundary snapshots

Dependency compatibility is qualified separately through reviewed SHA-256 locks under `requirements/compatibility/` at the supported interpreter endpoints:

- core, MCP, and OpenAI+MCP profiles each have a `minimum` snapshot bound to Python 3.11 and a `latest` snapshot bound to Python 3.14;
- `minimum` pins every ranged **direct runtime** dependency to the inclusive lower bound declared in `pyproject.toml` and preserves exact direct pins exactly;
- `latest` resolves the declared direct runtime ranges under Python 3.14 at snapshot-generation time, then freezes the complete compatible closure selected for that interpreter;
- dev/build tooling remains exact in each generated closure but does not redefine the package's runtime compatibility claim;
- optional MCP/OpenAI packages stay out of provider-neutral core profiles.

Every compatibility file carries `agent-evals/dependency-compatibility-lock/v1`, profile/boundary/Python metadata, and a SHA-256 digest of the complete generator input set. The validator requires the `minimum` files to identify Python 3.11 and the `latest` files to identify Python 3.14, so a lock cannot be relabeled across interpreter boundaries. `.github/scripts/validate_dependency_compatibility.py` fails closed if the committed profile set, source-input digest, direct floors/ranges, exact pins, hashes, interpreter binding, or optional-profile separation drifts.

Ordinary qualification never resolves compatibility ranges from the network. It installs only these committed profiles with `--require-hashes`, then installs the local project with `--no-deps --no-build-isolation`. Network resolution belongs only to a maintenance step used to prepare a candidate lock for code review. A resolver-produced candidate has no qualification authority until its exact bytes are committed and pass repository policy plus exact-head CI/CodeQL.

A `latest` snapshot means “newest compatible closure selected when this reviewed snapshot was generated”; it is not a perpetual claim that the file remains newest. Regenerate/review the boundary snapshots whenever public dependency declarations, build inputs, or the generator contract change, and refresh them before a release when current compatibility is part of the release claim. Qualification itself never mutates the graph.

The first executable minimum pass intentionally exposed stale public floors: the exact MCP/OpenAI integration versions required higher `pydantic`/`httpx2` floors than the package declared. The declarations were tightened rather than allowing the minimum lane to float silently above its advertised bounds. A future declared minimum that cannot resolve or pass is a package-contract failure.

Compatibility snapshots still provide package-file integrity and executable boundary evidence, not publisher authentication. Publisher identity/provenance, vulnerability/license policy, and signed workflow qualification remain separate assurance domains.
