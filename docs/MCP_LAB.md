# MCP Protocol Fault Laboratory

## Purpose

The MCP fault laboratory exercises **real Model Context Protocol behavior** without replacing the protocol with local function mocks. It uses official `mcp==2.1.1`, a fresh in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Its primary question is deliberately narrow:

> Did the trusted MCP client observe the exact controlled content or protocol-state relation that the test claims to exercise?

The answer is recorded as `MCPFaultReceipt`. That receipt is protocol evidence. **By itself** it is not an autonomous-agent verdict, an OpenAI `AttackDeliveryReceipt`, release authority, remote-transport assurance, or target-side attestation.

Six separate deterministic integration paths consume selected fault contracts through a fresh official MCP stdio server and the pinned OpenAI Agents SDK:

- `TOOL_METADATA_POISON` — exact controlled target description observed through official MCP discovery and bound to the exact target tool definition supplied at the public model boundary, without requiring a target call;
- `TOOL_RESULT_POISON` — exact same-call result delivery with post-run same-session recovery;
- `TOOL_ERROR` — exact model-visible error followed by one causal same-argument retry and benign recovery on the same session;
- `TOOL_LIST_STALE_CACHE` — exact initial target exposure, hidden live removal, cached post-removal target discovery, real unknown-tool rejection, evaluator-owned cache invalidation, first fresh target-absent discovery, and exact target-absent public-model exposure carrying the same rejection;
- `TOOL_SCHEMA_DRIFT` — exact v1 model-visible schema, hidden live v2 replacement, real stale-call rejection, evaluator-owned cache invalidation, first fresh v2 discovery, and one corrected v2 behavioral call on the same session;
- `TOOL_IDENTITY_DRIFT` — exact original model-visible identity, hidden live old→replacement registry mutation, real old-name rejection, evaluator-owned cache invalidation, first fresh replacement discovery, and one exact replacement-name behavioral call on the same session.

