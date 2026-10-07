# ADR 0003: Use a default-branch dispatch handoff for bot-created releases

**Status:** Accepted
**Date:** 2026-10-07
**Supersedes:** ADR 0002 trigger-transport assumption only

## Context

ADR 0002 established a separate PyPI Trusted Publishing authority domain downstream of a published,
non-draft, non-prerelease GitHub Release. It deliberately separated trusted-main evidence
verification from the final OIDC publication job and prohibited long-lived PyPI credentials.

The first real `v0.1.0` publication exposed an execution-platform constraint that static workflow
validation did not prove: the retained-byte GitHub Release publisher creates the Release with the
repository `GITHUB_TOKEN`, and GitHub suppresses ordinary recursive workflow events created by that
token. The Release was successfully published from qualified retained bytes, but the downstream
`release: published` workflow did not run.

The published GitHub Release and its retained evidence must remain the prerequisite authority. The
transport used to wake the PyPI verifier must not become a substitute trust assertion.

## Decision

Keep the native `release: published` entrypoint for Releases created outside the repository
`GITHUB_TOKEN` path, and add a second, default-branch-bound
`repository_dispatch` entrypoint named `pypi-publish-request` for the retained-byte publisher.

The retained-byte publisher emits that dispatch only after `gh release create` succeeds. The
payload is exact data containing only the already validated `version_tag` and release
`commit_sha`; it is serialized as JSON rather than interpolated into shell.

The PyPI verifier treats the dispatch only as a wake-up request. Trusted `main` code must fetch the
actual GitHub Release by tag, require it to be non-draft and non-prerelease, require the retained
release asset contract, resolve the tag, require exact equality with the authorized commit, and then
perform the existing package, SBOM/license, CI-qualification, release-statement, checksum, and
Sigstore provenance verification before any OIDC-capable job can run.

The authority split from ADR 0002 is unchanged: the verifier has no OIDC authority; the final
publisher has only same-run artifact read plus `id-token: write`, is bound to environment `pypi`,
does not checkout or execute repository code, and receives no PyPI password or API token.

The already retained and attested release-statement/v2 value
`pypi_trusted_publishing=release-event-oidc-only` remains byte-for-byte historical evidence for the
`v0.1.0` candidate. This ADR explicitly records the transport correction rather than silently
rewriting that retained statement or ADR 0002.

## Consequences

Bot-created Releases can reliably reach the PyPI verifier without a PAT, GitHub App installation
token, or new long-lived credential. The GitHub Release publisher retains its existing
`contents: write` authority and does not gain `id-token: write`.

Repository policy must require the dispatch to occur after Release publication, require the
dedicated event type, reject selectable-ref manual publication, and reject direct
`github.event.client_payload` interpolation in the PyPI workflow.

A repository dispatch can be sent by any principal with sufficient repository authority, so the
dispatch itself is intentionally non-authoritative. Publication remains fail-closed because trusted
default-branch code re-fetches the Release and independently binds its tag, commit, package, and
retained evidence before forwarding only the verified wheel and sdist to the isolated OIDC job.

## Assurance impact

The change repairs availability of the release-to-PyPI handoff without weakening
non-compensatory release qualification or merging evidence and credential authority. A forged,
stale, malformed, wrong-repository, wrong-ref, wrong-tag, or wrong-commit dispatch cannot by itself
authorize publication; validation must still establish the actual published Release and all retained
evidence predicates.

Hashes remain integrity identities rather than authentication. Historical release-statement/v1
material remains `not-enabled`; older evidence is not upgraded. BLOCKED and FAIL semantics,
evaluator authority, evidence roots, report signatures, and historical replay meaning are unchanged.

Completion of the repository change still does not establish that PyPI accepted the OIDC identity or
that a public package exists. Those are external states that require a successful real publication
and independent verification.

## Non-claims

- The `repository_dispatch` event is not authenticated release evidence and does not replace
  verification of the actual GitHub Release.
- The GitHub Release database object is not claimed to be separately cryptographically signed.
- GitHub OIDC authenticates the workflow identity accepted by PyPI; it is not a human maintainer
  signature or proof of external subject behavior.
- Repository workflow configuration does not prove the external PyPI Trusted Publisher record is
  correct.
- This decision does not retroactively reinterpret release-statement/v1, older unsigned evidence, or
  the retained `v0.1.0` release-statement/v2 bytes.
