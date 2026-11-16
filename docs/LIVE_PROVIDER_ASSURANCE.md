# Live Provider Assurance and Adapter Conformance

## Purpose

The framework provides deterministic adapter conformance and an offline simulated provider-boundary test seam; credentialed live-provider observation is intentionally out of scope.

Ordinary pull requests and deterministic CI prove repository-owned contracts without network credentials. The credential-dependent live canary has been retired because credentials and paid provider calls are intentionally outside this repository's scope. Deterministic offline provider-boundary simulation remains available. Neither path gives provider output grading authority, and neither path lets a third-party adapter declare itself a trusted producer of evaluator-owned evidence.

## Evaluator-owned adapter conformance

The core evaluator applies an evaluator-owned conformance check to every normalized adapter result before evidence conversion. The check validates:

- an exact `AdapterResult`;
- exact `EvidenceEvent` instances with contiguous zero-based sequence values;
- an exact terminal-state object;
- bounded output shape;
- finite non-negative elapsed time, token counts, and estimated cost.

Adapter identity remains the original runtime object throughout execution, drift detection, error provenance, and producer-authority checks. Invalid or hostile adapter names continue to fail through the existing bounded metric-provenance boundary rather than creating a second competing identity path.

A conformance failure is mapped into the evaluator's established invalid-adapter-result precondition and therefore resolves to `BLOCKED`, never subject `FAIL`.

Conformance is not producer authorization. The core evaluator still checks the original adapter by exact type for evaluator-owned `ATTACK_DELIVERY`, retrieval, approval, side-effect, and MCP protocol evidence. A subclass, matching class name, matching source string, structurally valid result, or conformance pass cannot manufacture that authority.

This design keeps extensibility separate from trust:

```text
implements AgentAdapter + passes structural conformance
    = eligible to provide ordinary normalized subject observations

passes structural conformance
    != authorized producer of evaluator-owned evidence
```

## Distinct JSON runtime adapter

`JsonHttpRuntimeAdapter` is a second runtime boundary distinct from the OpenAI Agents SDK adapter. Its transport receives a bounded request containing the exact trial, subject, scenario, objective, and turn-limit identities.

The remote response may supply only terminal output/state and non-authoritative token/cost telemetry. It cannot supply framework `EvidenceEvent` objects or choose evaluator-owned evidence kinds or source strings. Unexpected response fields fail closed before grading.

When public provider/runtime interfaces expose them, the adapter may retain bounded request identifiers and model-revision labels in a framework-created `OUTPUT` event. Those labels are diagnostic metadata. They are not authenticated provider identity, model attestation, or signing evidence.

A non-successful transport result becomes adapter uncertainty (`BLOCKED`), not a behavioral failure.

## Approved credential-free execution boundary

The QA Agent Evals repository requires **no provider account, API key, paid model, pricing variable, network call, or live provider observation** for its automated assurance. This is an intentional scope decision, not a missing configuration.

The previously installed weekly/manual GitHub Actions live-provider canary and its credentialed HTTP runner were removed. No workflow dispatch, schedule, PR job, release gate, or other repository automation may call the provider API as a canary or require provider secrets. The repository's native GitHub governance authentication is separate from provider credentials and is not altered by this decision.

The versioned runtime policy `.github/scripts/validate_runtime_policy.py` and the `tests/unit/test_live_provider_workflow_policy.py` contract reject restoration of the retired canary entry points or active workflows containing provider-key or canary configuration markers. Those checks are part of ordinary CI. In particular, the absence of an API key must **not** produce a red scheduled workflow or a request to provision a secret.

A previous scheduled live-provider workflow did fail on 2026-11-16 because it incorrectly expected `OPENAI_API_KEY` and pricing/model configuration. That historical run is immutable GitHub evidence, **not** an ongoing operational requirement. The incorrect provisioning request in issue #447 was closed as not planned.

## Deterministic provider-boundary and retry classification

`src/agent_evals/live_provider.py` remains a credential-free **pure control-plane test seam**: `run_provider_canary` accepts an injected transport function supplied by tests. No live HTTP adapter or automatically invoked provider call is attached to that seam. `tests/unit/test_live_provider_canary.py` verifies simulated successful observations, behavioral mismatches, throttling, timeouts, malformed responses, policy ceilings, and distinct uncertainty outcomes without external I/O.

The simulated dispositions retain their original meaning:

| Disposition | Meaning |
|---|---|
| `observed` | A deterministic injected transport returned a structurally valid response matching the declared assertion. |
| `subject_failure` | A deterministic injected transport returned a valid response violating the test assertion. |
| `provider_uncertain` | A simulated provider or transport result could not be resolved safely (rate limiting, timeout, malformed response, or budget violation). |

These are **offline test observations only**. Even a simulated `observed` result is not proof that a public provider was contacted, a model ran, a real request ID was generated, or a paid inference request succeeded.

The remaining attempt, token, time, and estimated-cost limits are deterministic **contract inputs** for the injected transport and are exercised in unit tests. They are not a live spending authorization, configured price snapshot, or enabled provider billing workflow. The `historical_observation: true` and `provider_attestation: false` schema flags in simulated observations continue to prevent promotion into evaluator-owned authority.

## Non-claims

This layer does not establish:

- authenticated provider or model identity from a request ID or model string;
- a real provider-side execution, SLA, availability guarantee, or receipt;
- a provider-attested timestamp, billing amount, or price;
- external side-effect truth without independent evaluator-owned evidence;
- automatic release acceptance based on synthetic or historical provider observations;
- authorization for third-party adapters to emit evaluator-owned evidence;
- permission to create API secrets, enable paid requests, or revive the removed live canary.

Any future credentialed execution would require a separately requested scope decision, an append-only architecture decision, and governed security review. It must not be inferred from this document or the presence of the deterministic test seam.

[← Documentation hub](README.md)
