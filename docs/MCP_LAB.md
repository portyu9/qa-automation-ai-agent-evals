# MCP Fault Laboratory

## Purpose

The MCP fault laboratory exercises **real Model Context Protocol behavior** without turning a local function stub into a pretend MCP server. It uses the official Python SDK `mcp==2.1.1`, a real in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

The laboratory answers a narrow question:

> Did the trusted MCP client observe the exact controlled fault at the protocol boundary the test claims to exercise?

That is **protocol delivery evidence**. It is not an autonomous-agent verdict, not an OpenAI `AttackDeliveryReceipt`, and not target-side attestation.

## Current deterministic surface

Four fault kinds are implemented:

| Fault | MCP boundary | Current behavior |
|---|---|---|
| `tool_metadata_poison` | `tools/list` | exact canonical fault JSON becomes one target tool description |
| `tool_result_poison` | first `tools/call` | exact canonical fault JSON becomes the first target call's text result |
| `tool_error` | first `tools/call` | controlled canonical fault JSON is carried unchanged inside the SDK's model-visible `ToolError` text envelope |
| `tool_list_stale_cache` | client-side `tools/list` cache | the target is initially listed under a private positive TTL, removed from the live server registry, still returned by a normal cached `Client.list_tools()` call, and then absent after `cache_mode="refresh"` forces current server truth |

Result and error faults are one-shot. The second target call returns controlled benign data, proving the fault does not become permanent server state.

The stale-discovery fault is different: it proves a protocol-state relation rather than malicious text delivery. It requires an initial live listing, a server-side removal, a stale cache hit, and a forced refresh that proves the target is no longer advertised.

## Protocol paths

Content faults use:

```text
MCPFaultSpec
    ↓
fresh official MCPServer
    ↓
official Client(mode="2026-07-28")
    ↓
tools/list
    ↓
tools/call(first)
    ↓
tools/call(second)
    ↓
exact public client observation
    ↓
MCPFaultReceipt
```

Stale discovery uses:

```text
MCPFaultSpec {"ttl_ms": ...}
    ↓
fresh MCPServer with private tools/list cache hint
    ↓
Client.list_tools()              → target present, TTL observed
    ↓
server.remove_tool(target)
    ↓
Client.list_tools()              → cached target still present
    ↓
Client.list_tools(cache_mode="refresh")
    ↓
refreshed listing                → target absent
    ↓
canonical relation observation
    ↓
MCPFaultReceipt
```

The connection is in-process but protocol-aware. It exercises the official SDK's modern server/client dispatch and response-cache behavior and does not require a port, subprocess, network service, model credential, or provider API call.

## Content-addressed fault contract

`MCPFaultSpec` binds:

- schema version;
- stable fault ID;
- revision;
- `MCPFaultKind`;
- exact tool name;
- canonical finite JSON payload.

The identity is SHA-256 over canonical fault material. Payload object key order therefore cannot silently create different identities for semantically identical JSON.

For metadata/result/error faults, complete canonical `payload_json` is the controlled malicious material. For `tool_list_stale_cache`, the payload must contain exactly one integer field, `ttl_ms`, between 1 and 86,400,000 milliseconds; that value is the exact private freshness declaration consumed by the laboratory.

The lab never chooses unrelated runtime fault parameters outside the content-addressed specification.

## Delivery receipts

`MCPFaultReceipt` is emitted only after the official client observes the expected boundary or relation. It binds:

- exact fault identity;
- fault kind;
- protocol version;
- tool name;
- concrete injection point;
- SHA-256 of the controlled canonical fault material;
- SHA-256 of the **exact canonical public-client observation**;
- domain-separated receipt root over those fields.

Raw malicious content is not duplicated into the receipt.

### Why two hashes matter

For direct metadata and result poisoning, controlled payload and observed text are identical:

```text
payload_sha256 == observation_sha256
```

For `ToolError`, the SDK intentionally creates a model-visible envelope:

```text
Error executing tool <tool>: <canonical fault payload>
```

The controlled payload remains an exact suffix, but the complete observed text differs. The receipt therefore records:

```text
payload_sha256 != observation_sha256
```

