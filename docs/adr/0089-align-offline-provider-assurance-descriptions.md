# ADR 0089: Align governed limitations and framework surface with offline-only provider assurance

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** Outdated descriptive claims in `docs/LIMITATIONS.md` and `docs/FRAMEWORK_SURFACE.md` that a weekly/manual credentialed provider-canary workflow still executes. Does not supersede or relax the runtime exclusion decision in ADR 0088.

## Context

Accepted ADR 0088 and merged PR #452 retired the credential-dependent GitHub Actions live provider canary and its HTTP execution entry point from AI Agent Evals because paid provider credentials were always out of scope. Deterministic offline injected-transport tests remain. Yet two older documentation pages still presented a scheduled/manual credentialed observation as an active capability. This contradiction could mislead operators into provisioning unnecessary provider API keys, enabling network executions, or treating an old failed run as a live configuration blocker.

`docs/LIMITATIONS.md` is an explicitly governed architecture-semantic path under the repository's append-only ADR policy. Removing its obsolete assertions must therefore be accompanied by a newly numbered decision, even though the executable runtime policy is already accepted and unchanged.

## Decision

Update `docs/LIMITATIONS.md` and `docs/FRAMEWORK_SURFACE.md` to describe the accepted credential-free model accurately. Ordinary CI and the optional SDK surface test deterministic model doubles, local protocols, and injected transport. No GitHub Actions job contacts a paid public provider or requires provider credentials, cost/pricing variables, or an operator model selection.

Preserve all existing statements on evaluator-owned authority, adapter conformance, non-attestation, provider/model identity uncertainty, and the absence of production-provider liveness guarantees. Clearly distinguish simulated `run_provider_canary` dispositions from actual public HTTP requests and link directly to accepted ADR 0088.

Do not alter source, unit tests, workflow triggers, required status checks, signed Dependabot provenance, permissions, release gates, or provider simulation implementation in this documentation follow-up.

## Consequences

Public framework scope and limitations now describe the same accepted implementation and explicitly reject the false inference that a missing provider API key is a repository defect. Future additions of credential-dependent jobs remain prohibited by the runtime and test policy introduced by ADR 0088.

This documentation correction introduces no new executable feature or success claim. Historical GitHub runs and append-only earlier ADRs remain as they occurred; they cannot be rewritten to indicate provider credentials were authorized.

## Assurance impact

The governed limitations page no longer contradicts the runtime exclusion policy. The exact-head semantic ADR validator must require this new numbered decision record. All normal PR CI, Security and CodeQL checks remain mandatory and unmodified.

No live-provider evidence is manufactured, no secret is requested, and no required signal is bypassed. The persistent runtime negative enforcement from PR #452 is the actual prevention mechanism; documentation alone would not suffice.

## Non-claims

- This ADR does not make a real provider call or verify provider availability, pricing, billing, or model identity.
- It does not revive the credentialed canary under another filename or permit an out-of-scope secret.
- It does not override ADR 0088, which controls provider execution scope.
- It does not address independent Dependabot-native service delays or unrelated GitHub runner availability issues.
