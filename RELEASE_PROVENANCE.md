# Release provenance

## Current stage: exact CI-tested bytes can be published without rebuilding

The release chain retains the exact wheel and source distribution that the CI package job builds, inspects, and smoke-tests. CI writes `artifact-manifest.json` using the versioned `agent-evals/package-artifact-manifest/v1` contract and uploads the wheel, sdist, and manifest as one run-bound GitHub Actions artifact.

A separate `package-reverify` job downloads that retained artifact, recomputes size and SHA-256 values, rejects unexpected material, and installs both retained distributions without invoking `python -m build`. The aggregate `ci-gate` requires that reverification.

Publication now uses a two-workflow privilege boundary:

1. `Release request` is a manual, read-only `workflow_dispatch` surface. It accepts an explicit existing version tag and explicit successful CI run ID, creates one canonical request JSON document, and uploads it. It receives no repository write permission and does not checkout repository code, so selecting a dispatch ref cannot supply executable code to a privileged job.
2. `Publish retained release` is a `workflow_run` consumer whose privileged logic is loaded explicitly from the repository default branch. It treats the request artifact as untrusted data, verifies the triggering request workflow identity and run attempt, fetches the explicitly requested CI run, requires canonical `CI`/push/success/default-branch metadata, resolves the existing tag, requires the tag commit to equal the CI-qualified commit, and requires the tag to equal `v<project.version>` from that commit.
3. The publisher downloads exactly `package-artifacts-<ci_run_id>`, reverifies `agent-evals/package-artifact-manifest/v1` against the exact CI repository/commit/workflow/run/attempt context, installs the retained wheel and sdist, and publishes only the retained wheel, sdist, and manifest to the already-existing tag. It never rebuilds distribution bytes and fails closed if a release already exists.

Repository policy checks require full-SHA action pins and reject drift that makes the privileged publisher directly dispatchable, checks out request-ref code, omits exact run/artifact bindings, rebuilds packages, or drops the tag verification contract. Ordinary CI also executes the release-candidate validator's deterministic self-test.

## Retained manifest binding

The manifest binds:

- repository (`owner/name`);
- exact 40-character source/workflow commit SHA;
- workflow name, run ID, and run attempt;
- exactly one wheel and one sdist;
- artifact filename, kind, byte size, and SHA-256 digest.

Manifest JSON is canonical and duplicate-key/extra-field sensitive. The artifact set is closed: extra, missing, renamed, reordered-by-kind, size-mutated, or digest-mutated package material fails verification.

## Integrity and authority boundary

This stage establishes a controlled publication path from an explicitly selected successful main-branch CI run to the exact retained package bytes that run produced and the downstream CI job reverified. It prevents a release operator or release workflow from silently rebuilding different package bytes for publication.

It does **not** turn hashes, workflow metadata, or a GitHub Release into cryptographic signer authentication. SHA-256 values remain content-integrity identifiers. The serialized repository/workflow/run fields remain execution-context evidence, not an external signer attestation or non-repudiation proof.

This stage therefore does not claim:

- a digital signature, MAC, DSSE/in-toto envelope, or non-repudiation;
- authenticated human, maintainer, runner, or publisher identity outside the GitHub execution boundary;
- GitHub OIDC/keyless build provenance;
- reproducible-build equivalence against an independent rebuild;
- an SBOM or dependency/license attestation;
- a signed GitHub Release;
- PyPI Trusted Publishing provenance.

Those remain separate #207 slices. A later signing/attestation layer may bind the retained artifact digests and workflow/source identities, but it must not retroactively reinterpret this unsigned manifest or unsigned release as authenticated evidence.

## Intended release chain

The target chain remains:

`source commit -> tested build -> retained wheel/sdist -> SBOM -> assurance artifacts -> signed provenance/attestation -> signed GitHub Release -> optional PyPI Trusted Publishing`

The invariant introduced here is narrower: publication consumes the exact retained and reverified package bytes from an explicitly validated CI run and existing version tag; it does not rebuild and assume byte identity.
