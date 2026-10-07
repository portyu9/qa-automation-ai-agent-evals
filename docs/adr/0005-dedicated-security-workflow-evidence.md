# ADR 0005: Dedicated security workflow evidence

**Status:** Accepted
**Date:** 2026-10-07
**Supersedes:** None

## Context

The accepted CI contract already performs security-relevant qualification inside `.github/workflows/ci.yml`: the
repository policy validates the scanner stack, the quality lanes run Bandit and dependency audit, Actions security
is evaluated separately, dependency review is fail-closed where repository administration permits it, and CodeQL
retains its own exact workflow and result gate. The public portfolio, however, projects named workflow evidence.
Other reviewed systems expose a dedicated `security.yml` surface while this repository exposed only `ci.yml`,
so the portfolio could not link a SECURITY badge to an independently named workflow even though security checks
were present.

No historical branch contains an unmerged `security.yml` implementation to salvage. The accepted base for this
decision is main `9f8b2241b3f7bae7c6fb762b61efa2d107b93228`; the existing CI, CodeQL, Scorecard, dependency governance,
and release assurance contracts remain the lineage that must be preserved.

## Decision

Add `.github/workflows/security.yml` as a read-only, first-class evidence workflow. It runs on pull requests and
pushes to `main`, on a bounded weekly schedule, and by explicit manual dispatch. It checks out without persisted
credentials, validates the mandatory scanner-stack contract, installs the exact hash-checked Python 3.11 core
profile, requires a consistent dependency graph, runs Bandit, and runs `pip-audit`.

The workflow terminates in a stable `security-gate` job that succeeds only when the scanner job succeeds. This
name is intended to provide an explicit repository-local SECURITY evidence surface for the portfolio without
reinterpreting the broader `ci-gate`.

Because workflow definitions are assurance-semantic paths, add `security.yml` to the dependency-governance
pull-request path set so future changes continue to exercise governance self-tests. This ADR is added in the same
change because the semantic ADR policy requires an append-only decision record for governed workflow changes.

## Consequences

The repository gains an additional Actions run on qualifying events and a weekly scheduled execution. Bandit and
dependency audit intentionally overlap checks already present in CI; that redundancy is the cost of a separately
named, independently observable SECURITY workflow. The dedicated workflow stays narrower than the aggregate CI
graph and does not replace Actions-security, dependency review, CodeQL, Scorecard, package integrity, release
supply-chain verification, or the required `ci-gate`.

Portfolio consumers may link to `.github/workflows/security.yml` and display its main-branch status once a
successful main run exists. Changes to this workflow remain subject to the repository's normal governed-path and
ADR requirements.

## Assurance impact

This decision adds a new evidence surface; it does not reduce an existing one. The workflow has `contents: read`
only, no secret consumption, no OIDC, no repository mutation authority, no check/status publication authority, and
no merge authority. Immutable action revisions and hash-checked dependency installation preserve the repository's
existing supply-chain expectations.

A green `security-gate` means only that the exact workflow subject completed the declared scanner contract
successfully. CI, CodeQL, Scorecard, dependency review, package/release evidence, protected-branch rules, and
repository administration remain separate assurance domains.

## Non-claims

This ADR does not claim universal absence of vulnerabilities, malware, secrets, dependency risk, or unsafe agent
behavior. It does not make `security.yml` a replacement for CodeQL or the aggregate CI gate, does not grant
deployment or release authority, and does not authorize bypass of branch protection or repository governance.
A portfolio badge derived from this workflow is a scoped live evidence signal, not certification.
