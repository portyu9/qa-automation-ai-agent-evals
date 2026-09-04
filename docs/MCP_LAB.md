# MCP Protocol Fault Laboratory

## Purpose

The MCP fault laboratory exercises **real Model Context Protocol behavior** without replacing the protocol with local function mocks. It uses the official Python SDK `mcp==2.1.1`, a fresh in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

The laboratory answers one bounded question:

> Did the trusted MCP client observe the exact controlled content or protocol-state relation that the test claims to exercise?

That is **protocol evidence**. It is not an autonomous-agent verdict, not an OpenAI `AttackDeliveryReceipt`, not a remote-transport assertion, and not target-side attestation.

Remote Streamable HTTP authorization is intentionally a separate evidence domain. See [MCP Remote Authorization](MCP_REMOTE_AUTH.md).

## Six deterministic fault families

| Fault | Boundary | Receipt precondition |
|---|---|---|
| `tool_metadata_poison` | `tools/list` | target description equals exact canonical fault JSON |
| `tool_result_poison` | first `tools/call` | first result text equals exact canonical fault JSON and a second call recovers to benign data |
| `tool_error` | first `tools/call` | SDK-generated model-visible `ToolError` contains the canonical payload at the exact expected suffix and a second call recovers |
| `tool_list_stale_cache` | cached `tools/list` | initial target present → server removes target → cached listing still contains target → forced refresh proves target absent |
| `tool_schema_drift` | cached discovery + call validation | cached old input schema remains visible after server replacement → stale old arguments fail against current server schema → refresh exposes replacement schema → replacement arguments succeed |
| `tool_identity_drift` | cached discovery + tool lookup | cached old tool name remains visible after server rename → stale-name call fails → refresh exposes only replacement name → replacement call succeeds |

The last three are **relational protocol-state faults**. Their receipts are withheld unless every leg of the relation closes.

## Why discovery, call validity, and agent behavior are separate

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

A stale `tools/list` response can be objectively real while a subsequent `tools/call` is evaluated against newer server truth. Conversely, a successful current call does not prove the client previously held current discovery. Neither observation says whether an autonomous agent noticed, understood, or resisted the condition.

This separation is the reason schema and identity drift are not graded by comparing an expected tool-call trajectory. The laboratory verifies observable protocol state and call results only.

## Protocol paths

### Direct content faults

```text
MCPFaultSpec
    ↓
fresh official MCPServer
    ↓
official Client(mode="2026-07-28")
    ↓
tools/list / tools/call
    ↓
exact public-client content observation
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

The v1 schema-drift fixture deliberately binds an exact before/after contract:

```text
initial required schema     = {query: string}
replacement required schema = {customer_id: integer, include_history: boolean}
```

The proof is:

```text
initial tools/list          → old schema
server replaces same name  → new schema becomes server truth
normal tools/list           → cached old schema
old-schema tools/call       → error under current server validation
refresh tools/list          → new schema
new-schema tools/call       → replacement:7:true
                              ↓
                       MCPFaultReceipt
```

The client cache is not treated as the call validator. The server's current schema remains authoritative at `tools/call` time.

### Identity drift

```text
initial tools/list          → old name
server removes old name
server adds replacement name
normal tools/list           → cached old name
old-name tools/call         → unknown-tool error
refresh tools/list          → replacement name only
replacement tools/call      → replacement:fresh
                              ↓
                       MCPFaultReceipt
