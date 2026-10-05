# Release provenance

## Current stage: retained release subjects carry trusted-main OIDC/Sigstore provenance

The release chain retains the exact wheel and source distribution that the CI package job builds, inspects, and smoke-tests. CI writes `artifact-manifest.json` using the versioned `agent-evals/package-artifact-manifest/v1` contract and uploads the wheel, sdist, and manifest as one run-bound GitHub Actions artifact.

A separate `package-reverify` job downloads that retained artifact, recomputes size and SHA-256 values, rejects unexpected material, and installs both retained distributions without invoking `python -m build`.

A second fresh-runner `package-reproduce` job independently checks out the same workflow subject, keeps retained/rebuilt artifacts under the runner temporary directory outside the source tree, verifies the retained manifest, derives `SOURCE_DATE_EPOCH` from the exact source commit, pins `PYTHONHASHSEED=0`, rebuilds the wheel and sdist with the same repository-pinned build contract, and requires the rebuilt filenames, sizes, and SHA-256 digests to match the retained manifest exactly. Extra, missing, symlinked, size-drifted, or digest-drifted reproduced material fails closed. The aggregate `ci-gate` requires both reverification and reproducibility.

A separate `release-supply-chain` job installs the retained wheel, resolves the runtime dependency closure actually present in that clean runner, and emits canonical SPDX 2.3 JSON plus `agent-evals/release-supply-chain-evidence/v1`. The evidence binds the exact package artifact manifest digest, retained wheel digest, repository/commit/workflow/run identity, the checked-in `agent-evals/dependency-license-policy/v1` digest, the resolved package/version/license set, and a clean PASS verdict. Unknown, non-allowlisted, explicitly denied, or unapproved `LicenseRef-*` licenses fail closed.

A fresh `release-supply-chain-reverify` job downloads the retained package and supply-chain artifacts, independently installs the retained wheel, recomputes the runtime closure, and requires it to match the retained SPDX package identities, dependency relationships, licenses, package-manifest binding, and checked-in license policy. The aggregate `ci-gate` requires both supply-chain jobs in addition to package reverification and exact-byte reproducibility.

On trusted `push` executions of `refs/heads/main` only, a downstream `release-provenance` job receives GitHub OIDC/attestation write authority. Pull-request executions never enter this job and therefore never receive signing authority. The job re-verifies the retained package manifest and retained SPDX/license evidence, then uses the immutable-pinned `actions/attest` action to generate SLSA provenance for exactly five retained subjects: the wheel, sdist, package manifest, SPDX SBOM, and supply-chain evidence JSON. The resulting Sigstore bundle is retained as `release-provenance-<run_id>` together with subject/bundle checksums and per-subject verification output.

The same trusted-main job immediately verifies each subject from the local Sigstore bundle with `gh attestation verify`, requiring this repository, `.github/workflows/ci.yml`, the exact source commit, `refs/heads/main`, the default SLSA provenance predicate, and a GitHub-hosted runner. This is a cryptographic provenance claim about those exact files and the GitHub workflow identity that signed them; it is not a signature over the GitHub Release object and it is not authenticated human identity.

Publication uses a default-branch-bound `repository_dispatch` entrypoint rather than `workflow_dispatch`. This distinction is intentional: GitHub binds `repository_dispatch` to the default branch and its current event SHA, while a manual `workflow_dispatch` can select another branch or tag.

The `Publish retained release` workflow accepts only the `release-request` repository-dispatch type. The operator supplies exactly two data fields in `client_payload`: an existing version tag and an explicit successful CI run ID. The workflow checks out its own release logic at the exact dispatch-time `GITHUB_SHA`, requires `GITHUB_REF=refs/heads/main`, and never interprets request data as executable shell text.

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
3. fetches that run's latest-attempt job graph and requires exactly one successful `Reproduce package artifacts independently` job, exactly one successful `Reverify release supply-chain evidence` job, and exactly one successful `Attest retained release artifacts` job, all bound to the same commit and run attempt, so historical CI runs without provenance qualification cannot publish;
4. resolves the already-existing tag, requires it to target the CI-qualified commit, and requires the tag to equal `v<project.version>` from `pyproject.toml` at that commit;
5. downloads exactly `package-artifacts-<ci_run_id>`, `release-supply-chain-<ci_run_id>`, and `release-provenance-<ci_run_id>`;
6. reverifies the package manifest and SPDX/license evidence, checks the retained subject/bundle checksums, and cryptographically re-verifies every retained subject from the Sigstore bundle against this repository, the CI signer workflow, the exact CI commit, `refs/heads/main`, and GitHub-hosted runner policy;
7. exercises the retained sdist, revalidates the tag and release-absence state immediately before publication; and
8. publishes the retained wheel, sdist, artifact manifest, SPDX SBOM, supply-chain evidence, Sigstore bundle, checksum inventories, and verification receipts to the existing tag with `gh release create --verify-tag`.

