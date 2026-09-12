# Release provenance

## Current stage: retained exact-tested package bytes

The release chain starts by retaining the exact wheel and source distribution that the CI package job already builds, inspects, and smoke-tests. CI writes `artifact-manifest.json` using the versioned `agent-evals/package-artifact-manifest/v1` contract and uploads the wheel, sdist, and manifest as one GitHub Actions artifact.

A separate `package-reverify` job downloads that retained artifact. It does not run `python -m build`. Instead it validates the manifest against the current workflow context, recomputes each file size and SHA-256 digest, rejects unexpected files, and smoke-tests installation from the downloaded wheel and sdist. `ci-gate` requires this downstream reverification job.

The manifest binds:

- repository (`owner/name`);
- exact 40-character source/workflow commit SHA;
- workflow name, run ID, and run attempt;
- exactly one wheel and one sdist;
- artifact filename, kind, byte size, and SHA-256 digest.

Manifest JSON is canonical and duplicate-key/extra-field sensitive. The artifact set is closed: extra, missing, renamed, reordered-by-kind, size-mutated, or digest-mutated package material fails verification.

## Integrity boundary

This stage establishes that a downstream CI job exercised the same retained package bytes described by the manifest. It also gives later release automation a concrete tested artifact set that can be selected without rebuilding different distribution files.

It does **not** make the manifest or GitHub Actions artifact a cryptographic signer attestation. SHA-256 values are content-integrity identifiers. The repository/workflow/run fields are serialized CI context, not authenticated publisher identity outside the GitHub execution/transport boundary.

This stage therefore does not claim:

- a digital signature, MAC, DSSE/in-toto envelope, or non-repudiation;
- authenticated human, maintainer, runner, or publisher identity;
- GitHub OIDC/keyless build provenance;
- reproducible-build equivalence against an independent rebuild;
- an SBOM or dependency/license attestation;
- signed GitHub Release provenance;
- PyPI Trusted Publishing provenance.

Those remain separate #207 slices. A later signing/attestation layer may bind these retained artifact digests and workflow/source identities, but it must not retroactively reinterpret this unsigned manifest as authenticated evidence.

## Intended release chain

The target chain remains:

`source commit -> tested build -> retained wheel/sdist -> SBOM -> assurance artifacts -> signed provenance/attestation -> GitHub Release -> optional PyPI Trusted Publishing`

The important invariant is that later publication consumes the retained, verified package bytes rather than rebuilding a new wheel/sdist and assuming byte identity.