Those dedicated bridges are described under [Relationship to agent adversarial testing](#relationship-to-agent-adversarial-testing), in [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md), and in [OpenAI Agents SDK Adapter](OPENAI_ADAPTER.md). They do not broaden the remaining fault families. The schema- and identity-drift bridges do not claim model-initiated refresh or automatic `tools/list_changed` handling.

Remote Streamable HTTP authorization and the separated OAuth flow remain independent evidence domains. See [MCP Remote Authorization](MCP_REMOTE_AUTH.md) and [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md).

## Six deterministic fault families

| Fault | Boundary | Receipt precondition | Agent bridge status |
|---|---|---|---|
| `tool_metadata_poison` | `tools/list` | target description equals exact canonical fault JSON | dedicated controlled stdio model-visible metadata bridge |
| `tool_result_poison` | first `tools/call` | first result text equals exact canonical fault JSON and a second call recovers to benign data | dedicated controlled stdio result bridge |
| `tool_error` | first `tools/call` | SDK-generated model-visible `ToolError` contains the canonical payload at the exact expected suffix and a second call recovers | dedicated controlled stdio causal retry/recovery bridge |
| `tool_list_stale_cache` | cached `tools/list` | initial target present → server removes target → cached listing still contains target → forced refresh proves target absent | dedicated controlled stdio host-refreshed removal-delivery bridge |
| `tool_schema_drift` | cached discovery + call validation | cached old schema remains visible → stale arguments fail against current server schema → refresh exposes replacement schema → replacement arguments succeed | dedicated controlled stdio host-refreshed schema-adaptation bridge |
| `tool_identity_drift` | cached discovery + tool lookup | cached old name remains visible → stale-name call fails → refresh exposes replacement name → replacement call succeeds | dedicated controlled stdio host-refreshed identity-adaptation bridge |

The last three are relational protocol-state faults. Their standalone laboratory receipts are withheld unless every leg of the relation closes. All three also have separate agent bridges with additional model-visible, agent-evidence, and host-refresh requirements beyond the laboratory receipt. Stale-cache closes at verified target removal/rejection/refreshed absence; schema and identity drift additionally require corrected behavioral calls under refreshed truth.

## Discovery, call validity, and agent behavior are different claims

```text
cached discovery
      ≠
current server contract
      ≠
call-time validity
      ≠
refreshed discovery
      ≠
agent behavior
```

A stale `tools/list` response can be objectively real while a subsequent `tools/call` is evaluated against newer server truth. Conversely, a successful current call does not prove the client previously held current discovery. Neither observation alone says whether an autonomous agent noticed, understood, or resisted the condition.

The six agent bridges do not invalidate this rule. They add **fault-specific proof steps**:

- metadata poison must pair the exact official `tools/list` description observation with one exact model-visible target definition and matching JSON-schema digest; no target invocation is required because metadata can affect selection before any call;
- result poison must be paired with one exact OpenAI target request/result identity and logical model-visible output;
- ToolError recovery must additionally prove distinct call identities, same canonical arguments, exact error/recovery outputs, and strict chronology `request₁ < result₁ < request₂ < result₂` before the second call can be credited as a retry;
- stale-cache removal delivery must additionally prove initial model-visible target presence, hidden live removal, cached post-removal target presence, real unknown-tool rejection, one host invalidation, first fresh target absence, exact rejection delivery to the target-absent public model boundary, one stable call identity, exact bound arguments, and no extra controlled target request;
- schema-drift adaptation must additionally prove v1 model-visible discovery, a hidden evaluator-owned live swap, real stale-call rejection, one host cache invalidation, first fresh post-invalidation v2 discovery, distinct stale/recovery call identities, exact bound v1/v2 arguments, and recovery only after v2 becomes model-visible;
- identity-drift adaptation must additionally prove exact original model-visible identity, hidden old→replacement mutation, real unknown-tool rejection, one host cache invalidation, first fresh replacement-only discovery, exact replacement model visibility, distinct call IDs, exact arguments/results, and recovery only after the replacement identity is visible.

## Protocol paths

### Direct content faults

```text
MCPFaultSpec
    ↓
fresh official MCPServer
    ↓
official Client / protocol 2026-07-28
    ↓
tools/list / tools/call
    ↓
exact public-client observation
    ↓
MCPFaultReceipt
```

### Stale discovery

```text
initial tools/list → target present + positive private TTL
server.remove_tool(target)
normal tools/list  → cached target still present
refresh tools/list → target absent
                     ↓
              MCPFaultReceipt
```

The dedicated stale-cache agent bridge adds a cross-domain relation to the standalone discovery proof: the target must be model-visible before selection, the harness removes it before live lookup, cached host discovery must still advertise it, the live call must reject, and host-owned invalidation must make target absence plus the exact rejection visible at the next public model boundary. No replacement call is manufactured. See [MCP Stale-Cache Tool-Removal Assurance](MCP_STALE_CACHE.md).

### Schema drift

The v1 fixture binds an exact before/after contract:

```text
initial required schema      = {query: string}
replacement required schema  = {customer_id: integer, include_history: boolean}
```

The standalone protocol proof requires old discovery, current-server rejection of old arguments, refreshed new discovery, and successful new-schema invocation. The cache is never treated as the call validator.

The agent bridge adds a separate behavioral relation. Its hidden server-side swap occurs only after the model has selected the v1-shaped call, and the host invalidates cached discovery only after the real stale-call rejection. That design prevents the model from being credited for a refresh action it did not perform.

### Identity drift

The standalone proof requires initial old name, cached old name after server rename, live rejection of the stale name, refreshed replacement identity, and successful replacement invocation. The rename is a protocol condition, not automatically an agent failure.

The dedicated agent bridge adds a stronger cross-domain requirement: the public pinned-SDK model boundary must first expose exactly the old controlled identity, then after the stale rejection and host-owned invalidation expose exactly the replacement controlled identity. Only a distinct replacement-name request made after that exposure can qualify as adaptation. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

## Content-addressed fault contract

`MCPFaultSpec` binds:

- schema version;
- stable fault ID and revision;
- `MCPFaultKind`;
- exact original tool name;
- canonical finite JSON payload.

Its identity is SHA-256 over canonical fault material.

For direct content faults, complete canonical `payload_json` is the controlled content. Stateful faults bind the exact deterministic parameters consumed by the laboratory, including bounded TTL and the bound before/after schema or identity relation.

The lab does not invent unbound mutation parameters at runtime.

## Receipts and observation integrity

`MCPFaultReceipt` binds:

- exact fault identity and kind;
- protocol version;
- original tool name;
- concrete observation point;
- SHA-256 of controlled canonical fault material;
- SHA-256 of the exact canonical client observation;
- a domain-separated receipt root.

Raw malicious content is not duplicated into the receipt.

Two hashes are required because configuration and observation are not always byte-identical:

- metadata/result poison: payload and observation digests can be equal;
- `ToolError`: the SDK wraps the controlled message, so the observation differs;
- stale cache/schema drift/identity drift: the observation is a canonical multi-step relation rather than the raw configured payload.

This prevents SDK transformation or state transition from being mislabeled as byte-identical delivery.

## Concrete protocol observation points

```text
mcp:2026-07-28:tools/list:<tool>:description
mcp:2026-07-28:tools/call:<tool>:result.content[0].text
mcp:2026-07-28:tools/call:<tool>:error.content[0].text:message-suffix
mcp:2026-07-28:tools/list:cache-use-stale-after-remove:<tool>:refresh-proves-absent
mcp:2026-07-28:tools/list:schema-drift:<tool>:cached-old:call-rejects-old:refresh-new
mcp:2026-07-28:tools/list:identity-drift:<tool>:cached-old-name:call-rejects-old:refresh-new-name
```

A receipt is never created merely because a fault object exists or the server was mutated.

The stale-cache agent bridge additionally binds the live rejection, exact stale call identity/arguments, target-present→target-absent public-model transition, and strict removal/cache/invalidation ordinals. The schema-drift agent bridge uses a separate bridge-specific observation relation that additionally binds initial/cached/refreshed schema digests, host invalidation chronology, stale/recovery observations, and the exact corrected agent call. The identity-drift agent bridge likewise binds the exact original/replacement identities, model-visible controlled identity sets, distinct call IDs, argument/rejection/recovery digests, and the same six-leg host-refresh chronology.

## Isolation and recovery

Every protocol probe creates a fresh server. Content result/error faults are first-call-only and require benign recovery. Discovery-state probes use fresh client cache state. Schema and identity drift additionally require successful operation under refreshed server truth.

These controls detect evaluator defects such as sticky fault state and cross-test cache contamination.

The standalone protocol-lab recovery checks and the agent bridges answer different questions. The lab proves the protocol relation. The ToolError bridge proves the **agent-visible first error causally precedes one behavioral retry**. The stale-cache bridge proves the **removed target's real rejection causally precedes host-refreshed target absence plus exact rejection delivery at the public model boundary**, without inventing a recovery call. The schema-drift bridge proves the **agent's corrected v2 call occurs only after host-owned refresh makes v2 model-visible**. The identity-drift bridge proves the **agent's replacement-name call occurs only after host-owned refresh makes that exact replacement identity model-visible**.

## CI boundary

MCP support is optional and isolated from the provider-neutral core:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp tests/integration/test_mcp_fault_lab.py
```

The dedicated protocol job requires neither provider credentials nor an external service.

For the cross-boundary OpenAI/MCP tests, both optional groups are installed and the existing OpenAI deterministic job runs all six stdio bridge families:

```bash
python -m pip install -e '.[dev,openai,mcp]'
pytest -m openai \
  tests/integration/test_openai_mcp_tool_metadata_adapter.py \
  tests/integration/test_openai_mcp_tool_result_adapter.py \
  tests/integration/test_openai_mcp_tool_error_recovery_adapter.py \
  tests/integration/test_openai_mcp_tool_schema_drift_adapter.py \
  tests/integration/test_openai_mcp_tool_schema_drift_contract.py \
  tests/integration/test_openai_mcp_tool_identity_drift_adapter.py \
  tests/integration/test_openai_mcp_tool_stale_cache_adapter.py
```

This reuses the existing OpenAI CI status context; it does not make the protocol-lab job an agent verdict job.

## Relationship to agent adversarial testing

### What remains separate

`MCPFaultLab` still returns protocol-domain evidence. An `MCPFaultReceipt` does not itself become `ATTACK_DELIVERY`, `PASS`, `FAIL`, or release acceptance.

`OpenAIAgentsAdapter` local `TOOL_RESULT` injection is also still a separate local-`FunctionTool` mechanism. It does not intercept MCP tools.

### Tool-metadata model-visible delivery bridge

`OpenAIAgentsMCPToolMetadataAdapter` implements one explicit cross-domain contract for `TOOL_METADATA_POISON`:

```text
MCPFaultSpec(tool_metadata_poison)
        ↓
fresh official MCPServerStdio subprocess
        ↓
exact target description observed through official tools/list
        ↓
MCPFaultReceipt
        ↓
pinned Agents SDK converts the MCP target to a model Tool
        ↓
public Model observer sees exactly one target definition
+ exact description equivalence
+ protocol/model JSON-schema digest equality
        ↓
MCPAgentToolMetadataReceipt
        ↓
PROTOCOL_DELIVERY before normalized model/agent behavior
        ↓
deterministic agent trial grading
```

The target does **not** need to be called. That is intentional: poisoned discovery metadata can influence tool selection before any invocation exists. Leading pre-model `ATTACK_DELIVERY` evidence remains before metadata delivery in compound trials; replay rejects a metadata receipt moved after normalized behavioral evidence. The bridge proves exposure at the controlled model boundary, not model attention, compliance, resistance, or behavioral safety.

### Result delivery bridge

`OpenAIAgentsMCPToolResultAdapter` implements one explicit cross-domain contract for `TOOL_RESULT_POISON`:

```text
MCPFaultSpec(tool_result_poison)
        ↓
fresh official MCPServerStdio subprocess
        ↓
agent makes exactly one target MCP call
        ↓
exact first result observed → MCPFaultReceipt
        ↓
exact OpenAI TOOL_REQUEST call_id
+ exactly one matching TOOL_RESULT
+ output equivalence
+ same-session benign recovery after the run
        ↓
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic agent trial grading
```

The behavioral run makes exactly one target call. Recovery occurs only after the run, through the same live session and same arguments, so benign recovery cannot contaminate the agent transcript.

Missing consumption, multiple target calls, protocol-version drift, malformed result shape, agent-evidence ambiguity, output mismatch, or recovery mismatch fails closed as evaluator uncertainty.

### ToolError retry/recovery bridge

`OpenAIAgentsMCPToolErrorRecoveryAdapter` implements a distinct two-call behavioral contract for `TOOL_ERROR`:

```text
MCPFaultSpec(tool_error)
        ↓
fresh official MCPServerStdio subprocess
        ↓
TOOL_REQUEST(error_call_id)
        ↓
real first-call MCP ToolError → MCPFaultReceipt
        ↓ exact model-visible error equivalence
TOOL_RESULT(error_call_id)
        ↓
TOOL_REQUEST(retry_call_id; same canonical arguments)
        ↓ same live MCP session
TOOL_RESULT(retry_call_id; exact benign recovery)
        ↓
MCPAgentToolErrorRecoveryReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic agent trial grading
```

The adapter requires exactly two target calls, distinct non-empty OpenAI call IDs, canonical argument equality, exactly one normalized result for each call, exact error/recovery observation equivalence, and strict normalized chronology:

```text
request₁ < result₁ < request₂ < result₂
```

That chronology is an assurance condition, not presentation detail. If two identical calls are pre-issued before the first error result, the second call is **not** accepted as a retry and evaluation blocks with `mcp_error_retry_causality_unverified`.

Missing retry, more than one retry, changed arguments, protocol-version drift, malformed/ambiguous evidence, wrong error representation, wrong recovery, or non-causal ordering fails closed as evaluator uncertainty.

### Stale-cache host-refresh/removal-delivery bridge

`OpenAIAgentsMCPToolStaleCacheAdapter` implements the cross-domain contract for `TOOL_LIST_STALE_CACHE`: initial protocol/model target presence → hidden live target removal → cached post-removal target presence → real unknown-tool rejection → host invalidation → first fresh target-absent discovery → target-absent public model boundary carrying the exact rejection → `MCPAgentToolStaleCacheReceipt` → `PROTOCOL_DELIVERY`. Exactly one controlled stale request/result pair is required; no synthetic recovery call is part of bridge closure. See [MCP Stale-Cache Tool-Removal Assurance](MCP_STALE_CACHE.md).

### Schema-drift host-refresh/adaptation bridge

`OpenAIAgentsMCPToolSchemaDriftAdapter` implements a separate two-call behavioral contract for `TOOL_SCHEMA_DRIFT`:

```text
model receives v1 schema
        ↓
TOOL_REQUEST(stale_call_id; v1 arguments)
        ↓
hidden evaluator-only live swap to v2
        ↓
real MCP validation rejects stale v1 arguments
        ↓
TOOL_RESULT(stale_call_id; exact model-visible rejection)
        ↓
host invalidates cached tool discovery once
        ↓
first fresh post-invalidation tools/list exposes v2
        ↓
model receives v2 schema + stale rejection
        ↓
TOOL_REQUEST(recovery_call_id; exact v2 arguments)
        ↓ same live MCP session
TOOL_RESULT(recovery_call_id; exact replacement result)
        ↓
MCPAgentToolSchemaDriftReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic agent trial grading
```

The adapter requires exactly two target calls, distinct non-empty OpenAI call IDs, exact bound v1/v2 schemas and arguments, one real stale rejection, one host cache invalidation, refreshed v2 discovery before recovery, exact protocol/model-visible rejection equivalence, exact replacement-result equivalence, and strict protocol chronology:

```text
initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call
```

Later SDK turns may reuse the already-refreshed v2 cache. The bridge therefore distinguishes one fresh post-invalidation discovery from harmless cached reads. Recovery before refreshed discovery, repeated stale arguments, extra target calls, control-tool leakage, wrong schema/result observations, or receipt tampering fails closed as evaluator uncertainty.

### Identity-drift host-refresh/adaptation bridge

`OpenAIAgentsMCPToolIdentityDriftAdapter` implements a separate two-call behavioral contract for `TOOL_IDENTITY_DRIFT`:

```text
model receives exact original identity
        ↓
TOOL_REQUEST(stale_call_id; original name)
        ↓
hidden evaluator-only live old→replacement swap
        ↓
real MCP lookup rejects removed old name
        ↓
TOOL_RESULT(stale_call_id; exact model-visible unknown-tool rejection)
        ↓
host invalidates cached tool discovery
        ↓
first fresh post-invalidation tools/list exposes replacement only
        ↓
model receives exact replacement identity + stale rejection
        ↓
TOOL_REQUEST(recovery_call_id; exact replacement name)
        ↓ same live MCP session
TOOL_RESULT(recovery_call_id; exact deterministic recovery)
        ↓
MCPAgentToolIdentityDriftReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic agent trial grading
```

The adapter requires exactly two controlled attempts; exact original then replacement identities; distinct non-empty OpenAI call IDs; strict finite canonical argument provenance; one real unknown-tool stale rejection; host invalidation only after that rejection; refreshed replacement-only protocol and model-visible identity sets; exact recovery output; and strict protocol chronology:

```text
initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call
```

The harness owns the rename and the host adapter owns invalidation. The model is credited only for choosing the replacement after it is actually visible. Missing recovery, stale-name reuse, an unbound identity, call-ID reuse, extra controlled attempts, recovery before refresh, ambiguous discovery/model exposure, wrong arguments/results, control-tool leakage, or receipt tampering fails closed. A removed old name emitted after refresh may also be rejected directly by the pinned SDK/MCP boundary and is preserved as `RUNTIME_ERROR / BLOCKED` rather than being repaired. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

All five bridges establish delivery/recovery/adaptation preconditions only. They do not assert safe subject behavior; deterministic policy/outcome oracles still decide PASS/FAIL.

## Explicit non-claims

The six-fault protocol laboratory plus the five dedicated bridges do **not** establish:

- model attention to, interpretation of, compliance with, or resistance to a verified `tool_metadata_poison` description;
- agent behavior for generic stale-cache behavior beyond the protocol-only stale-cache laboratory;
- universal agent behavior for arbitrary MCP tool results, errors, schema changes, or identity migrations;
- generic retry/backoff/idempotency correctness beyond the exact one-retry ToolError relation;
- model-initiated MCP refresh or automatic `tools/list_changed` handling;
- arbitrary schema compatibility, coercion/default/optional-field semantics, or arbitrary schema migrations beyond the bound v1/v2 fixture;
- arbitrary rename, alias, fallback, or multi-tool migration graphs beyond the bound identity-drift fixture;
- semantic equivalence of old and replacement tools merely because the controlled fixture binds them into one relation;
- multiple controlled MCP servers or arbitrary parallel target plans;
- OpenAI hosted MCP interception or hosted third-party MCP fidelity;
- remote/Internet MCP behavior, TLS, DNS, reverse proxies, gateways, service meshes, packet faults, latency, disconnect, retry, or rate-limit assurance;
- general stdio transport robustness beyond the exact deterministic controlled subprocess paths exercised by the bridges;
- public/cross-partition cache sharing, cache poisoning, arbitrary cache stores, notification invalidation, or TTL race correctness beyond the implemented relations;
- arbitrary registry churn beyond the bound identity fixture;
- malformed JSON-RPC/framing, duplicate/out-of-order responses, or header-routing faults;
- malicious MCP resources, templates, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- production authorization or identity-provider assurance;
- complete MCP conformance certification;
- provider-side or target-side cryptographic identity/delivery attestation;
- release acceptance from a protocol or bridge receipt alone.

Remote bearer authentication, scope enforcement, verifier-owned issuer/resource binding, and RFC 9728 metadata remain covered only by [MCP Remote Authorization](MCP_REMOTE_AUTH.md). Authorization-code/PKCE/introspection behavior remains covered only by [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md).

## Verified implementation checkpoint

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including controlled MCP stdio bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint remains a historical audited merged implementation revision. Capabilities added after it, including ToolError recovery, host-refreshed schema-drift adaptation, and host-refreshed identity-drift adaptation, are accepted only after their own exact-head CI, merge, and post-merge `main` verification.

[← Documentation hub](README.md)