Repository policy requires full-SHA action pins and rejects drift that reintroduces `workflow_dispatch`/`workflow_run`, interpolates `client_payload` into shell, drops default-branch SHA binding, omits exact run/artifact bindings, rebuilds packages, or drops tag verification. Ordinary CI also executes the release-candidate validator's deterministic self-test.

## Locked executable dependency environment

Trust-bearing CI now installs third-party Python dependencies only from repository-owned exact lock profiles with pip `--require-hashes`. Core Python 3.11–3.14, MCP Python 3.11, and OpenAI+MCP Python 3.11 are separate profiles so optional integration dependencies do not become implicit provider-neutral prerequisites.

The locks include the exact build frontend/backend. Package and reproducibility jobs therefore run `python -m build --no-isolation` after installing the matching hash-checked profile; retained wheels use `--no-deps`, and retained source distributions additionally use `--no-build-isolation`. Publication reuses the same core Python 3.11 dependency snapshot when exercising and reverifying retained release evidence.

These SHA-256 entries are package-file integrity constraints only. They do not authenticate the package publisher, establish signing identity, or create OIDC/DSSE/in-toto provenance. Public supported dependency ranges remain in `pyproject.toml`; the CI locks are executable assurance snapshots, not a narrowing of the package compatibility contract. See [CI dependency locks](CI_DEPENDENCY_LOCKS.md).

## Retained manifest binding

The manifest binds:

- repository (`owner/name`);
- exact 40-character source/workflow commit SHA;
- workflow name, run ID, and run attempt;
- exactly one wheel and one sdist;
- artifact filename, kind, byte size, and SHA-256 digest.

Manifest JSON is canonical and duplicate-key/extra-field sensitive. The artifact set is closed: extra, missing, renamed, reordered-by-kind, size-mutated, or digest-mutated package material fails verification.

## Integrity and authority boundary

This stage establishes a controlled publication path from an explicitly selected successful main-branch CI run to the exact retained package bytes that run produced and downstream CI reverified. It also establishes exact-byte reproducibility for those wheel/sdist outputs in a separate clean `ubuntu-24.04` runner using the same pinned build frontend/backend contract and source-derived build epoch, plus a retained SPDX 2.3 runtime SBOM and fail-closed dependency-license verdict that a separate clean runner independently reverifies. On trusted main pushes, GitHub Actions OIDC/Sigstore provenance additionally binds the exact wheel, sdist, manifest, SBOM, and supply-chain evidence to the signing repository/workflow/source identity. Publication still consumes the original retained tested bytes and retained evidence; it never rebuilds or re-signs package bytes.

SHA-256 values remain content-integrity identifiers rather than authentication by themselves. The retained Sigstore bundle adds cryptographic workflow provenance for the five attested subjects, but it does **not** authenticate a human maintainer, sign the GitHub Release entity itself, turn older unsigned evidence into signed evidence, or establish PyPI Trusted Publishing.

This stage therefore does not claim:

- a digital signature, MAC, DSSE/in-toto envelope, or non-repudiation;
- authenticated human, maintainer, runner, or publisher identity outside the GitHub execution boundary;
- a signature over the GitHub Release entity itself (the retained release assets have provenance, but the Release object is not separately signed);
- publisher authentication merely because a dependency archive matches a committed SHA-256 lock entry;
- reproducibility across arbitrary operating systems, Python implementations, builders, or dependency graphs beyond the explicitly exercised clean-runner contract;
- an independent third-party assertion that the SBOM/license contents are semantically complete or correct beyond the repository's verified generation/policy contract;
- a signed GitHub Release;
- PyPI Trusted Publishing provenance.

Those remain separate #207 slices. A later signing/attestation layer may bind the retained artifact digests and workflow/source identities, but it must not retroactively reinterpret this unsigned manifest or unsigned release as authenticated evidence.

## Intended release chain

The target chain remains:

`source commit -> tested build -> retained wheel/sdist -> SBOM -> assurance artifacts -> signed provenance/attestation -> signed GitHub Release -> optional PyPI Trusted Publishing`

The signed-provenance/attestation link is now implemented for the five retained release subjects on trusted main pushes. A separately signed GitHub Release entity and optional PyPI Trusted Publishing remain future #207 slices.

The invariant introduced here is still deliberately narrow: the CI run must retain/reverify the tested package bytes, independently reproduce those exact bytes from the same source in a fresh runner, generate a canonical SPDX/runtime-license evidence pair bound to the retained package manifest and checked-in license policy, and independently reverify that evidence in another clean job. Publication consumes only the original retained, qualified bytes and retained supply-chain evidence from the explicitly validated CI run and existing version tag; the publisher itself never rebuilds or regenerates release evidence.
