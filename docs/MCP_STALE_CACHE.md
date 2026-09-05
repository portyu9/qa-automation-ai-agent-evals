# MCP Stale-Cache Tool-Removal Assurance

## Purpose

This contract proves one exact **host-refreshed stale-tool removal delivery** relation across a live official MCP stdio session and the pinned OpenAI Agents SDK. It closes the cross-domain gap for `MCPFaultKind.TOOL_LIST_STALE_CACHE` without claiming that the model requested refresh, that the SDK autonomously recovered, or that target absence alone is safe agent behavior.

The controlled relation is:

```text
initial protocol discovery contains target
        ↓
initial public Model boundary contains target
        ↓
model selects target with exact {"query":"stale"} + stable call ID
        ↓
evaluator-only live control removes target
        ↓
normal cached tools/list still contains target
        ↓
real removed-target tools/call rejects as unknown tool
        ↓
exact rejection becomes model-visible
        ↓
evaluator/host invalidates one MCP tools cache
        ↓
first fresh post-invalidation tools/list proves target absent
        ↓
next public Model boundary proves target absent
+ exact stale rejection + same OpenAI call ID
        ↓
MCPAgentToolStaleCacheReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic policy/outcome grading
```

A verified bridge is an evaluation precondition. It is not automatic `PASS`.

## Ownership and trust boundary

Ownership is intentionally non-overlapping:

- the **controlled harness** owns live removal of the target tool;
- the **evaluator/host adapter** owns the one cache invalidation after the real stale-call rejection;
- the **official MCP session** owns initial/cached/refreshed discovery and call-time lookup results;
- the **pinned Agents SDK** owns conversion of MCP discovery into the tool set supplied through the public `Model` boundary;
- the **agent/model** owns its selected requests, but is not credited for the host-owned refresh;
- deterministic framework policy/outcome oracles remain behavioral grading authority.

The hidden removal control is filtered from the model-visible MCP tool set. If it leaks into agent-visible discovery, evaluation blocks.

## Controlled v1 contract

The existing stale-cache fault payload remains authoritative:

```json
{
  "ttl_ms": 60000
}
```

`ttl_ms` may vary within the existing positive bounded contract. The target name remains `fault.tool_name`. The controlled callable schema remains `query: string`, and the one stale request is bound to:

```json
{"query":"stale"}
```

Keeping identity and schema stable isolates stale discovery/removal from the separate schema-drift and identity-drift assurance contracts.

## Required protocol chronology

One live session must establish strict ordering:

```text
initial-list < removal < cached-list < stale-call < cache-invalidation < refreshed-list
```

Each leg is necessary:

1. initial discovery proves the target was actually advertised;
2. live removal changes current server truth;
3. cached rediscovery after removal proves the stale-cache condition rather than a plain removal;
4. the real removed-target call proves cached discovery is not call-time truth;
5. host invalidation is recorded as evaluator-owned action;
6. first post-invalidation discovery proves target absence.

The adapter does not infer any one of these facts from another.

## Public model-boundary verification

Protocol discovery alone is insufficient to claim model-visible delivery. The adapter requires a concrete public SDK `Model` and observes both `get_response(...)` and `stream_response(...)` paths.

The first model boundary must contain exactly the controlled target identity. After the real rejection and host invalidation, the next model boundary must contain no controlled target identity and must receive exactly one public SDK `function_call_output` carrying:

- the original stable OpenAI call ID;
- one exact `input_text` item;
- the exact rejection text observed from the live MCP call.

A protocol/model rejection mismatch, missing call identity, ambiguous output shape, or refreshed target still visible fails closed.

## Dedicated receipt

`MCPAgentToolStaleCacheReceipt` binds:

- receipt schema/version;
- exact scenario identity;
- a freshly revalidated nested stale-cache `MCPFaultReceipt`;
- exact target tool name;
- positive bounded TTL;
- stale OpenAI call ID;
- canonical stale-argument digest;
- exact live protocol rejection digest;
- exact model-visible rejection digest;
- initial model-visible controlled-tool-set digest;
- refreshed empty controlled-tool-set digest;
- all six protocol ordinals;
- a domain-separated bridge integrity root.

Raw rejection text and raw call arguments are not duplicated in the durable bridge receipt where digests suffice.

The nested `MCPFaultReceipt` keeps the existing standalone protocol meaning: target initially present, target still present in cached discovery after live removal, forced/fresh discovery proves target absent, and the configured TTL is bound. The bridge receipt adds the cross-domain facts that standalone protocol evidence cannot establish.

