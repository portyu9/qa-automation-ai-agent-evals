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
python -m pip install --no-deps --no-build-isolation -e .
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

The lock profiles are CI execution snapshots, not the package's public compatibility declaration. Supported ranges remain in `pyproject.toml`; minimum/latest compatibility lanes are a separate #207 workstream.
