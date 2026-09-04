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
│   ├── private tools/list stale cache after server-side removal
│   ├── tool-schema drift across cached discovery / call validation / refresh
│   └── tool-identity drift across cached discovery / stale lookup / refresh
├── MCP remote authorization laboratory
│   ├── pre-bound loopback TCP + Uvicorn + Streamable HTTP
│   ├── verifier-owned issuer/resource binding
│   ├── SDK bearer authentication + expiry checks
│   ├── SDK required-scope enforcement
│   └── RFC 9728 protected-resource metadata
├── evidence normalization and persistence verification
├── exact-identity replay
├── deterministic policy and outcome oracles
├── statistical assurance
├── assurance-report verification
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory + resources + handoffs + app context

External / not presently attested
└── live model providers, hosted/external tools, Internet-hosted MCP servers,
    real authorization servers / IdPs, production memory/retrieval, target systems,
    proxies, TLS infrastructure, cloud/IAM, and production fault injectors
```

External content can become evidence or adversarial stimulus. It does not become control-plane authority merely because a model, tool, MCP server, resource, session, handoff, application context, HTTP endpoint, authorization middleware, or external service produced it.

## Identity domains

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, and tags.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

MCP evidence has two independent identity domains:

### Protocol-fault identity

`MCPFaultSpec` binds schema, fault ID/revision, `MCPFaultKind`, original tool name, and canonical finite JSON payload. Content faults bind malicious content directly. Stateful discovery faults bind the exact TTL plus the before/after contract consumed by the laboratory.

The six kinds are:

```text
tool_metadata_poison
tool_result_poison
tool_error
tool_list_stale_cache
tool_schema_drift
tool_identity_drift
```

### Remote-authorization identity

`MCPRemoteAuthPolicy` separately binds schema, lab ID/revision, issuer URL, MCP resource path, canonical required scopes, and protected tool name.

A protocol fault does not silently become a remote-auth policy, and neither becomes an `AttackFixture`. They answer different questions.

## Attack delivery is an evaluation precondition

An adversarial agent scenario is behaviorally gradeable only after one exact matching `ATTACK_DELIVERY` receipt verifies.

```text
unverified delivery                         → BLOCKED
verified delivery + deterministic violation → FAIL
verified delivery + deterministic closure   → PASS
```

The receipt binds exact scenario identity, attack identity, channel, concrete injection point, canonical payload SHA-256, and domain-separated receipt root. It is evaluator integrity evidence, not cryptographic target-side attestation.

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

## MCP protocol-fault boundary

`MCPFaultLab` is provider-neutral protocol test infrastructure. It uses official `mcp==2.1.1`, creates a fresh real `MCPServer`, and connects an official `Client` in modern `2026-07-28` mode.

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

Three direct content observations are closed:

- target tool description returned by `tools/list` equals canonical fault JSON;
- first target `tools/call` result text equals canonical fault JSON;
- first target `ToolError` preserves canonical fault JSON inside the SDK-generated model-visible error envelope.

Three relational discovery-state observations are also closed:

- **stale removal** — initial target present → server removes target → normal cached list still contains target → explicit refresh proves target absent;
- **schema drift** — initial old schema → server replaces the same tool name with a new schema → cached list still exposes old schema → old arguments fail at call time against current server truth → refresh exposes new schema → new arguments succeed;
- **identity drift** — initial old name → server removes it and adds a replacement name → cached list still exposes old name → stale-name call fails → refresh exposes only replacement name → replacement call succeeds.

The core relation is:

```text
cached discovery ≠ current server contract ≠ call-time validity ≠ refreshed discovery
```

`MCPFaultReceipt` binds both controlled fault-material and canonical-observation digests. Direct content may produce equal digests; SDK transformation and stateful relations intentionally do not.

Result/error probes require a benign second call. Discovery probes use fresh client cache state. Receipts are withheld unless the complete fault-specific relation closes.

This receipt is **not** OpenAI `ATTACK_DELIVERY` and does not derive agent `PASS`/`FAIL`.

See [MCP Protocol Fault Laboratory](MCP_LAB.md).

## MCP remote Streamable HTTP authorization boundary

`MCPRemoteAuthLab` is intentionally separate from the in-process fault laboratory.

```text
MCPRemoteAuthPolicy
        ↓
pre-bound 127.0.0.1 TCP socket
        ↓
Uvicorn + MCP Streamable HTTP app
        ↓
