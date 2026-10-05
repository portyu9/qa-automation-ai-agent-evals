# Release provenance

## Current stage: exact CI-tested bytes are independently reproducible and publish without rebuilding

The release chain retains the exact wheel and source distribution that the CI package job builds, inspects, and smoke-tests. CI writes `artifact-manifest.json` using the versioned `agent-evals/package-artifact-manifest/v1` contract and uploads the wheel, sdist, and manifest as one run-bound GitHub Actions artifact.

A separate `package-reverify` job downloads that retained artifact, recomputes size and SHA-256 values, rejects unexpected material, and installs both retained distributions without invoking `python -m build`.

A second fresh-runner `package-reproduce` job independently checks out the same workflow subject, keeps retained/rebuilt artifacts under the runner temporary directory outside the source tree, verifies the retained manifest, derives `SOURCE_DATE_EPOCH` from the exact source commit, pins `PYTHONHASHSEED=0`, rebuilds the wheel and sdist with the same repository-pinned build contract, and requires the rebuilt filenames, sizes, and SHA-256 digests to match the retained manifest exactly. Extra, missing, symlinked, size-drifted, or digest-drifted reproduced material fails closed. The aggregate `ci-gate` requires both reverification and reproducibility.

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
3. fetches that run's latest-attempt job graph and requires exactly one successful `Reproduce package artifacts independently` job bound to the same commit and run attempt, so pre-reproducibility historical CI runs cannot qualify for the stronger release path;
4. resolves the already-existing tag, requires it to target the CI-qualified commit, and requires the tag to equal `v<project.version>` from `pyproject.toml` at that commit;
5. downloads exactly `package-artifacts-<ci_run_id>`, reverifies `agent-evals/package-artifact-manifest/v1` against the exact CI repository/commit/workflow/run/attempt context, and installs the retained wheel and sdist;
6. revalidates the tag and release-absence state immediately before publication; and
7. publishes only the retained wheel, sdist, and manifest to the existing tag with `gh release create --verify-tag`.

Repository policy requires full-SHA action pins and rejects drift that reintroduces `workflow_dispatch`/`workflow_run`, interpolates `client_payload` into shell, drops default-branch SHA binding, omits exact run/artifact bindings, rebuilds packages, or drops tag verification. Ordinary CI also executes the release-candidate validator's deterministic self-test.

## Retained manifest binding

The manifest binds:

- repository (`owner/name`);
- exact 40-character source/workflow commit SHA;
- workflow name, run ID, and run attempt;
- exactly one wheel and one sdist;
- artifact filename, kind, byte size, and SHA-256 digest.

Manifest JSON is canonical and duplicate-key/extra-field sensitive. The artifact set is closed: extra, missing, renamed, reordered-by-kind, size-mutated, or digest-mutated package material fails verification.

## Integrity and authority boundary

This stage establishes a controlled publication path from an explicitly selected successful main-branch CI run to the exact retained package bytes that run produced and downstream CI reverified. It also establishes exact-byte reproducibility for those wheel/sdist outputs in a separate clean `ubuntu-24.04` runner using the same pinned build frontend/backend contract and source-derived build epoch. Publication still consumes the original retained tested bytes; the independent rebuild is evidence of reproducibility, never the release input.

It does **not** turn hashes, workflow metadata, repository-dispatch authorization, or a GitHub Release into cryptographic signer authentication. SHA-256 values remain content-integrity identifiers. Repository/workflow/run metadata remains execution-context evidence, not an external signer attestation or non-repudiation proof.

This stage therefore does not claim:

- a digital signature, MAC, DSSE/in-toto envelope, or non-repudiation;
- authenticated human, maintainer, runner, or publisher identity outside the GitHub execution boundary;
- GitHub OIDC/keyless build provenance;
- reproducibility across arbitrary operating systems, Python implementations, builders, or dependency graphs beyond the explicitly exercised clean-runner contract;
- an SBOM or dependency/license attestation;
- a signed GitHub Release;
- PyPI Trusted Publishing provenance.

Those remain separate #207 slices. A later signing/attestation layer may bind the retained artifact digests and workflow/source identities, but it must not retroactively reinterpret this unsigned manifest or unsigned release as authenticated evidence.

## Intended release chain

The target chain remains:

`source commit -> tested build -> retained wheel/sdist -> SBOM -> assurance artifacts -> signed provenance/attestation -> signed GitHub Release -> optional PyPI Trusted Publishing`

The invariant introduced here is narrower: the CI run must both retain/reverify the tested package bytes and independently reproduce those exact bytes from the same source in a fresh runner. Publication then consumes only the original retained, reverified, reproducibility-qualified bytes from an explicitly validated CI run and existing version tag; the publisher itself never rebuilds.
