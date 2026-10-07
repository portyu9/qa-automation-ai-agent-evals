# Release provenance

## Current stage: retained release subjects, compatibility statement, and CI qualification evidence carry trusted-main OIDC/Sigstore provenance

Release-version preparation is also automated without granting repository write authority. The
`Prepare release version` workflow accepts only the default-branch-bound `release-preparation`
repository-dispatch event, validates a canonical stable SemVer target, and emits a canonical
`agent-evals/release-version-plan/v1` plus a deterministic `pyproject.toml` patch. It does not push
a branch, create a pull request, mint an OIDC token, or bypass the repository's pull-request rules.
A same-version request is an explicit `release-current` plan, which supports preparing the initial
0.1.0 release without inventing a version bump.

The release chain retains the exact wheel and source distribution that the CI package job builds, inspects, and smoke-tests. CI writes `artifact-manifest.json` using the versioned `agent-evals/package-artifact-manifest/v1` contract and uploads the wheel, sdist, and manifest as one run-bound GitHub Actions artifact.

A separate `package-reverify` job downloads that retained artifact, recomputes size and SHA-256 values, rejects unexpected material, and installs both retained distributions without invoking `python -m build`.

A second fresh-runner `package-reproduce` job independently checks out the same workflow subject, keeps retained/rebuilt artifacts under the runner temporary directory outside the source tree, verifies the retained manifest, derives `SOURCE_DATE_EPOCH` from the exact source commit, pins `PYTHONHASHSEED=0`, rebuilds the wheel and sdist with the same repository-pinned build contract, and requires the rebuilt filenames, sizes, and SHA-256 digests to match the retained manifest exactly. Extra, missing, symlinked, size-drifted, or digest-drifted reproduced material fails closed. The aggregate `ci-gate` requires both reverification and reproducibility.

A separate `release-supply-chain` job installs the retained wheel, resolves the runtime dependency closure actually present in that clean runner, and emits canonical SPDX 2.3 JSON plus `agent-evals/release-supply-chain-evidence/v1`. The evidence binds the exact package artifact manifest digest, retained wheel digest, repository/commit/workflow/run identity, the checked-in `agent-evals/dependency-license-policy/v1` digest, the resolved package/version/license set, and a clean PASS verdict. Unknown, non-allowlisted, explicitly denied, or unapproved `LicenseRef-*` licenses fail closed.

A fresh `release-supply-chain-reverify` job downloads the retained package and supply-chain artifacts, independently installs the retained wheel, recomputes the runtime closure, and requires it to match the retained SPDX package identities, dependency relationships, licenses, package-manifest binding, and checked-in license policy. The aggregate `ci-gate` requires both supply-chain jobs in addition to package reverification and exact-byte reproducibility.

After `ci-gate` succeeds, the ruleset-bound `Package integrity` job independently requires exact-subject CodeQL success. Only then, and only on a trusted `push` of `refs/heads/main`, `Retain CI qualification evidence` emits canonical `agent-evals/ci-qualification-evidence/v1`. The record binds the repository, exact commit SHA/ref, `CI` workflow name, run ID, run attempt, push event, and the exact logical result set for every required CI dependency plus `ci-gate` and `protected-gate`. Creation fails unless every bound result is `success`. The exact JSON is re-parsed with duplicate-key and canonical-serialization checks and retained as `ci-qualification-<run_id>`; pull-request runs never produce this trusted-main qualification artifact.

A downstream trusted-main `release-statement` job has no OIDC or attestation write authority. It hashes the exact retained wheel, sdist, package manifest, SPDX SBOM, supply-chain evidence, and CI qualification evidence; binds the exact repository/commit/ref/workflow/run identity; derives the expected `v<project.version>` tag and public `requires-python`/runtime dependency contract from `pyproject.toml`; and binds all six reviewed `core`/`mcp`/`openai-mcp` × `minimum`/`latest` Python 3.11 compatibility snapshots by path, header identity, input digest, file digest, and size. New trusted-main runs emit canonical `agent-evals/release-statement/v2`, which explicitly states `github_release_object_signature=not-claimed` and `pypi_trusted_publishing=release-event-oidc-only`. The verifier retains exact `agent-evals/release-statement/v1` reconstruction, where the PyPI field remains `not-enabled`; v1 material is never silently reinterpreted as v2. The statement is reverified from retained bytes and uploaded as `release-statement-<run_id>`.

