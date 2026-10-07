# Changelog

This file records material repository changes that affect users, operators, evaluators, or assurance
claims. The repository is pre-1.0, but pre-1.0 does not permit silent reinterpretation of durable
evidence or authority semantics.

## Unreleased

### Release automation

- Add deterministic default-branch release-version preparation that emits a validated patch artifact without repository write authority.
- Add a separate PyPI Trusted Publishing workflow authorized only by a published GitHub Release. Externally created Releases may enter through the `release: published` event; the retained-byte publisher uses a default-branch-bound `pypi-publish-request` handoff after publication because GitHub suppresses ordinary recursive events created by `GITHUB_TOKEN`. Both paths execute trusted default-branch verifier code, re-verify the exact attested release subjects, and use GitHub OIDC instead of a long-lived PyPI token.
- Version the canonical release statement to v2 for the OIDC-only PyPI publication contract while retaining exact v1 verification semantics.

### Governance

- Require append-only architecture decision records (ADRs) for governed assurance-semantic changes.
- Publish explicit compatibility and deprecation contracts for framework, Python, OpenAI, MCP,
  evidence schemas, and adapters.

### Documentation

- Add a durable changelog rather than treating commit history as release notes.

## 0.1.0 — repository baseline

The package metadata declares version 0.1.0. On 2026-10-07, `v0.1.0` was published as a GitHub
Release from exact retained CI-qualified package bytes with retained SBOM, qualification evidence,
release statement, and reverified GitHub Actions OIDC/Sigstore provenance. PyPI availability remains
an external publication state that must be verified separately from this changelog.

### Included in the source baseline

- evaluator-owned evidence, deterministic policy/oracle authority, explicit BLOCKED versus FAIL,
  replay/regrade verification, and assurance reports;
- typed resource, approval, handoff, side-effect, retrieval, MCP, OAuth, semantic-calibration, and
  statistical assurance contracts;
- immutable/content-addressed evidence persistence, backup/replication observations, durable
  classified-data minimization, optional DSSE envelopes, and retained release provenance;
- deterministic core/OpenAI/MCP CI, min/latest compatibility lanes, CodeQL/security checks,
  reproducible package verification, SPDX/license evidence, and an exact-retained-byte GitHub
  Release publisher that still requires an operator-selected qualified tag/run.

### Non-claims

- The GitHub Release database object itself is not claimed cryptographically signed; the retained release assets carry the verified provenance described in the release contract.
- Source/changelog text alone does not establish PyPI publication or Trusted Publisher authentication; those remain externally verified states.
- Hashes are integrity identities, not authentication.
- Compatibility claims remain limited to the executable contracts documented in
  docs/COMPATIBILITY.md.