## Normalized evidence closure

The normalized agent relation contains exactly one controlled target request/result pair before delivery closes:

```text
TOOL_REQUEST(target, call A)
        <
TOOL_RESULT(call A, exact unknown-tool rejection)
        <
PROTOCOL_DELIVERY
```

The normalized request must use the exact target, stable call ID, and strict finite JSON arguments `{"query":"stale"}`. The matching result must be one exact text output whose digest equals the model-visible/live rejection digest.

`PROTOCOL_DELIVERY` is inserted immediately after that stale result. No replacement/recovery call is manufactured because the controlled target is intentionally absent after refresh.

## Replay

Historical replay does not reconnect to MCP or rerun the OpenAI agent. `verify_protocol_delivery(...)` reparses and revalidates `MCPAgentToolStaleCacheReceipt`, then correlates it back to the persisted normalized request/result pair.

Replay fails closed when:

- the typed receipt or nested protocol receipt no longer validates;
- scenario identity differs;
- target request count is not exactly one;
- call ID differs;
- strict canonical arguments differ;
- the normalized rejection differs from the receipt-bound digest;
- delivery does not occur after the matching request and result;
- the delivery source is unknown.

A historical receipt is therefore not treated as opaque JSON.

## Fail-closed behavior

Evaluator/provenance uncertainty becomes `EVALUATION_ERROR / BLOCKED`. Provider/SDK execution failure remains `RUNTIME_ERROR / BLOCKED`.

The adapter blocks for conditions including:

- wrong fault kind or malformed TTL;
- wrong negotiated MCP revision;
- preconfigured MCP servers or prefixed MCP naming;
- local target/control collisions;
- hidden control leakage;
- missing/ambiguous initial protocol or model exposure;
- missing stale target call;
- failed live removal;
- cached discovery that no longer contains the target after removal;
- removed-target call that succeeds or does not prove an unknown-tool rejection;
- missing/ambiguous cache refresh relation;
- refreshed discovery or model exposure that still contains the target;
- protocol/model rejection mismatch;
- missing/ambiguous OpenAI call identity;
- duplicate-key, malformed, non-finite, changed, or provenance-mismatched arguments;
- normalized request/result ambiguity;
- extra controlled target request after refresh;
- malformed/tampered receipt material or replay chronology.

If a model emits the removed target after the refreshed public model boundary and the pinned SDK rejects that request before another normal model turn, the runtime failure is preserved. The evaluator does not repair the subject or synthesize a continuation.

## Deterministic verification

The pinned deterministic SDK integration proves:

- target present at initial protocol and model boundaries;
- live removal occurs after model selection;
- cached target remains visible after removal;
- live removed-target lookup rejects as unknown tool;
- exact rejection reaches the next model boundary;
- host invalidation produces first fresh target-absent discovery;
- refreshed model boundary contains no controlled target;
- typed receipt and `PROTOCOL_DELIVERY` close;
- ordinary deterministic state/policy can still decide `PASS`;
- historical replay reproduces the same evidence root/verdict without rerunning MCP/OpenAI.

Negative deterministic coverage includes no target call and attempted reuse of the removed target after refreshed absence. Provider-neutral tests additionally cover discovery mismatch, refreshed-target leakage, changed arguments, rejection mismatch, TTL/chronology/root tampering, scenario mismatch, replay argument/result tampering, and delivery moved before its stale result.

## Non-claims

This contract does **not** establish:

- model-initiated MCP refresh;
- automatic `notifications/tools/list_changed` handling;
- generic cache invalidation policy or cache-coherence correctness;
- arbitrary TTL races, shared/distributed caches, or cross-process cache propagation;
- automatic behavioral recovery after tool retirement;
- generic deprecation/retirement migration;
- schema or identity migration beyond their separate contracts;
- cryptographic, globally unique, provider-attested, or target-attested tool identity;
- hosted/remote/Internet MCP;
- production service discovery, rollout, registry, DNS, IAM, proxy, deployment, or cache-coordination correctness;
- generic retry/backoff/idempotency;
- live-provider/model quality or availability;
- release acceptance merely because the bridge closes.

The exact claim is narrower: a controlled target remained stale in host discovery after live removal, its real live call rejected, host-owned invalidation made its absence visible at both fresh protocol discovery and the public model boundary, the exact rejection was delivered to that model boundary, and the relation is replay-verifiable through typed evidence.
