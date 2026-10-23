# ADR 0064: Remediate pinned setuptools traversal advisories with fully hashed lock closure

**Status:** Accepted
**Date:** 2026-10-23
**Supersedes:** None; extends the append-only dependency supply-chain controls.

## Context

The current `security` workflow on PR #414 found setuptools `84.0.0`
vulnerable to GHSA-xmj3-9gf7-h52w. The CI gate correctly failed during
`pip-audit`, independently of the separate lowercase native workflow-name
contract correction. The repository intentionally uses SHA-256-hashed
closed dependency profiles and separately reviewed, version-bound compiler
bootstrap profiles, so a partial pin edit would break deterministic builds.

## Decision

Advance only setuptools to released `84.2.1` in every first-party core,
MCP, OpenAI-MCP, minimum/latest compatibility and compiler-bootstrap lock
profile. Bind the wheel SHA-256
`ca140b45d5325a9478f880e351484f62fef15f336462e449ca0c03c873d589c2`
and source tarball SHA-256
`3ff8b3b5492a0aa66960f4419365a86b84e013070d4313e4d4a6894f5d64d6bc`
to the exact PyPI 84.2.1 release artifacts published 2026-10-20.
Update the compiler-bootstrap version assertion to `84.2.1` alongside
those generated lockfiles. No blanket vulnerability exemption, `pip-audit`
disablement, floating version constraint, lock removal or GitHub gate bypass.

## Consequences

Fresh CI, release artifact and security installations resolve reviewed
setuptools 84.2.1 across Python 3.11–3.14 and previously supported
compatibility lanes. Dependencies other than setuptools retain identical
pin/hash blocks; the existing source build `setuptools>=83` remains unchanged.
All release and qualification evidence must still derive from real successful
workflow runs and exactly reproducible artifact builds.

## Assurance impact

On accepted main `c9e4af94ec3e15fdae8f860d948e252d88e1e82f`, the
security job failed with the exact GHSA advisory, independent of main CI's
uppercase evidence-label regression. The security remediation follows
new app PR #414 on its existing reviewed branch, without creating a duplicate
lane or modifying accepted ADRs. Wheel/sdist hashes were checked against the
official PyPI release page; every old lock block was replaced exactly once.
Gate acceptance requires CI parser/lock/compatibility/compiler/release tests,
CodeQL, and a clean installed-dependency pip-audit on the exact new commit.

## Non-claims

A pinned upstream release and passing `pip-audit` cannot establish absolute
absence of vulnerabilities. This ADR does not alter risk policy, exception
allowlists, CODEOWNERS, workflow execution authority, or protected merge
requirements. It does not authorize rewriting pre-existing signed evidence.