```

This proves discovery identity drift without treating the rename as agent misbehavior.

## Content-addressed fault contract

`MCPFaultSpec` binds:

- schema version;
- stable fault ID and revision;
- `MCPFaultKind`;
- exact original tool name;
- canonical finite JSON payload.

Its identity is SHA-256 over canonical fault material.

For the three content faults, complete canonical `payload_json` is the controlled content. Stateful faults bind the exact deterministic parameters the laboratory consumes:

- `tool_list_stale_cache` — exactly one bounded positive `ttl_ms`;
- `tool_schema_drift` — bounded `ttl_ms` plus the exact v1 initial and replacement required-schema projections;
- `tool_identity_drift` — bounded `ttl_ms` plus one exact replacement tool name different from the original.

The lab does not invent unbound mutation parameters at runtime.

## Receipts and observation integrity

`MCPFaultReceipt` binds:

- exact fault identity and kind;
- protocol version;
- original tool name;
- concrete observation/injection point;
- SHA-256 of controlled canonical fault material;
- SHA-256 of the exact canonical client observation;
- a domain-separated receipt root.

Raw malicious content is not duplicated into the receipt.

Two hashes are necessary because configuration and observation are not always byte-identical:

- metadata/result poison: `payload_sha256 == observation_sha256`;
- `ToolError`: the SDK wraps the controlled message, so the hashes differ;
- stale cache: payload binds TTL while observation binds the initial/cached/refreshed relation;
- schema drift: payload binds TTL + expected schema migration while observation binds all three schema projections, stale-call failure, refreshed-call success, and observed TTL;
- identity drift: payload binds TTL + replacement name while observation binds initial/cached/refreshed names, stale-name failure, replacement-call success, and observed TTL.

This prevents a state transition or SDK transformation from being mislabeled as byte-identical delivery.

## Concrete observation points

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

Every probe creates a fresh server. Content result/error faults are first-call-only and require a second controlled benign response:

```text
benign:second
```

Discovery-state probes use a fresh client cache. Schema and identity drift additionally require a successful operation under refreshed server truth before the relation is considered closed.

The isolation contract catches two evaluator defects that would otherwise create false confidence: accidental sticky fault state and cross-test cache contamination.

## CI boundary

MCP support is optional and isolated from the provider-neutral core:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp tests/integration/test_mcp_fault_lab.py
```

The `mcp` extra directly declares `mcp==2.1.1`, `httpx2`, and `uvicorn`; the latter two are used by the separate remote-auth laboratory. The dedicated in-process MCP job does not require a provider credential or network service.

Verified protocol checkpoint: **6/6 deterministic MCP tests passed** against protocol `2026-07-28` at implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc` (protected-main CI run `33881346071`).

## Relationship to agent adversarial testing

The MCP fault laboratory is deliberately not folded into OpenAI `TOOL_RESULT`, `TOOL_METADATA`, or `RESOURCE` interception.

OpenAI adversarial channels produce `ATTACK_DELIVERY` evidence inside agent trials. The MCP protocol lab produces `MCPFaultReceipt` from an official MCP client observation. No current path converts that receipt into agent `PASS`, `FAIL`, or release acceptance.

Protocol delivery success therefore cannot become fake behavioral assurance.

## Explicit non-claims

The six-fault laboratory does **not** establish:

- agent behavior after consuming an MCP-delivered condition;
- OpenAI hosted/MCP tool interception;
- remote transport behavior beyond the separately documented loopback authorization laboratory;
- stdio, proxy, Internet, TLS, DNS, packet, latency, disconnect, or transport-chaos assurance;
- public/cross-partition cache sharing, cache poisoning, custom/shared cache stores, notification invalidation, TTL-expiry races, or general cache correctness beyond the exact relations implemented here;
- arbitrary schema migrations beyond the bound v1 before/after schema pair;
- arbitrary registry churn beyond the bound one-name replacement relation;
- malformed JSON-RPC/framing, duplicate/out-of-order responses, or `Mcp-Method`/`Mcp-Name` header-routing faults;
- malicious resources, resource templates, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- hosted third-party MCP server fidelity or complete MCP conformance certification;
- target-side delivery attestation.

Remote bearer authentication, scope enforcement, verifier-owned issuer/resource binding, and RFC 9728 protected-resource metadata are covered only by the separate [MCP Remote Authorization](MCP_REMOTE_AUTH.md) boundary.

## Verified implementation checkpoint

Implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc`, protected-main CI run `33881346071`:

- deterministic core: **330 passed, 23 deselected**;
- branch coverage: **93.61%** against the 90% gate;
- strict mypy: **0 issues across 40 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality, Ruff, formatter, Bandit, dependency audit, and package integrity: **7/7 CI jobs green**;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint identifies the audited implementation revision. This documentation-only synchronization is validated separately by pull-request CI and does not silently redefine the implementation evidence.

[← Documentation hub](README.md)
