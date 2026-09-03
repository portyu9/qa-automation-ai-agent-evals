# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes provider/model configuration, application revision, instructions, tool schemas, authority policy, memory policy, adapter identity, and adapter version.

The architecture starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial derivation
├── controlled attack injectors
│   ├── OpenAI USER_INPUT
│   ├── OpenAI local FunctionTool TOOL_RESULT
│   ├── OpenAI local FunctionTool TOOL_METADATA description
│   ├── OpenAI per-trial Session-history MEMORY
│   ├── OpenAI structured inline-file RESOURCE
│   ├── OpenAI first-native-handoff context
│   └── OpenAI targeted runtime-context ENVIRONMENT
├── attack-delivery verifier
├── evidence normalization and persistence verification
├── exact-identity replay
├── deterministic policy and outcome oracles
├── statistical assurance
├── assurance-report verification
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory + resources + handoffs + app context

External systems
└── providers, hosted/external tools, MCP servers, production memory/retrieval,
    target systems, infrastructure, fault injectors
```

External content can become evidence or adversarial stimulus. It does not become control-plane authority merely because a model, tool, resource, session, handoff, application context, or external service produced it.

## Identity contracts

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, and tags.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

## Attack delivery is an evaluation precondition

An adversarial scenario is behaviorally gradeable only after one exact matching `ATTACK_DELIVERY` receipt verifies.

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

## Local-tool isolation

For result, metadata, and environment attacks, the adapter resolves one exact local SDK `FunctionTool`, copies it, and clones the agent with a fresh tools list. The reusable original tool and agent remain unchanged.

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

Important channel-specific ordering includes:

```text
TOOL_RESULT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
ENVIRONMENT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:      HANDOFF → ATTACK_DELIVERY
```

User-input, metadata, memory, and resource structures can be prepared before subject execution; independent SDK tests prove the prepared content reaches the tested model/tool boundary.

## Authority remains fail-closed

`AuthorityPolicy` controls allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown authority is not permission.

Deterministic policy checks include unauthorized tools, privileged use without approval, out-of-scope resources, explicit policy violations, tool-call budget excess, and handoff budget excess. Critical policy failure is non-compensatory.

Adversarial derivation cannot broaden authority.

## Adapter and runtime failure separation

`AgentAdapter` executes and normalizes; it does not grade itself.

`AdapterPreconditionError` represents an evaluator-controlled prerequisite that cannot be satisfied, such as malformed channel payloads, unavailable targets, unbindable call identity, or unsupported runtime-context type. `TrialRunner` converts this to `EVALUATION_ERROR / BLOCKED`.

Provider/SDK execution exceptions remain `RUNTIME_ERROR / BLOCKED`.

Neither is rewritten as subject `FAIL`.

## Persistence and replay

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, and semantic evidence roots before reuse. Local integrity hashes do not authenticate a hostile writer who can coherently replace all associated bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not re-run the agent, provider, tool, session, resource, handoff, or environment injector and cannot establish fresh delivery.

## Statistical and release authority

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance.

## Current boundary

The framework currently provides deterministic contracts, content-addressed adversarial scenarios, evidence-bound delivery verification, all seven generic OpenAI adapter channel categories at scoped boundaries, integrity-verified local persistence, exact historical replay, deterministic policy/outcome oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, failure minimization, and a credential-free deterministic OpenAI SDK tier.

Verified checkpoint:

- **177 passed, 11 deselected**;
- **93.78% branch coverage**;
- strict mypy: **0 issues across 34 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

Credentialed live-provider assurance, production application-memory/RAG injection, hosted File Search/vector-store/URL retrieval manipulation, tool-name/schema poisoning, hosted/MCP interception, distributed handoff-fabric injection, process/network/filesystem/cloud environment chaos, target-side delivery attestation, authenticated hostile-writer evidence/report signing, automatic adversarial generation, MCP fault servers, calibrated semantic graders, and production deployment attestation remain separate implementation layers.
