# ADR 0084: Preserve OAuth revocation and chaos uncertainty contracts under Ruff upgrades

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** No security or behavioral decision. This record documents a source-equivalent refactoring required by the updated Ruff lint compatibility contract; it does not supersede the existing OAuth, chaos, or dependency-governance architecture.

## Context

The repository intentionally enables the Ruff `SIM` lint family and permits Dependabot to propose upgrades to its pinned linter and its hash-locked compatibility manifests. The signed Ruff 0.17.3 → 0.17.4 proposal in PR #445 introduced `SIM102` on two preexisting nested conditions: (1) a revoked OAuth session token accepted by a resource, and (2) a `BLOCKED` chaos observation with a missing evaluator-owned error code. Quality jobs for Python 3.11 and 3.14 failed, correctly preventing autonomous merge. Disabling `SIM102`, accepting an unsafe automatic rewrite, or bypassing required tests would weaken or obscure the invariant.

The original source enforced the following predicates: `kind == REQUEST AND token in revoked_tokens AND accepted_by_resource` is rejected, and `outcome == BLOCKED AND error_code is None` is rejected. These predicates do not depend on side effects and their operands are already validated typed fields.

## Decision

Replace the two nested `elif`/inner-`if` checks with a single equivalent `elif` Boolean conjunction. Keep identical exception classes, messages, and error transitions. No change to token revocation order, sender binding, evaluator-vs-subject blame, upstream model response classification, or authorization provenance is permitted.

Add executable regression cases establishing that an accepted request made using a revoked token is rejected; a denied request using a revoked token and a request using a nonrevoked token remain accepted by the event sequence checker; a `BLOCKED` chaos observation lacking an error code is rejected; and a `RECOVERED` observation carrying an evaluator error remains rejected.

Keep `SIM` lint selection enabled and all required CI, security, CodeQL, package-integrity, semantic ADR, and exact-head Dependabot gates. This record does not authorize an automated unsafe Ruff fix or mutation of the native Dependabot commit. The signed bot PR must refresh onto the newly accepted main and satisfy its own pinned hash-locked qualification before merge.

## Consequences

Future Ruff 0.17.4 upgrades no longer fail on these two source constructs, while the executable negative cases protect the original fail-closed semantic boundary. The updated linter may add other diagnostics in a later release; such diagnostics are not presumed safe to fix automatically and remain subject to explicit source review, an append-only decision record where required, and required qualification. A successfully merged correction does not establish that arbitrary future lint releases will be compatible.

No provider credential, model target, security exception, dependency allowlist, CI skip, secret, or workflow privilege is introduced. Normal code qualification still runs for all supported Python versions.

## Assurance impact

The changes affect validation of OAuth resource acceptance following token revocation and evaluator-owned classification of chaos observations, both high-assurance boundaries. The conditional equivalence is explicit, with positive and adversarial test cases. Ruff must still pass as a required quality gate, and repository policy must verify this newly added numbered ADR on the exact PR head. Separately, the signed Dependabot lint-upgrade PR must pass against the accepted main SHA before automated merge.

## Non-claims

- This ADR does not claim that arbitrary Ruff upgrades are source-compatible or automatically safe to apply.
- It does not authorize suppression of lint violations, mutation of a signed Dependabot branch, or bypassing CI, Security, CodeQL, package integrity, or owner controls.
- It does not modify OAuth issuer trust, JWT verification, resource acceptance rules, replay detection, or chaos error attribution.
- It does not resolve the separate scheduled live-provider canary's missing credentials and pricing configuration (issue #447).
