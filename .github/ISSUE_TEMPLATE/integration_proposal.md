---
name: Provider / integration proposal
about: Propose a new provider, agent runtime, MCP, retrieval, approval, or external-system adapter
title: "integration: "
labels: ""
assignees: ""
---

## Integration

Name the provider/runtime/protocol boundary and the exact public interfaces to be exercised.

## Assurance claim

What narrow evidence-backed claim should this integration establish? Separate provider/runtime observation from evaluator authority.

## Normalization and provenance

Describe how tool calls, results, handoffs, approvals, state, timing and provider identifiers will be normalized. Identify any evaluator-owned evidence the integration must **not** be allowed to self-issue.

## Failure behavior

Explain how provider/runtime errors, unavailable preconditions, malformed output and ambiguous provenance fail closed.

## Deterministic testing

Describe provider-independent test doubles/fixtures and which live-provider checks, if any, must remain a separately labeled lane.

## Security and credentials

Describe credential/IAM requirements at a high level only. Do not post tokens, keys, secrets, production payloads, or private customer data.

## Non-claims

State what the integration does not prove (for example provider availability, production IAM, target-side enforcement, live-model quality, or cryptographic attestation).
