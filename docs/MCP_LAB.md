# MCP Protocol Fault Laboratory

## Purpose

The MCP fault laboratory exercises **real Model Context Protocol behavior** without replacing the protocol with local function mocks. It uses official `mcp==2.1.1`, a fresh in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Its primary question is deliberately narrow:

> Did the trusted MCP client observe the exact controlled content or protocol-state relation that the test claims to exercise?

The answer is recorded as `MCPFaultReceipt`. That receipt is protocol evidence. **By itself** it is not an autonomous-agent verdict, an OpenAI `AttackDeliveryReceipt`, release authority, remote-transport assurance, or target-side attestation.

One separate integration path now consumes the same `TOOL_RESULT_POISON` fault contract through a fresh official MCP stdio server and the pinned OpenAI Agents SDK. That dedicated bridge is described under [Relationship to agent adversarial testing](#relationship-to-agent-adversarial-testing) and in [OpenAI Agents SDK Adapter](OPENAI_ADAPTER.md). It does not broaden the other five fault families.

Remote Streamable HTTP authorization and the separated OAuth flow remain independent evidence domains. See [MCP Remote Authorization](MCP_REMOTE_AUTH.md) and [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md).

## Six deterministic fault families

| Fault | Boundary | Receipt precondition | Agent bridge status |
|---|---|---|---|
| `tool_metadata_poison` | `tools/list` | target description equals exact canonical fault JSON | protocol-only |
| `tool_result_poison` | first `tools/call` | first result text equals exact canonical fault JSON and a second call recovers to benign data | dedicated controlled stdio bridge implemented |
| `tool_error` | first `tools/call` | SDK-generated model-visible `ToolError` contains the canonical payload at the exact expected suffix and a second call recovers | protocol-only |
| `tool_list_stale_cache` | cached `tools/list` | initial target present → server removes target → cached listing still contains target → forced refresh proves target absent | protocol-only |
| `tool_schema_drift` | cached discovery + call validation | cached old schema remains visible → stale arguments fail against current server schema → refresh exposes replacement schema → replacement arguments succeed | protocol-only |
| `tool_identity_drift` | cached discovery + tool lookup | cached old name remains visible → stale-name call fails → refresh exposes replacement name → replacement call succeeds | protocol-only |

The last three are relational protocol-state faults. Their receipts are withheld unless every leg of the relation closes.

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

The new tool-result bridge does not invalidate this rule. It adds a **specific additional proof step** for one result fault: exact protocol observation must be paired with one exact OpenAI agent tool request/result identity and model-visible output before `PROTOCOL_DELIVERY` exists.

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

### Schema drift

The v1 fixture binds an exact before/after contract:

```text
initial required schema     = {query: string}
replacement required schema = {customer_id: integer, include_history: boolean}
```

The proof requires old discovery, current-server rejection of old arguments, refreshed new discovery, and successful new-schema invocation. The cache is never treated as the call validator.

### Identity drift

The proof requires initial old name, cached old name after server rename, live rejection of the stale name, refreshed replacement identity, and successful replacement invocation. The rename is a protocol condition, not automatically an agent failure.

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

## Isolation and recovery

Every protocol probe creates a fresh server. Content result/error faults are first-call-only and require benign recovery. Discovery-state probes use fresh client cache state. Schema and identity drift additionally require successful operation under refreshed server truth.

These controls detect evaluator defects such as sticky fault state and cross-test cache contamination.

## CI boundary

MCP support is optional and isolated from the provider-neutral core:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp tests/integration/test_mcp_fault_lab.py
```

The dedicated protocol job requires neither provider credentials nor an external service.

For the cross-boundary OpenAI/MCP test, both optional groups are installed and the existing OpenAI deterministic job runs the dedicated stdio integration:

```bash
python -m pip install -e '.[dev,openai,mcp]'
pytest -m openai tests/integration/test_openai_mcp_tool_result_adapter.py
```

This reuses the existing OpenAI CI status context; it does not make the protocol-lab job an agent verdict job.

## Relationship to agent adversarial testing

### What remains separate

`MCPFaultLab` still returns protocol-domain evidence. An `MCPFaultReceipt` does not itself become `ATTACK_DELIVERY`, `PASS`, `FAIL`, or release acceptance.

`OpenAIAgentsAdapter` local `TOOL_RESULT` injection is also still a separate local-`FunctionTool` mechanism. It does not intercept MCP tools.

### What is now bridged

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
+ same-session benign recovery
        ↓
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic agent trial grading
```

The behavioral run makes exactly one target call. Recovery occurs only after the run, through the same live session and same arguments, so benign recovery cannot contaminate the agent transcript.

Missing consumption, multiple target calls, protocol-version drift, malformed result shape, agent-evidence ambiguity, output mismatch, or recovery mismatch fails closed as evaluator uncertainty.

The bridge proves same-call controlled delivery in the deterministic harness. It does not assert that the agent resisted the content merely because the bridge closed; deterministic policy/outcome oracles still decide behavior.

## Explicit non-claims

The six-fault protocol laboratory plus the one dedicated bridge do **not** establish:

- agent behavior for `tool_metadata_poison`, `tool_error`, stale-cache, schema-drift, or identity-drift faults;
- universal agent behavior for arbitrary MCP tool results, retries, multiple target calls, multiple MCP servers, or parallel plans;
- OpenAI hosted MCP interception or hosted third-party MCP fidelity;
- remote/Internet MCP behavior, TLS, DNS, reverse proxies, gateways, service meshes, packet faults, latency, disconnect, retry, or rate-limit assurance;
- general stdio transport robustness beyond the exact deterministic controlled subprocess path exercised by the bridge;
- public/cross-partition cache sharing, cache poisoning, arbitrary cache stores, notification invalidation, or TTL race correctness beyond the implemented relations;
- arbitrary schema migrations or arbitrary registry churn beyond the bound fixtures;
- malformed JSON-RPC/framing, duplicate/out-of-order responses, or header-routing faults;
- malicious MCP resources, templates, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- production authorization or identity-provider assurance;
- complete MCP conformance certification;
- target-side cryptographic delivery attestation;
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

This checkpoint identifies the audited merged implementation revision. Documentation-only synchronization is validated separately by its own full pull-request CI.

[← Documentation hub](README.md)