For `tool_list_stale_cache`, `payload_sha256` binds the canonical TTL fault specification while `observation_sha256` binds canonical JSON containing the initial, cached, and refreshed tool-name sets plus the observed TTL. Those are intentionally different domains: configured fault material versus verified protocol-state relation.

This prevents the evaluator from pretending a transformed content representation or stateful protocol fault is byte-identical to its configuration.

## Concrete injection points

```text
mcp:2026-07-28:tools/list:<tool>:description
mcp:2026-07-28:tools/call:<tool>:result.content[0].text
mcp:2026-07-28:tools/call:<tool>:error.content[0].text:message-suffix
mcp:2026-07-28:tools/list:cache-use-stale-after-remove:<tool>:refresh-proves-absent
```

A receipt is not created merely because a fault object exists or a server was configured. The official client observation must satisfy the complete fault-specific contract.

## Isolation and recovery

Every probe builds a fresh server. Within a result/error probe, the controlled fault applies only to the first call. The second call returns:

```text
benign:second
```

This verifies two different properties:

1. the intended fault really reached the first MCP call;
2. the harness itself did not accidentally turn the fault into persistent server contamination.

Metadata poison remains an advertised description for that fresh server instance while tool calls remain benign.

The stale-discovery probe also starts from a fresh server and fresh client cache. It verifies that the initial listing contains only the target, the server removes that target, an ordinary cached listing remains stale under the configured positive TTL, and an explicit refresh returns an empty listing. A receipt is withheld if any leg of that relation fails.

## CI boundary

MCP support is optional and isolated from the provider-neutral core:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp tests/integration/test_mcp_fault_lab.py
```

The `mcp` extra pins `mcp==2.1.1`. The ordinary deterministic suite does not install MCP, and the dedicated MCP CI job installs `.[dev,mcp]` explicitly. This prevents the repository from silently relying on the OpenAI adapter's transitive MCP dependency.

Current verified MCP checkpoint: **4/4 deterministic protocol tests passed** against protocol `2026-07-28`.

## Relationship to OpenAI adversarial channels

The MCP lab is deliberately **not** described as OpenAI `TOOL_RESULT`, `TOOL_METADATA`, or `RESOURCE` interception.

The OpenAI channel implementations act at documented OpenAI Agents SDK/local boundaries and produce `ATTACK_DELIVERY` evidence for framework adversarial trials.

The MCP lab instead produces protocol-specific `MCPFaultReceipt` evidence from the official MCP client. No current path wires an autonomous OpenAI agent through this lab and then derives an agent `PASS`/`FAIL` from the MCP fault.

Keeping those layers separate prevents protocol-delivery success from becoming fake behavioral assurance.

## Current non-claims

The implemented laboratory does **not** yet establish:

- remote Streamable HTTP, stdio, proxy, or network transport fault behavior;
- `Mcp-Method` / `Mcp-Name` header-routing fault coverage;
- authorization issuer validation, scope escalation, credential reuse, token binding, or CIMD behavior;
- public/cross-partition cache sharing, cache poisoning, custom/shared cache-store behavior, notification-driven invalidation, TTL-expiry behavior, cache races, renamed-tool discovery, or general cache correctness beyond the single tested private stale-after-removal relation;
- malformed JSON-RPC, invalid schemas, schema drift, duplicate/out-of-order responses, or protocol framing faults;
- malicious MCP resources, resource templates, prompts, roots, elicitation, sampling, or subscriptions;
- Tasks-extension long-running/cancellation/failure semantics;
- hosted or third-party MCP server fidelity;
- agent behavioral resistance to an MCP-delivered stimulus;
- remote target-side delivery attestation;
- protocol-conformance certification for the complete MCP specification.

Those are separate fault families and should move into this document only after executable coverage proves the stronger claim.

## Verification checkpoint

Repository source checkpoint associated with the current MCP layer:

- deterministic core: **181 passed, 15 deselected**;
- branch coverage: **93.14%** against the 90% gate;
- strict mypy: **0 issues across 37 source files**;
- OpenAI deterministic SDK: **11/11 passed**;
- MCP deterministic protocol: **4/4 passed**;
- Python 3.11 and 3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

[← Documentation hub](README.md)
