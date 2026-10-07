# Changelog

This file records material repository changes that affect users, operators, evaluators, or assurance
claims. The repository is pre-1.0, but pre-1.0 does not permit silent reinterpretation of durable
evidence or authority semantics.

## Unreleased

### Release automation

- Add deterministic default-branch release-version preparation that emits a validated patch artifact without repository write authority.
- Add a separate PyPI Trusted Publishing workflow that is triggered only by a published GitHub Release, executes default-branch code only, re-verifies the exact attested release subjects, and uses GitHub OIDC instead of a long-lived PyPI token.
- Version the canonical release statement to v2 for the OIDC-only PyPI publication contract while retaining exact v1 verification semantics.

### Governance

- Require append-only architecture decision records (ADRs) for governed assurance-semantic changes.
- Publish explicit compatibility and deprecation contracts for framework, Python, OpenAI, MCP,
  evidence schemas, and adapters.

### Documentation

- Add a durable changelog rather than treating commit history as release notes.

## 0.1.0 — repository baseline (not yet published)

The current package metadata declares version 0.1.0. As of 2026-10-07, the repository has no GitHub
Release and no PyPI publication. This section describes the source baseline only; it is not a claim
that a distributable release has been published.

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

- A source baseline is not a signed GitHub Release.
- The repository is not published to PyPI and does not claim PyPI Trusted Publishing.
- Hashes are integrity identities, not authentication.
- Compatibility claims remain limited to the executable contracts documented in
  docs/COMPATIBILITY.md.
