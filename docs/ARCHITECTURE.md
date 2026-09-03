# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes provider/model configuration, application revision, instructions, tool schemas, authority policy, memory policy, adapter identity, and adapter version.

The architecture starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial derivation
├── controlled OpenAI attack injectors
│   ├── USER_INPUT
│   ├── local FunctionTool TOOL_RESULT
│   ├── local FunctionTool TOOL_METADATA description
│   ├── per-trial Session-history MEMORY
│   ├── structured inline-file RESOURCE
│   ├── first-native-handoff context
│   └── targeted runtime-context ENVIRONMENT
├── attack-delivery verifier
├── deterministic MCP protocol fault laboratory
│   ├── tools/list description poison
│   ├── first tools/call result poison
│   ├── first tools/call model-visible ToolError
│   └── private tools/list stale cache after server-side removal with refresh truth
├── evidence normalization and persistence verification
├── exact-identity replay
├── deterministic policy and outcome oracles
├── statistical assurance
├── assurance-report verification
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory + resources + handoffs + app context

External systems
└── providers, hosted/external tools, remote MCP servers, production memory/retrieval,
    target systems, infrastructure, fault injectors
```

External content can become evidence or adversarial stimulus. It does not become control-plane authority merely because a model, tool, MCP server, resource, session, handoff, application context, or external service produced it.

## Identity contracts

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, and tags.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

The MCP layer has a separate identity domain. `MCPFaultSpec` binds schema, fault ID/revision, `MCPFaultKind`, exact tool name, and canonical finite JSON payload. For content faults that payload is the controlled content. For `tool_list_stale_cache`, it instead binds the exact bounded positive `ttl_ms` parameter consumed by the laboratory. A protocol fault does not silently become an `AttackFixture`, because protocol delivery and agent behavioral grading answer different questions.

## Attack delivery is an evaluation precondition

An adversarial agent scenario is behaviorally gradeable only after one exact matching `ATTACK_DELIVERY` receipt verifies.

```text
unverified delivery                         → BLOCKED
verified delivery + deterministic violation → FAIL
verified delivery + deterministic closure   → PASS
```

The receipt binds exact scenario identity, attack identity, channel, concrete injection point, canonical payload SHA-256, and domain-separated receipt root. It is control-plane integrity evidence, not cryptographic target-side attestation.

## Seven OpenAI channel boundaries

`OpenAIAgentsAdapter` implements all seven generic `AttackChannel` categories at scoped SDK/local boundaries:

- `USER_INPUT` — exact canonical fixture JSON as second ordered `Runner.run` user message;
- local `TOOL_RESULT` — first matching copied local `FunctionTool` result replacement, call-ID-bound;
- description-level `TOOL_METADATA` — copied local `FunctionTool.description` only;
- session-history `MEMORY` — fresh per-trial SDK `Session` prior user item;
- inline-file `RESOURCE` — exact canonical JSON as structured `input_file.file_data`;
- native `HANDOFF` — exact canonical JSON appended to first actual SDK handoff context while preserving destination;
- runtime-context `ENVIRONMENT` — exact canonical JSON returned for one exact string key only during the first matching local `FunctionTool` invocation, with delivery created only on actual value consumption.

These seven categories are **not universal production interception claims**. Each implementation is bounded by its documented concrete surface.

## MCP protocol fault boundary

`MCPFaultLab` is provider-neutral protocol test infrastructure. It uses the official Python SDK `mcp==2.1.1`, creates a fresh real `MCPServer`, and connects an official `Client` in modern `2026-07-28` mode.

```text
content-addressed MCPFaultSpec
        ↓
fresh MCPServer
        ↓
official Client / protocol 2026-07-28
        ↓
content observation or protocol-state relation
        ↓
MCPFaultReceipt
```

The current implementation closes four exact protocol observations:

- target tool description returned by `tools/list` equals canonical fault JSON;
- first target `tools/call` result text equals canonical fault JSON;
- first target `ToolError` preserves canonical fault JSON inside the SDK-generated model-visible error envelope;
- a private positive-TTL `tools/list` result remains visible from the client cache after the target is removed from the live server registry, while `cache_mode="refresh"` proves the current listing no longer contains the target.

The stale-discovery path is deliberately relational:

```text
initial Client.list_tools() → target present + configured TTL observed
server.remove_tool(target)
Client.list_tools()         → target still present from fresh cache
Client.list_tools(refresh)  → target absent from live server truth
```

Result/error probes execute a second benign call to prove one-shot recovery. Every probe uses a fresh server; the stale-discovery probe also starts with a fresh client cache, so one probe cannot contaminate another.

`MCPFaultReceipt` deliberately binds both `payload_sha256` and `observation_sha256`. They match when the protocol exposes controlled content directly. They differ when the SDK wraps the payload in the `ToolError` envelope, and for the stale-cache fault they differ because the payload binds TTL configuration while the observation binds canonical initial/cached/refreshed tool-name sets plus the observed TTL. That distinction records protocol transformation or stateful relation instead of pretending neither occurred.

This MCP receipt is **not** an OpenAI `ATTACK_DELIVERY` event and does not derive an agent `PASS`/`FAIL`. Agent-through-MCP behavioral assurance remains a later integration layer.

See [MCP Fault Laboratory](MCP_LAB.md).

## Local-tool isolation

For OpenAI result, metadata, and environment attacks, the adapter resolves one exact local SDK `FunctionTool`, copies it, and clones the agent with a fresh tools list. The reusable original tool and agent remain unchanged.

Result replacement and metadata poisoning alter only the copied tool's requested boundary. Environment injection additionally requires `run_context` to be `None` or a string-keyed `Mapping`.

## Environment specialization

The SDK local-context boundary is materially different from prompt or resource input. `Runner.run(..., context=...)` carries application-owned local data/dependencies through `RunContextWrapper.context`; the SDK does not automatically send that context to the LLM.

For an `ENVIRONMENT` fixture, the adapter snapshots base mapping context into a read-only per-trial overlay and uses task-local `ContextVar` activation during the first targeted tool invocation.

```text
target FunctionTool call
        ↓ activate call-scoped overlay