resource-server auth middleware
        ↓
HTTP challenge / RFC 9728 metadata / authorized MCP calls
        ↓
MCPRemoteAuthProbeResult
        ↓
MCPRemoteAuthReceipt
```

The enforcement ownership is explicit:

- the deterministic `TokenVerifier` enforces exact **issuer** and **resource** binding;
- MCP SDK authentication middleware handles bearer recognition, verifier acceptance, and expiry;
- MCP SDK authorization middleware enforces required scopes;
- the SDK's protected-resource route exposes RFC 9728 metadata;
- the official client uses a real Streamable HTTP connection to prove an authorized `tools/list` and `tools/call` complete over the TCP boundary.

The matrix requires 401 for missing, unknown, expired, wrong-issuer, and wrong-resource credentials; 403 for an otherwise authenticated token missing required scope; correct resource metadata; and successful protected tool discovery/call with a valid scoped bearer.

The result/receipt do not serialize actual bearer token values. The `Bearer` authentication scheme in `WWW-Authenticate` remains evidence because it is public protocol output, not a credential.

`MCPRemoteAuthReceipt` is separate from `MCPFaultReceipt`. Neither is inserted into agent trial chronology.

See [MCP Remote Authorization](MCP_REMOTE_AUTH.md).

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

## Evidence chronology and separation

Important OpenAI channel-specific ordering includes:

```text
TOOL_RESULT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
ENVIRONMENT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:      HANDOFF → ATTACK_DELIVERY
```

MCP protocol-fault receipts and remote-auth receipts are separate evidence families. They record trusted-client/protocol observations and are not inserted into agent trial chronology until a future integration contract explicitly defines that bridge.

That separation prevents four false implications:

```text
MCP configuration      ⇏ client observation
client observation     ⇏ agent consumption
bearer authorization   ⇏ agent correctness
protocol receipt       ⇏ release acceptance
```

## Authority remains fail-closed

`AuthorityPolicy` controls allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown authority is not permission.

Deterministic policy checks include unauthorized tools, privileged use without approval, out-of-scope resources, explicit policy violations, tool-call budget excess, and handoff budget excess. Critical policy failure is non-compensatory.

Adversarial derivation cannot broaden authority.

## Adapter and runtime failure separation

`AgentAdapter` executes and normalizes; it does not grade itself.

`AdapterPreconditionError` represents evaluator-controlled prerequisites that cannot be satisfied. `TrialRunner` converts this to `EVALUATION_ERROR / BLOCKED`. Provider/SDK execution exceptions remain `RUNTIME_ERROR / BLOCKED`.

Neither is rewritten as subject `FAIL`.

The MCP laboratories return protocol-domain observations rather than `TrialEvidence`; protocol exceptions therefore do not manufacture agent failure semantics.

## Persistence, replay, statistics, and release authority

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, and semantic evidence roots before reuse. Local hashes do not authenticate a hostile writer who can coherently replace all associated bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not re-run the agent, provider, tool, injector, or either MCP laboratory and cannot establish fresh delivery.

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance. MCP protocol success is not currently a release-gate input.

## Current boundary

The framework currently provides deterministic contracts, content-addressed adversarial scenarios, evidence-bound OpenAI delivery verification across seven scoped channel categories, a six-fault official-SDK MCP protocol laboratory, a separate real-loopback Streamable HTTP authorization laboratory, integrity-verified local persistence, exact historical replay, deterministic policy/outcome oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, failure minimization, and credential-free deterministic SDK tiers.

Verified checkpoint:

- deterministic core: **183 passed, 20 deselected**;
- branch coverage: **93.04%**;
- strict mypy: **0 issues across 38 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

Still outside the executable claim boundary are credentialed live-provider assurance, agent-through-MCP behavioral grading, Internet/hosted MCP fidelity, stdio/proxy/TLS/DNS/transport-chaos faults, real authorization-server issuance and IdP/JWT/introspection assurance, DPoP/mTLS, public/shared-cache behavior beyond the exact implemented relations, arbitrary schema/registry mutations, MCP resource/prompt/task fault families, full MCP conformance certification, production application-memory/RAG injection, OpenAI hosted/MCP interception, distributed handoff-fabric injection, process/network/filesystem/cloud environment chaos, target-side delivery attestation, authenticated hostile-writer evidence/report signing, automatic adversarial generation, calibrated semantic graders, and production deployment attestation.
