# Compatibility Matrix

This document is the human-readable compatibility view for the current source contract. Executable
truth remains in pyproject.toml, the checked-in compatibility locks, CI, and the canonical
agent-evals/release-statement/v1 produced from qualified release artifacts.

## Current framework line

| Surface | Current contract | Executable authority |
|---|---|---|
| Framework package | 0.1.0 source/package metadata; pre-1.0 | pyproject.toml |
| Python | >=3.11,<3.15 (3.11, 3.12, 3.13, 3.14) | package metadata; quality on 3.11 + 3.14; compatibility locks |
| Core runtime | pydantic>=2.12.2,<3, typer>=0.16,<1 | package metadata + core min/latest locks |
| OpenAI integration | openai-agents==0.22.3 | optional dependency + openai-mcp min/latest CI profile |
| MCP integration | mcp==2.2.0 plus declared HTTP/ASGI ranges | optional dependency + mcp and openai-mcp min/latest CI profiles |

The six release-bound compatibility snapshots are:

| Profile | Minimum boundary | Latest reviewed boundary |
|---|---|---|
| core | Python 3.11 — requirements/compatibility/core-minimum-py311.txt | Python 3.14 — requirements/compatibility/core-latest-py314.txt |
| mcp | Python 3.11 — requirements/compatibility/mcp-minimum-py311.txt | Python 3.14 — requirements/compatibility/mcp-latest-py314.txt |
| openai-mcp | Python 3.11 — requirements/compatibility/openai-mcp-minimum-py311.txt | Python 3.14 — requirements/compatibility/openai-mcp-latest-py314.txt |

"Latest" means the reviewed versions frozen in that lock, not arbitrary future packages satisfying a
range. A dependency release after the lock was generated is not covered until the lock and its CI
qualification advance.

## Evidence and schema compatibility

| Contract | Compatibility status |
|---|---|
| Current TrialEvidence/v2 root semantics | Current writer/validator contract; accepted roots are not silently reinterpreted |
| Historical TrialEvidence/v2 timestamp encodings | Verification-only via agent_evals.evidence.legacy_v2; not upgraded to current gradeable evidence |
| Versioned receipts/policies/reports | Each schema identity is authoritative only for its documented version; a new semantic meaning requires an explicit version/domain transition |
| JSON runtime request agent-evals/json-runtime-request/v1 | Current provider-neutral HTTP adapter request contract |

Resource ceilings, UTC normalization, minimization, and verification-only historical support can
constrain what current code accepts without redefining a historical root. See
[Evidence & Replay](EVIDENCE_AND_REPLAY.md), [Evidence Minimization](EVIDENCE_MINIMIZATION.md), and
[Deprecation Policy](DEPRECATION_POLICY.md).

## Provider and protocol scope

The OpenAI and MCP rows above establish compatibility with the repository-governed SDK versions and
the exact deterministic/live lanes that exercise them. They do not claim compatibility with every
OpenAI model, every hosted MCP server, arbitrary future SDK versions, every operating system, or an
external provider's production availability.

Provider-neutrality is an architecture property plus tested adapter behavior; it is not a claim that
all providers implement equivalent semantics.

## Release binding

On a qualified trusted-main run, the release statement binds the exact pyproject.toml digest and all
six compatibility-lock digests to the retained package and provenance subjects. The GitHub Release
publisher then reverifies that statement before publication. As of 2026-10-07, there is no published
GitHub Release and no PyPI release, so this document must not be read as a distribution claim.

## Change policy

Compatibility changes that touch governed assurance semantics require a new ADR, changelog entry when
user/operator-visible, and the transition rules in [Deprecation Policy](DEPRECATION_POLICY.md).
Prose may narrow claims but may not expand them beyond executable qualification evidence.
