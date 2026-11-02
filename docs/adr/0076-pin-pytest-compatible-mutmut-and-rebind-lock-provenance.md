# ADR 0076: Pin pytest-compatible Mutmut and rebind lock provenance

**Status:** Accepted
**Date:** 2026-11-02
**Supersedes:** Mutmut 3.8.0 compatibility assumption in the mutation assurance implementation and documentation; retains the assurance floors and all earlier trust boundaries.

## Context

The accepted `main` at `f0d9c5280c2129ebf73f13dea8c463398d00f37a` pins `mutmut==3.8.0` across development input, six native CI hash locks, six minimum/latest compatibility locks, the deep-mutation runner, and its manifest and contract test. On November 2, CI mutation job `125335513710` failed while collecting test statistics: Mutmut 3.8.0's pytest harness accessed the private `pytest.Function._nodeid` attribute, which is absent under the installed pytest 9.2. The resulting `AttributeError` stopped mutation execution before it could return valid results; CI's mutation policy correctly failed closed and blocked `ci-gate` and package integrity. The scheduled deep-mutation suite was also failing on the pinned tool.

The upstream Mutmut 3.8.1 release fixes stats collection on pytest 9.2 by using the public `nodeid` attribute. Mutmut is development/assurance tooling rather than runtime package behavior. The repository's existing `95.00%` mutation floor, disallowance of incomplete/unresolved results, and ten named deep campaigns remain authoritative. Updating the direct Mutmut requirement also changes the exact sorted source-requirements digest recorded in each compatibility lock header. That provenance contract must be renewed in the same change as the pin.

## Decision

Pin `mutmut==3.8.1` exactly in `pyproject.toml`, the tool-version assertion in `.github/scripts/run_deep_mutation.py`, the deep-campaign manifest, and executable policy expectations. Replace only the Mutmut 3.8.0 artifacts in all six core/MCP/OpenAI-MCP native CI locks and all six minimum/latest compatibility locks using the 3.8.1 upstream SHA-256 sdist and wheel identities. The respective SHA-256 artifact digests are `9fb7cfc23caabff22a938e33b8d34317f5fa79b1deab82642cd5e014f3f400aa` and `e424d72c0557b6a52a721d9b71e2d18eb9590af746db0bbad50b71e8d4d8ed78`.

Regenerate and bind the six compatibility `Input-SHA256` fields to the canonical source requirements calculated by `validate_dependency_compatibility.py`: deduplicate and lexicographically sort the declared runtime/tooling input requirements, join with newline and a terminal newline, hash with SHA-256. Preserve all non-Mutmut package pins, hashes, lock profile membership, build compiler identity, and `--require-hashes` installation requirements. Make no changes to the mutation-score evaluator, target selection, concurrency, timeout, or security/owner-approval rules. This ADR is an append-only decision record, not a replacement for executable checks.

## Consequences

CI and deep-assurance jobs will use Mutmut 3.8.1's pytest-compatible statistics harness. Every targeted lock and the deep-runner contract refer to one exact Mutmut release. Updating source declarations necessarily changes six lock-header input identities; the independent compatibility validator will reject any stale header or future ungoverned drift. Keeping a third-party pinned tool limits supply-chain/version drift but does not guarantee future pytest compatibility; further tool changes require matching lock regeneration, tests and a new decision if assurance semantics are governed.

The two open Dependabot lanes are not replaced by this change: PR #431's unique Ruff upgrade plus 12 bot-generated lock/compatibility revisions and PR #432's unique immutable zizmor workflow pin must be preserved and reconciled against the eventual accepted main using fresh provenance and exact-head qualification. Historical closed Dependabot action PRs #417 and #422 are superseded by accepted newer action versions; no orphaned implementation branch was found in the preflight.

## Assurance impact

Keep the ordinary authoritative mutation gate at **95.00% or higher** with exact successful process exit, a positive mutant denominator, complete exported status accounting, and zero unresolved `no_tests`, `skipped`, `suspicious`, `timeout`, interrupted, or segfault statuses. Keep ten independently scored deep-mutation campaigns, their `95.00%` per-campaign threshold, manifest file membership, strict tool-version verification, exact subject SHA and retained artifacts unchanged.

The exact PR head must separately satisfy repository runtime policy, dependency-lock and compatibility provenance validation, dependency governance self-tests, Python quality/compatibility, CodeQL, Security, main CI's real Mutmut execution and aggregate `ci-gate`. Deep mutation is an independently required confidence signal where triggered; no ordinary CI result substitutes for it. A missing source-input digest, wrong wheel/sdist artifact hash, failed Mutmut collection, incomplete campaign or insufficient mutation score must continue to block the appropriate gate.

Lineage preflight: accepted `main@f0d9c5280c2129ebf73f13dea8c463398d00f37a`; open bot PR #431 head `5bd3513ac711d7b2e97b1576cca4e55ae8d44e3e`, `pyproject.toml` blob `4ee552f0bc7415fe2ab245bd6030dff6ad1ce8ca`, and separate generated lock identities; bot PR #432 head `7d8954c6accaa7dd0ecbb399bcf4ff4f7887079a`, `ci.yml` blob `f3645ed24aeb3cd664faca1b88cb6fc21cb33503`. Both are **must preserve**, not replace. Closed old action PR #417 head `a03140e930cc0c124e2ea6501e62a6fa037d510f` and #422 head `9de3a2addc498904cdcd9cc45d4aa6ae74fe6425` are **superseded**, with their older pin revisions already overtaken by the accepted main action set; prior code PRs #424–429 are accepted. No other divergent implementation branch was found.

## Non-claims

A new version pin does not itself establish that the CI and ten deep mutation campaigns pass, that mutation testing is an exhaustive security proof, or that a future upstream tool update is safe. This change does not waive survivor review, lower any thresholds, skip tests, bypass CodeQL, loosen dependency provenance, override administrative protection, autonomously merge a stale bot head, or establish production runtime compatibility outside separately executed checks.