subject reads ctx.context[<key>] or .get(<key>)
        ↓
exact canonical AttackFixture.payload_json
        ↓ create call-ID-bound ATTACK_DELIVERY
        ↓
tool returns through ordinary SDK path
```

Mere configuration, tool execution, or key membership does not establish delivery. If the target tool never reads the value, there is no receipt and the adversarial trial is `BLOCKED`.

This gives the framework a useful distinction between **environment availability** and **environment consumption**.

## Evidence chronology

Important OpenAI channel-specific ordering includes:

```text
TOOL_RESULT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
ENVIRONMENT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:      HANDOFF → ATTACK_DELIVERY
```

User-input, metadata, memory, and resource structures can be prepared before subject execution; independent SDK tests prove the prepared content reaches the tested model/tool boundary.

MCP protocol receipts are a separate evidence family. They record exact client-side protocol observation or a canonical relation derived from public client fields and are not inserted into agent trial chronology until a future integration contract explicitly defines that bridge.

## Authority remains fail-closed

`AuthorityPolicy` controls allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown authority is not permission.

Deterministic policy checks include unauthorized tools, privileged use without approval, out-of-scope resources, explicit policy violations, tool-call budget excess, and handoff budget excess. Critical policy failure is non-compensatory.

Adversarial derivation cannot broaden authority.

## Adapter and runtime failure separation

`AgentAdapter` executes and normalizes; it does not grade itself.

`AdapterPreconditionError` represents an evaluator-controlled prerequisite that cannot be satisfied, such as malformed channel payloads, unavailable targets, unbindable call identity, or unsupported runtime-context type. `TrialRunner` converts this to `EVALUATION_ERROR / BLOCKED`.

Provider/SDK execution exceptions remain `RUNTIME_ERROR / BLOCKED`.

Neither is rewritten as subject `FAIL`.

The MCP laboratory currently returns protocol observations rather than `TrialEvidence`; it therefore does not manufacture trial failure semantics from an MCP client/server exception.

## Persistence and replay

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, and semantic evidence roots before reuse. Local integrity hashes do not authenticate a hostile writer who can coherently replace all associated bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not re-run the agent, provider, tool, session, resource, handoff, environment injector, or MCP protocol probe and cannot establish fresh delivery.

## Statistical and release authority

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance.

MCP protocol-probe success is not currently an input to release acceptance unless a caller separately establishes the required agent/evaluation contract.

## Current boundary

The framework currently provides deterministic contracts, content-addressed adversarial scenarios, evidence-bound OpenAI delivery verification, all seven generic OpenAI adapter channel categories at scoped boundaries, a deterministic official-SDK MCP protocol fault laboratory with three content faults plus one private stale-discovery cache relation, integrity-verified local persistence, exact historical replay, deterministic policy/outcome oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, failure minimization, and credential-free deterministic SDK tiers.

Verified checkpoint:

- deterministic core: **181 passed, 15 deselected**;
- branch coverage: **93.14%**;
- strict mypy: **0 issues across 37 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- deterministic MCP protocol: **4/4 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

Credentialed live-provider assurance, agent-through-MCP behavioral grading, remote MCP transport/proxy faults, MCP authorization, public/cross-partition/shared-cache behavior, cache poisoning, notification invalidation, renamed-tool discovery, MCP resource/prompt/task fault families, full MCP conformance certification, production application-memory/RAG injection, hosted File Search/vector-store/URL retrieval manipulation, OpenAI hosted/MCP interception, tool-name/schema poisoning, distributed handoff-fabric injection, process/network/filesystem/cloud environment chaos, target-side delivery attestation, authenticated hostile-writer evidence/report signing, automatic adversarial generation, calibrated semantic graders, and production deployment attestation remain separate implementation layers.
