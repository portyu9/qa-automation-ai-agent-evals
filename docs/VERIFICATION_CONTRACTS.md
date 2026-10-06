# Verification Contracts

The verification layer is additive to the framework's historical evidence and assurance schemas. It
exists to make new authority-bearing integrations explicit without changing what old hashes mean.

## Historical contracts that do not change

- Trial evidence remains agent-evals/trial-evidence/v2 with root domain
  agent-evals/trial-evidence/v2\0.
- Assurance Report v6 remains agent-evals/assurance-report/v6; its historical verifier and root
  semantics are not widened by the new verification objects.
- Existing attack, protocol, retrieval, side-effect, approval, and semantic receipt roots keep
  their own domain-specific verifiers. A common receipt envelope never substitutes for them.
- BLOCKED remains evaluator uncertainty/precondition failure, not subject FAIL.
- Existing exact-type live-producer checks remain fail-closed authority while capability-backed
  producer migration is introduced deliberately.

## New additive schemas

| Contract | Schema | Purpose |
|---|---|---|
| Verification fact | agent-evals/verification-fact/v1 | Bind one fact claim to exact material, context, dependencies, and a non-authorizing producer label. |
| Verification graph | agent-evals/verification-graph/v1 | Commit to an ordered topological DAG of independently verified facts. |
| Evidence chain | agent-evals/evidence-chain/v1 | Optional bounded previous-root chain over existing event digests for incremental verification. |
| Typed event projection | agent-evals/event-payload/v1 | Validate historical event payloads into explicit kind-discriminated views without rewriting v2 evidence. |
| Outcome selector | agent-evals/outcome-selector/v1 | Unambiguous JSON-pointer selectors for new contracts; historical dotted selectors remain legacy behavior. |
| Receipt envelope | agent-evals/receipt-envelope/v1 | Common metadata/digest wrapper around domain-specific receipts without collapsing trust domains. |

## Producer capabilities

ProducerCapabilityAuthority issues run-local capabilities bound by object identity to one exact
issuer. Cross-authority reuse, role substitution, and producer-ID substitution are rejected. This is
an evaluator-process role-separation mechanism. It is not a cryptographic token, remote attestation,
or sandbox against hostile Python already executing in the same interpreter.

Serialized FactProducerRole values are also not authority. A VerificationFactClaim becomes a
run-local VerifiedFact only when verify_fact_claim(...) independently recomputes the exact material
digest and checks the caller-owned expected kind, name, producer role, dependencies, and context.

## Release criticality

The compatibility ReleaseGate.decide(..., critical_violations=...) API remains available so old
callers are not silently reinterpreted. New hardened integrations can use decide_verified(...) with
VerifiedCriticalityRecord; the gate derives the non-compensatory count from exact verified
criticality facts rather than taking a caller-supplied integer.

A verified criticality fact still proves only the relation its verifier checked. It is not a
signature, human identity assertion, provider attestation, or permission to upgrade unrelated facts.

## Typed event projections

project_typed_event(...) validates an existing EvidenceEvent into a v1 kind-specific payload view.
It does not alter the event digest or evidence root. Receipt-bearing event kinds require the common
schema_version + receipt_root shape, while semantic correctness remains with the existing domain
verifier.

This separation is deliberate: schema discrimination improves machine handling; it does not confer
producer authority.

## Outcome selectors

OutcomeSelectorV1 uses explicit JSON-pointer escaping (~0 for ~, ~1 for /). Therefore a flat key
named a.b, a nested path a -> b, and a key containing / are distinct. Existing
EvaluationScenario.required_outcomes / forbidden_outcomes retain their historical dotted-path
semantics until a future explicitly versioned scenario migration elects the new selector contract.

## Oracle failure codes

structured_oracle_failures(...) projects current deterministic-oracle reasons into stable failure
classes such as outcome.required_missing, policy.resource, and policy.budget. The original oracle
still owns verdict and criticality; classification does not recompute or override grading.

## Common receipt envelopes

ReceiptEnvelopeV1 binds the existing receipt schema, existing receipt root, exact event digest, and
payload digest. Verifying the envelope proves only envelope integrity. Consumers must still invoke
the attack/MCP/retrieval/side-effect/semantic verifier appropriate to that receipt domain.

## Non-claims

These contracts intentionally do not claim:

- hashes are authentication or signatures;
- run-local capabilities resist hostile same-process introspection;
- a producer label authenticates a producer;
- a receipt envelope upgrades the trust of its embedded receipt;
- the previous-root chain is a Merkle membership proof;
- a typed payload projection proves the payload was truthfully produced;
- structured failure codes replace deterministic oracle authority;
- old persisted evidence is reinterpreted under new schema labels.