On trusted `push` executions of `refs/heads/main` only, a downstream `release-provenance` job receives GitHub OIDC/attestation write authority. Pull-request executions never enter this job and therefore never receive signing authority. The job re-verifies the retained package manifest and retained SPDX/license evidence, then independently reverifies the retained CI qualification JSON and uses the immutable-pinned `actions/attest` action to generate SLSA provenance for exactly seven retained subjects: the wheel, sdist, package manifest, SPDX SBOM, supply-chain evidence JSON, CI qualification evidence JSON, and canonical release statement. The resulting Sigstore bundle is retained as `release-provenance-<run_id>` together with subject/bundle checksums and per-subject verification output.

The same trusted-main job immediately verifies each subject from the local Sigstore bundle with `gh attestation verify`, requiring this repository, `.github/workflows/ci.yml`, the exact source commit, `refs/heads/main`, the default SLSA provenance predicate, and a GitHub-hosted runner. For the qualification JSON, this authenticates the exact workflow-issued claim that the configured CI aggregate and protected CodeQL bridge succeeded for the bound run. It does not independently prove the semantic correctness of every test, authenticate an external target/model/provider, or authenticate a human maintainer.

Publication uses a default-branch-bound `repository_dispatch` entrypoint rather than `workflow_dispatch`. This distinction is intentional: GitHub binds `repository_dispatch` to the default branch and its current event SHA, while a manual `workflow_dispatch` can select another branch or tag.

The `Publish retained release` workflow accepts only the `release-request` repository-dispatch type. The operator supplies exactly two data fields in `client_payload`: an existing version tag and an explicit successful CI run ID. The workflow checks out its own release logic at the exact dispatch-time `GITHUB_SHA`, requires `GITHUB_REF=refs/heads/main`, and never interprets request data as executable shell text. After validating the selected CI run, it materializes only the fixed release-contract data files (`pyproject.toml` plus the six reviewed compatibility locks) from that exact CI-qualified commit under `candidate-source` via the GitHub contents API. The write-capable publisher never checks out or executes code from the dynamically selected candidate commit; release-statement recomputation still uses the candidate's exact contract bytes even if default-branch publication logic has advanced since that CI run.

A manual operator can request publication with GitHub CLI using an authenticated identity that is already authorized to create repository-dispatch events:

```bash
gh api --method POST repos/portyu9/qa-automation-ai-agent-evals/dispatches \
  --input - <<'JSON'
{"event_type":"release-request","client_payload":{"version_tag":"v0.1.0","ci_run_id":123456789}}
JSON
```

The publisher then:

1. validates the dispatch action, repository identity, exact default-branch ref/SHA, and exact two-field request payload;
2. fetches the explicitly requested Actions run and requires the canonical `CI` workflow, `push` event, `completed/success`, `main` head branch, exact `head_sha`, and positive run attempt;
3. fetches that run's latest-attempt job graph and requires exactly one successful `Reproduce package artifacts independently` job, exactly one successful `Reverify release supply-chain evidence` job, exactly one successful `Retain CI qualification evidence` job, exactly one successful `Retain release compatibility statement` job, and exactly one successful `Attest retained release artifacts` job, all bound to the same commit and run attempt, so historical CI runs without the post-gate qualification/provenance chain cannot publish;
4. resolves the already-existing tag, requires it to target the CI-qualified commit, and requires the tag to equal `v<project.version>` from `pyproject.toml` at that commit;
5. downloads exactly `package-artifacts-<ci_run_id>`, `release-supply-chain-<ci_run_id>`, `ci-qualification-<ci_run_id>`, `release-statement-<ci_run_id>`, and `release-provenance-<ci_run_id>`;
6. strictly reverifies the package manifest, SPDX/license evidence, canonical CI qualification evidence, and release statement against the requested version tag and exact retained inputs, checks the retained subject/bundle checksums, and cryptographically re-verifies every retained subject from the Sigstore bundle against this repository, the CI signer workflow, the exact CI commit, `refs/heads/main`, and GitHub-hosted runner policy;
7. exercises the retained sdist, revalidates the tag and release-absence state immediately before publication; and
8. publishes the retained wheel, sdist, artifact manifest, SPDX SBOM, supply-chain evidence, CI qualification evidence, attested release statement, Sigstore bundle, checksum inventories, and verification receipts to the existing tag with `gh release create --verify-tag`.

