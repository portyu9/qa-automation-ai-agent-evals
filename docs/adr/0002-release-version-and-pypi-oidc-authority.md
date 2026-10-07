# ADR 0002: Separate version preparation and PyPI OIDC publication authority

**Status:** Accepted
**Date:** 2026-10-07
**Supersedes:** None

## Context

The accepted release chain already separates tested-byte production, trusted-main CI qualification,
Sigstore provenance, and GitHub Release publication. The GitHub Release publisher is deliberately
default-branch-bound, consumes retained CI-tested artifacts without rebuilding, and has
`contents: write` but no OIDC signing authority.

The remaining roadmap work requires version/release automation and PyPI Trusted Publishing without
collapsing those authority domains or turning long-lived credentials into a new release root of
trust. Historical `agent-evals/release-statement/v1` material also explicitly records PyPI as
`not-enabled`, so enabling a repository-side PyPI path cannot silently change the meaning of v1.

## Decision

Add two separate automation surfaces.

First, `Prepare release version` is a read-only, default-branch-bound
`repository_dispatch` workflow. It validates one canonical stable SemVer target, applies the
version change only in its ephemeral checkout, and retains a canonical
`agent-evals/release-version-plan/v1` plus deterministic patch. It receives no repository write,
pull-request write, OIDC, or attestation authority. The repository's normal pull-request path remains
the only route for accepting a version bump.

Second, `Publish package to PyPI` runs only after a non-draft, non-prerelease GitHub Release is
published. It has only `contents: read` and `id-token: write`, is bound to the GitHub environment
`pypi`, and executes trusted default-branch code rather than release-tag code. The tag commit is
treated as data. Before invoking the immutable-pinned PyPA publisher, the workflow requires exact
tag/package binding, release-statement/v2, retained package/SBOM/license/CI qualification evidence,
subject and bundle checksums, and successful Sigstore verification of all seven attested release
subjects. Only the verified wheel and sdist enter the upload directory. No PyPI password, API token,
alternate repository URL, rebuild, or skip-existing behavior is permitted.

Version the release statement to `agent-evals/release-statement/v2` for new trusted-main runs with
`pypi_trusted_publishing=release-event-oidc-only`. The verifier keeps exact v1 reconstruction with
`pypi_trusted_publishing=not-enabled`; historical v1 evidence is never reinterpreted as v2.

The existing GitHub Release publisher remains a separate write-capable workflow and does not gain
`id-token: write` or PyPI publication authority.

## Consequences

Repository-side PyPI Trusted Publishing is now configured, but actual activation still requires the
external PyPI Trusted Publisher record for project `qa-automation-ai-agent-evals`, GitHub owner
`portyu9`, repository `qa-automation-ai-agent-evals`, workflow `publish-pypi.yml`, and
environment `pypi`. An actual GitHub Release and successful PyPI publication remain external states
that must be verified separately.

Version preparation intentionally produces a patch artifact instead of pushing a branch or opening a
GITHUB_TOKEN-authored pull request. That preserves the protected pull-request/CI path and avoids the
GitHub behavior where events created by the repository GITHUB_TOKEN do not provide the ordinary PR
CI signal expected by this repository.

The public compatibility document no longer embeds the literal package version. Executable version
truth remains in `pyproject.toml`, while compatibility claims remain bound to reviewed locks, CI,
and the attested release statement. Ordinary version bumps therefore do not require an unrelated
assurance-semantic ADR merely to synchronize prose.

## Assurance impact

The change adds a new external publication authority while preserving non-compensatory release
qualification. A PyPI publish is downstream of a published GitHub Release and cannot compensate for
missing package, supply-chain, qualification, release-statement, or provenance evidence.

OIDC authority is granted only to the dedicated PyPI workflow. The workflow cannot execute code from
the release tag under that authority, and the existing GitHub Release publisher cannot mint PyPI
OIDC credentials. Repository policy machine-checks both separations and rejects token-based PyPI
upload markers.

BLOCKED and FAIL semantics, evaluator authority, evidence roots, report signing, and historical replay
meaning are unchanged.

## Non-claims

- Repository workflow configuration does not prove that the external PyPI Trusted Publisher record
  exists or is correct.
- A configured OIDC path is not evidence that a PyPI release has been published.
- GitHub OIDC authenticates the workflow execution accepted by PyPI; it is not a human maintainer
  signature or proof of external subject behavior.
- The GitHub Release database object is still not claimed to be separately cryptographically signed.
- SHA-256 values remain integrity identities, not authentication by themselves.
- Historical release-statement/v1 and older unsigned evidence remain historical material under their
  original semantics.
