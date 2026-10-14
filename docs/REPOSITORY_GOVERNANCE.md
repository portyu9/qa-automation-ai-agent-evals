# Repository Governance

## Purpose

This document defines the repository-owned ownership, protected-merge, history, and administration intent for assurance-critical changes. The executable copy is `.github/repository-governance.json`, validated by `.github/scripts/validate_governance_policy.py`.

## Repository-owned intent is not live enforcement

Committed policy defines repository intent and lets CI detect drift. It is **not** continuous evidence of GitHub administration state. Live enforcement belongs to the GitHub ruleset/admin surface and must be independently verified.

A missing or inaccessible administration control is never rewritten as PASS.

## Single-CODEOWNER CI-authoritative model

The repository intentionally has exactly one human CODEOWNER: `@portyu9`. CODEOWNERS expresses trust ownership and routes review attention; it is **not** a mandatory approval gate.

Protected-`main` merge authority is:

- pull requests are mandatory;
- zero approving reviews are required;
- CODEOWNER approval is not required;
- all configured required status checks must pass on the current merge subject;
- review threads must be resolved;
- merge commits remain the only allowed merge method;
- deletion and non-fast-forward protections remain active.

This model deliberately does not depend on GitHub Actions review approval or Copilot review approval. `can_approve_pull_request_reviews` may remain disabled, and Copilot quota cannot block a merge.

An optional human or automated review may still comment, request changes, or identify issues. Such review is advisory unless a future, explicitly reviewed governance revision changes the authority model.

## CI authority

The protected ruleset binds the required check contexts. A green unprotected job, comment, label, hash, or repository-owned marker does not substitute for those contexts.

The aggregate `Package integrity` bridge remains part of the protected check set so downstream release/supply-chain authority is not flattened into a weaker individual job.

Strict required-status-check policy means a PR must be qualified against the current protected base before merge.

## Signed-commit tradeoff

Decision: **do not require signed commits on protected history while autonomous connector/automation commits are part of the supported workflow**.

GitHub's signed-commit protection evaluates commits introduced by a pull request, including head-branch commits. Connector/API-created commits are not guaranteed to carry a user-verifiable signature. Requiring signatures therefore allows a PR to pass every authoritative CI check yet remain unmergeable.

This decision does not claim unsigned commits are authenticated. It preserves the repository's existing narrow non-claims: hashes are integrity identifiers, not signatures; GitHub account attribution is not cryptographic provenance; release attestations and evidence-domain signatures retain their own separate semantics.

A future managed signing identity may justify re-enabling signed-commit protection, but that requires an explicit key-management and automation design rather than assuming GitHub can sign API commits on the user's behalf.

## Trust-critical ownership

CODEOWNERS explicitly covers surfaces that can change evaluation authority, evidence meaning, release truth, CI authority, or security non-claims, including:

- `.github/`;
- `pyproject.toml` and `requirements/`;
- contracts, evidence, release gates, runtime, security, and semantic evaluator code;
- security and limitations documentation.

CODEOWNERS is routing/governance metadata, not an authentication system.

## Auto-merge and update-branch

Auto-merge and update-branch are eligible once the live ruleset matches this CI-authoritative model. They may not weaken required checks, thread resolution, deletion protection, non-fast-forward protection, or pull-request-only changes.

## External administration prerequisites

The repository **requires** the following external administration features but does
**not** currently claim that their enablement is independently authenticated:

- dependency graph: **UNVERIFIED**; an actual PR
  `dependency-graph/compare` probe returned HTTP 403/404 and dependency
  review was explicitly **BLOCKED**, not PASS. Access denial does not
  by itself establish whether the feature is switched off;
- secret scanning: **UNVERIFIED** from the limited connector surface;
- push protection: **UNVERIFIED** from the limited connector surface.

These states are recorded consistently across
`.github/repository-governance.json` and
`.github/security-scanners.json`. The required CI policy
`.github/scripts/validate_governance_policy.py` rejects invented
`verified-enabled` declarations and contradictions, including when
two mutable checked-in policies try to assert the same unsupported
claim. Changing the status requires an **independent authorized
GitHub administrator read**, recorded with date and scope; repository
JSON is *not* that evidence.

Separate, authenticated GitHub API reads have verified the active
Protect Main ruleset, required review-thread resolution, all seven
protected GitHub Actions status contexts, deletion and
non-fast-forward protections, and merge-only history as of
2026-10-14. Native auto-merge and branch updates are on, with squash
and rebase disabled. These are **point-in-time** observations, not
cryptographically authenticated assurances from checked-in policy.
The scoped read-only Actions token omits some administrator fields;
the live audit reports those as **BLOCKED**, never PASS.

Required signed commits are intentionally **not** part of the
current live ruleset, because connector-created working commits are
not guaranteed signed. Do not confuse unsigned GitHub commit identity
with provenance authentication or the signed Dependabot-specific
prerequisite. Whenever the connector cannot mutate or independently
observe an administrator setting, owner-authorized CLI/API
administration and a separate verified result are necessary.

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
