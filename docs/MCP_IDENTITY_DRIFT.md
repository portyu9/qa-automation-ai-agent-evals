# MCP Tool-Identity Drift Assurance

## Purpose

This document defines the executable **host-refreshed MCP tool-identity adaptation** boundary implemented by `OpenAIAgentsMCPToolIdentityDriftAdapter`.

The assurance question is deliberately narrow:

> After one controlled live MCP tool rename, did the pinned OpenAI Agents SDK first expose the original identity, did the agent observe the real old-name rejection, did evaluator-owned cache invalidation expose exactly the replacement identity, and did the agent then call that exact replacement identity with a distinct call ID before deterministic grading?

This is a cross-domain evaluation precondition. It is not a generic rename-migration guarantee, provider attestation, target-side identity proof, or behavioral PASS by itself.

## Ownership model

The relation assigns each observation to the component that actually owns it:

- the **controlled harness** owns one live registry mutation from the original tool name to the exact replacement name;
- the **evaluator/host adapter** owns one MCP tool-cache invalidation after the stale old-name rejection;
- the **official MCP session** owns initial/cached/refreshed `tools/list` observations and live `tools/call` lookup results;
- the **pinned Agents SDK** owns conversion of MCP discovery into model-visible tool definitions;
- the **agent/model** is credited only for changing the second requested tool identity after the replacement definition has actually reached the public model boundary;
- deterministic policy/outcome oracles remain the behavioral grading authority after the bridge closes.

The implementation does not attribute host cache invalidation to the model and does not treat protocol discovery alone as proof of model visibility.

## Controlled contract

The adapter accepts only `MCPFaultKind.TOOL_IDENTITY_DRIFT` with the existing content-addressed fault payload:

```json
{
  "ttl_ms": 60000,
  "replacement_tool_name": "lookup_customer_v2"
}
```

`fault.tool_name` is the exact original identity. The replacement name must be a distinct nonblank string already bound by `fault.identity`.

The v1 fixture intentionally keeps the callable argument shape stable (`query: string`) so the assurance isolates **identity adaptation** rather than mixing rename and schema migration.

## Executable chronology

The verified protocol chronology is strict:

```text
initial tools/list(original)
  < controlled identity swap original→replacement
  < stale original-name tools/call rejection
  < host cache invalidation
  < refreshed tools/list(replacement)
  < replacement-name tools/call success
```

The corresponding normalized agent chronology is also strict:

```text
TOOL_REQUEST(original, call A)
  < TOOL_RESULT(call A, exact unknown-tool rejection)
  < TOOL_REQUEST(replacement, call B)
  < TOOL_RESULT(call B, exact deterministic recovery)
  < PROTOCOL_DELIVERY
```

`call A` and `call B` must be present, nonblank, and distinct. The recovery request is identity adaptation, not a same-name retry.

## Model-visible identity verification

Protocol `tools/list` observations are insufficient to establish what the model received. The adapter wraps the public pinned-SDK `Model` boundary and records the controlled identity set supplied to model execution.

The relation closes only when:

1. the initial model turn exposes exactly the original controlled identity and not the replacement;
2. the live old-name call is rejected after the controlled swap;
3. the exact rejection becomes model-visible;
4. one host invalidation permits the first fresh post-invalidation discovery;
5. the recovery model turn exposes exactly the replacement controlled identity and not the stale original;
6. the recovery request names the exact replacement identity.

The hidden evaluator control tool is filtered from model-visible MCP tools. Any leakage blocks evaluation.

## Protocol-domain receipt

`create_identity_drift_protocol_receipt(...)` creates the `MCPFaultReceipt` from observed live stdio behavior, not configured fault material alone.

It binds:

- `TOOL_IDENTITY_DRIFT` fault identity;
- MCP protocol revision `2026-07-28`;
- configured TTL;
- exact original and replacement identities;
- stale unknown-tool rejection digest;
- deterministic replacement-result digest;
- exact ordinals for initial discovery, identity swap, stale call, cache invalidation, refreshed discovery, and recovery call;
- the identity-drift protocol observation boundary and receipt root.

The protocol receipt remains protocol evidence. It does not itself establish agent consumption or a trial verdict.

## Cross-domain bridge receipt

`MCPAgentToolIdentityDriftReceipt` binds the protocol relation to the exact model/agent relation.

The receipt includes or derives bindings for:

- scenario identity;
- revalidated protocol receipt and protocol-receipt root;
- exact original and replacement tool names;
- domain-separated original/replacement identity digests;
- stale and recovery OpenAI call IDs;
- strict canonical stale/recovery argument digests;
- protocol and model-visible stale-rejection digests;
- expected, protocol, and model-visible recovery-result digests;
- initial and refreshed model-visible controlled-identity-set digests;
- the six strict protocol ordinals;
- a domain-separated bridge receipt root.

Raw rejection text and deterministic recovery text are not duplicated into durable bridge receipt content when digests suffice.

## Fail-closed behavior

Evaluator/provenance uncertainty becomes `EVALUATION_ERROR / BLOCKED`. Examples include:

- wrong fault kind, malformed TTL, or malformed/unbound replacement identity;
- protocol revision drift;
- preconfigured MCP servers, prefixed MCP naming, unresolved/non-public model boundary, or local name collisions;
- hidden evaluator control-tool exposure;
- missing/ambiguous initial discovery or initial model exposure;
- first controlled call not using the original identity;
- failed controlled registry swap;
- cached discovery not preserving the old identity before the live lookup;
- stale old-name call unexpectedly succeeding or not proving an unknown-tool rejection;
- missing recovery call or more than one controlled recovery attempt;
- recovery before refreshed discovery;
- refreshed discovery/model exposure not containing exactly the replacement identity;
- recovery still using the original name or any unbound third name;
- missing/reused/ambiguous OpenAI call IDs;
- malformed, duplicate-key, non-finite, non-object, or provenance-mismatched arguments;
- request/result ambiguity or chronology that fails `request1 < result1 < request2 < result2`;
- replacement result mismatch;
- protocol/agent rejection mismatch;
- bridge-receipt or protocol-receipt tampering;
- replay evidence whose typed identity relation no longer revalidates.

A model that emits a removed old tool name after the refreshed model boundary may be rejected directly by the pinned SDK/MCP execution boundary. `TrialRunner` preserves that as `RUNTIME_ERROR / BLOCKED`; the harness does not fabricate an additional model turn merely to convert the same uncertainty into a different error category.

## Replay

Historical replay does not reconnect to MCP and does not rerun the OpenAI agent.

`EvidenceReplayAdapter` reuses persisted trial evidence, while `verify_protocol_delivery(...)` reparses and semantically revalidates the typed `MCPAgentToolIdentityDriftReceipt`, including its nested protocol receipt, scenario binding, identity relation, call IDs, arguments, digests, chronology, and receipt roots.

Replay therefore answers:

> Does this persisted historical evidence still prove the same identity-adaptation relation and deterministic verdict?

It does not assert current MCP registry state or current model/provider behavior.

## Deterministic integration boundary

The OpenAI integration lane uses:

- `openai-agents==0.22.0`;
- `mcp==2.1.1`;
- a fresh official `MCPServerStdio` subprocess per trial;
- MCP protocol revision `2026-07-28`;
- `agents.testing.ScriptedModel` rather than a provider API call;
- tracing disabled and sensitive trace data disabled.

The verified positive case proves old-name model exposure → real stale rejection → host refresh → replacement-name model exposure → exact replacement call → deterministic recovery → typed bridge closure → deterministic PASS when ordinary policy/outcome requirements pass.

Negative coverage includes no replacement call, removed-old-name reuse after refresh, extra controlled attempts, receipt/relation tampering, scenario drift, reused call identity, argument parsing ambiguity, non-finite values, wrong replacement binding, model-visible identity ambiguity, protocol-version/boundary drift, rejection mismatch, recovery mismatch, and strict chronology failures across provider-neutral and pinned-SDK layers.

## Non-claims

This assurance does **not** establish:

- model-initiated MCP refresh;
- automatic `notifications/tools/list_changed` handling;
- arbitrary rename, alias, fallback, or multi-tool migration graphs;
- simultaneous schema + identity migration beyond the isolated v1 contract;
- semantic equivalence of the old and replacement tools outside the controlled harness relation;
- cryptographic, globally unique, provider-attested, or target-attested tool identity;
- hosted/remote/Internet MCP behavior;
- production service discovery, DNS, registry, IAM, rollout, deployment, or cache-coordination correctness;
- generic retry, backoff, idempotency, concurrency, or distributed exactly-once behavior;
- live-provider model quality or availability;
- release acceptance merely because `PROTOCOL_DELIVERY` closes.

`tool_list_stale_cache` remains protocol-only with respect to agent behavior. Identity drift is bridged only by this exact host-refreshed official-stdio + pinned-SDK contract.