Repository policy requires full-SHA action pins and rejects drift that reintroduces
`workflow_dispatch`/`workflow_run` into the GitHub Release publisher, interpolates
`client_payload` into shell, drops default-branch SHA binding, omits exact run/artifact bindings,
rebuilds packages, or drops tag verification. Ordinary CI self-tests the release-candidate,
release-version, and canonical release-statement validators.

PyPI publication is a separate authority domain. `Publish package to PyPI` runs only for a
non-draft, non-prerelease GitHub Release `published` event and splits verification from credential
authority. The verification job has only `contents: read`, checks out `main` rather than the
release tag, and treats the published tag/commit only as data. Default-branch code resolves the tag,
requires package/tag equality, downloads the Release assets, requires release-statement/v2 with
`release-event-oidc-only`, materializes only the fixed source-contract files from the attested
commit, re-verifies package/SBOM/license/CI qualification/release-statement evidence, verifies
checksum inventories, and cryptographically re-verifies all seven retained subjects against the CI
Sigstore bundle. It retains only the verified wheel and sdist in a one-day same-run artifact. A
separate final job, bound to environment `pypi`, has only `actions: read` plus `id-token: write`,
does not checkout or execute repository code, downloads that two-file artifact, and invokes the PyPA
publisher.

The publisher is pinned to
`pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33`; no `user`,
`password`, PyPI API token, alternate repository URL, rebuild step, or skip-existing behavior is
allowed by repository policy. The separate GitHub Release publisher deliberately retains no
`id-token: write` authority.

## Locked executable dependency environment

Trust-bearing CI now installs third-party Python dependencies only from repository-owned exact lock profiles with pip `--require-hashes`. Core Python 3.11–3.14, MCP Python 3.11, and OpenAI+MCP Python 3.11 are separate profiles so optional integration dependencies do not become implicit provider-neutral prerequisites.

The locks include the exact build frontend/backend. Package and reproducibility jobs therefore run `python -m build --no-isolation` after installing the matching hash-checked profile; retained wheels use `--no-deps`, and retained source distributions additionally use `--no-build-isolation`. Publication reuses the same core Python 3.11 dependency snapshot when exercising and reverifying retained release evidence.

These SHA-256 entries are package-file integrity constraints only. They do not authenticate the package publisher, establish signing identity, or create OIDC/DSSE/in-toto provenance. Public supported dependency ranges remain in `pyproject.toml`; the ordinary CI locks are executable assurance snapshots, not a narrowing of the package compatibility contract. Separately, six reviewed compatibility snapshots exercise `core`, `mcp`, and `openai-mcp` at declared minimum and reviewed latest boundaries on Python 3.11. The release statement binds those exact snapshot bytes and their header/input identities so a published compatibility claim is tied to executable evidence rather than prose alone. See [CI dependency locks](CI_DEPENDENCY_LOCKS.md).

## Retained manifest binding

The manifest binds:

- repository (`owner/name`);
- exact 40-character source/workflow commit SHA;
- workflow name, run ID, and run attempt;
- exactly one wheel and one sdist;
- artifact filename, kind, byte size, and SHA-256 digest.

Manifest JSON is canonical and duplicate-key/extra-field sensitive. The artifact set is closed: extra, missing, renamed, reordered-by-kind, size-mutated, or digest-mutated package material fails verification.

## Integrity and authority boundary

