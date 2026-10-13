# ADR 0010: Reference live dependency-pin authority in compatibility documentation

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

The accepted compatibility matrix duplicated exact `mcp` and `openai-agents` versions from `pyproject.toml`. Its governance validator demanded the same literal version strings in Markdown. A signed Dependabot source change plus the trusted 12-lock publisher correctly advanced SDK pins and hashes, yet exact-head CI failed solely because the static prose still repeated the previous versions. The restricted lock publisher cannot rewrite arbitrary documentation, and granting it arbitrary documentation mutation authority would expand the trust boundary defined in ADRs 0008–0009.

## Decision

The matrix shall instead name the exact source of its current OpenAI and MCP pins: the relevant `project.optional-dependencies` entries in `pyproject.toml`. The governance validator requires those precise source-authority references while still parsing and requiring exactly one direct `==` pin for each package. Exact locks and reproducible compatibility evidence remain verified by the separate unchanged lock and CI policies. Do not freeze version strings in a human-facing snapshot that cannot be updated by the canonical dependency-only admission lane.

## Consequences

A legitimate signed direct-SDK update no longer fails the documentation contract for containing a newer version than the last manually authored Markdown. The matrix is explicitly a current-source contract, not an immutable release version list. Readers seeking concrete dependency values must inspect `pyproject.toml` at the same commit; the six checked-in compatibility lock paths remain listed and mandatory.

## Assurance impact

The governance validator still parses `pyproject.toml`, enforces exact pin cardinality and retains all six required lock path checks, Python floor and release/replay prose checks. The new binding is declarative; dependency graphs, hashes, CodeQL, package reproducibility, signed bot provenance, publisher scope and trusted merge requirements are unchanged. The fix narrows documentation drift risk without adding any privileged mutation authority.

## Non-claims

This does not claim future versions are automatically compatible without qualifying their hashes and tests; it does not loosen a single dependency range, permit arbitrary package versions, allow prose to override executable manifests, or weaken post-merge CI/security evidence.
