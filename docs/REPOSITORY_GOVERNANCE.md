# Repository Governance

## Purpose

This document defines the repository-owned review, ownership, protected-history, and administration intent for assurance-critical changes. The executable copy of that intent is `.github/repository-governance.json`, validated by `.github/scripts/validate_governance_policy.py`.

## Repository-owned intent is not live enforcement

Committed policy describes what the repository requires and allows CI to detect accidental drift in that intent. It is **not** evidence that GitHub has applied the same settings. Live enforcement belongs to the protected-branch/ruleset administration surface and must be verified independently.

A missing or inaccessible administration control is therefore not rewritten as PASS. It remains BLOCKED or unverified until an authorized administration surface establishes the state.

## Review and protected-history target

The intended protected-`main` contract is:

- pull requests are mandatory;
- at least one approving review is required;
- trust-critical paths require CODEOWNER review;
- stale approvals are dismissed after substantive pushes;
- approval after the last substantive push is required;
- review threads must be resolved before merge;
- merge commits remain the only allowed merge method;
- aggregate CI/CodeQL authority remains bound through the protected `Package integrity` bridge.

These controls are cumulative. Repository-owned checks do not compensate for a missing live review rule.

## BLOCKED: single-maintainer independent review

The repository currently has one trust maintainer represented in CODEOWNERS. A reviewer cannot provide independent governance merely by reviewing their own change under another repository-owned label.

The target is at least two distinct trust maintainers before CODEOWNER approval becomes a meaningful independent-review mechanism. Until that precondition is met, independent CODEOWNER review is explicitly **BLOCKED: single-maintainer independent review** rather than treated as satisfied.

When additional maintainers are added, ownership should be split by durable expertise boundaries instead of assigning every sensitive path to every maintainer. The machine-readable trust-boundary list exists so that expansion is explicit and reviewable.

## Trust-critical ownership

CODEOWNERS must explicitly cover the repository surfaces that can change evaluation authority, evidence meaning, release truth, CI authority, or security non-claims. The current contract covers at least:

- `.github/` workflows, policy, security, and release automation;
- `pyproject.toml` and `requirements/` runtime/dependency authority;
- contracts, evidence, release gates, runtime, security, and semantic evaluator code;
- security and limitations documentation.

CODEOWNERS is a routing and governance mechanism, not an authentication system. A GitHub username does not become a cryptographic principal merely because it appears in CODEOWNERS.

## Signed protected history

Decision: **require signed commits on protected history** once the live ruleset can be updated through an authorized administration surface.

GitHub-created merge commits may already report valid verification, but observed signed commits do not substitute for a rule requiring signatures. The repository policy records the decision; live ruleset inspection proves enforcement.

## Auto-merge and update-branch

Decision: keep repository auto-merge and update-branch support disabled until the live review controls above are authoritative.

After required approvals, CODEOWNER review, stale/last-push protection, thread resolution, and authoritative checks are enforced, both features may be enabled through repository administration. Enabling them earlier would increase automation before the human-governance boundary is enforceable.

## External administration prerequisites

The following remain administration-surface requirements and are never inferred from committed files alone:

- dependency graph enabled so dependency review can execute;
- secret scanning verified enabled;
- push protection verified enabled;
- protected-`main` review controls applied;
- signed-commit rule applied;
- repository auto-merge/update-branch state applied according to the decision above.

Where the connected automation surface cannot read or mutate one of these settings, repository status must remain BLOCKED/unverified rather than guessed.

## Change control

Changes to evidence schemas, canonical identity, release authority, authorization semantics, replay semantics, security boundaries, repository governance policy, CI gate authority, or protected-history policy require explicit compatibility/security review.

A change that alters assurance meaning should explain:

- what authority or evidence domain changes;
- whether historical artifacts keep their previous meaning;
- whether a schema/version transition is required;
- what deterministic tests prove the new boundary;
- what non-claims remain;
- whether a live GitHub administration change is additionally required.

The repository policy validator checks committed intent only. It deliberately does not claim to attest the live GitHub ruleset.