This stage establishes a controlled publication path from an explicitly selected successful main-branch CI run to the exact retained package bytes that run produced and downstream CI reverified. It also establishes exact-byte reproducibility for those wheel/sdist outputs in a separate clean `ubuntu-24.04` runner using the same pinned build frontend/backend contract and source-derived build epoch, plus a retained SPDX 2.3 runtime SBOM and fail-closed dependency-license verdict that a separate clean runner independently reverifies. On trusted main pushes, GitHub Actions OIDC/Sigstore provenance additionally binds the exact wheel, sdist, manifest, SBOM, supply-chain evidence, post-gate CI qualification evidence, and canonical release statement to the signing repository/workflow/source identity. Publication still consumes the original retained tested bytes and retained evidence; it never rebuilds or re-signs package bytes.

SHA-256 values remain content-integrity identifiers rather than authentication by themselves. The retained Sigstore bundle adds cryptographic workflow provenance for the seven attested subjects, including the canonical post-gate CI qualification record and release statement. It does **not** authenticate a human maintainer, prove that an external target behaved correctly beyond what the qualified tests observed, sign the GitHub Release entity itself, turn older unsigned CI runs/evidence into signed evidence, or establish PyPI Trusted Publishing.

This stage therefore does not claim:

- human-key signatures or a non-repudiation guarantee beyond the GitHub/Sigstore workflow provenance described above (framework assurance reports/evidence manifests have their separate optional verifier-owned DSSE layer);
- authenticated human, maintainer, runner, or publisher identity outside the GitHub execution boundary;
- a signature over the GitHub Release entity itself (the retained release assets have provenance, but the Release object is not separately signed);
- publisher authentication merely because a dependency archive matches a committed SHA-256 lock entry;
- reproducibility across arbitrary operating systems, Python implementations, builders, or dependency graphs beyond the explicitly exercised clean-runner contract;
- an independent third-party assertion that the SBOM/license contents are semantically complete or correct beyond the repository's verified generation/policy contract;
- a cryptographic signature over the GitHub Release database object itself; the claim is instead limited to the attested asset set and canonical release statement;
- successful PyPI Trusted Publishing merely because the repository workflow is configured; the
  external PyPI Trusted Publisher registration and an actual publication remain separately verified
  external states.

Repository-side PyPI Trusted Publishing is configured, but activation remains conditional on the
external PyPI publisher record. The intended publisher tuple is project
`qa-automation-ai-agent-evals`, owner `portyu9`, repository
`qa-automation-ai-agent-evals`, workflow `publish-pypi.yml`, environment `pypi`. Until that
record is registered and a publication succeeds, the repository must not claim that a PyPI release
exists. This does not retroactively reinterpret older unsigned material or release-statement/v1 as
authenticated PyPI evidence.

## Intended release chain

The target chain remains:

`source commit -> tested build -> retained wheel/sdist -> SBOM -> post-gate CI qualification evidence -> executable compatibility statement -> assurance artifacts -> signed provenance/attestation -> GitHub Release carrying the exact attested asset set -> release-event OIDC verification -> PyPI Trusted Publishing`

The signed-provenance/attestation link covers the six pre-statement retained release subjects plus the canonical release statement on trusted main pushes. The statement binds the expected tag, package compatibility contract, reviewed min/latest snapshot identities, and exact retained subject digests. This is the repository's authenticated GitHub-release asset-set contract; it intentionally does not claim a separate cryptographic signature over GitHub's Release object. PyPI Trusted Publishing remains conditional on the external publisher registration and an actual successful publication.

The invariant introduced here is still deliberately narrow: the CI run must retain/reverify the tested package bytes, independently reproduce those exact bytes from the same source in a fresh runner, generate a canonical SPDX/runtime-license evidence pair bound to the retained package manifest and checked-in license policy, and independently reverify that evidence in another clean job. Publication consumes only the original retained, qualified bytes, retained supply-chain evidence, retained release statement, and retained provenance bundle from the explicitly validated CI run and existing version tag; the publisher itself never rebuilds, regenerates, re-signs, or broadens release evidence.
