# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is implemented against `openai-agents==0.22.0`, and CI exercises its real SDK runner/tool/handoff/input loop deterministically with `ScriptedModel` without provider API calls.

The deterministic SDK tier verifies ordinary tool execution plus concrete `USER_INPUT`, local-`FunctionTool` `TOOL_RESULT`, local description-level `TOOL_METADATA`, isolated session-history `MEMORY`, structured inline-file `RESOURCE`, and first-native-handoff-context `HANDOFF` delivery.

The repository does **not** claim live-model behavioral assurance, production-provider availability, model-specific safety performance, provider-side delivery attestation, or credentialed end-to-end coverage. Terminal state observation remains outside SDK result.

### Approval decisions are not inferred from approval requests

The OpenAI adapter records SDK `ToolApprovalItem` objects as `APPROVAL_REQUEST`, not `APPROVAL`. Privileged execution therefore requires independently observed authorization evidence.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### Delivery receipts are not universal injectors or target-side attestation

`TrialRunner` requires exactly one internally valid delivery receipt before deterministic adversarial subject grading. Missing, duplicate, malformed, forged, or mismatched delivery evidence produces `BLOCKED` with no completed subject oracles rather than behavioral `FAIL`.

`OpenAIAgentsAdapter` currently provides six concrete channel implementations:

- `USER_INPUT`: exact canonical fixture JSON as second ordered SDK user message;
- local `TOOL_RESULT`: first matching local function-tool result replaced with exact canonical fixture JSON and bound to exact SDK call ID;
- local description-level `TOOL_METADATA`: copied target description replaced with exact canonical fixture JSON while original tool remains unchanged;
- SDK session-history `MEMORY`: fresh per-trial `Session` returns exact canonical fixture JSON as one prior user item;
- structured inline-file `RESOURCE`: exact canonical fixture JSON becomes `file_data` of one SDK `input_file` item;
- native SDK `HANDOFF`: fresh per-trial run-level handoff filter appends exact canonical fixture JSON to first actual handoff context while preserving destination.

These controls establish what attack is intended, what exact scenario is evaluated, and what delivery observation the trusted control plane recorded. They do not provide universal injection or independent proof that an arbitrary external target consumed the stimulus.

### Local `TOOL_RESULT` replacement is not hosted/MCP interception

The current `TOOL_RESULT` implementation requires identity-bearing `tool` + `result` routing. Complete canonical fixture JSON becomes model-visible replacement output.

Per trial the target is copied and agent cloned. On first matching call the original target function is deliberately **not executed**; later matching calls use copied original behavior.

The repository does **not** claim hosted/MCP/external-tool interception, generic support for every SDK tool implementation, that a backing service produced the malicious result, preservation of original first-call side effects, or execute-then-perturb semantics.

If the configured target never executes, no receipt is emitted and the trial remains `BLOCKED`.

### Local `TOOL_METADATA` means description poisoning, not universal metadata poisoning

The current `TOOL_METADATA` implementation requires `tool` + `description`. Complete canonical fixture JSON becomes copied local `FunctionTool.description`.

It does **not** mutate or test tool names, parameter JSON schemas, invocation callbacks, approval semantics, routing identity, hosted-tool metadata, MCP discovery metadata, external registries, provider wire serialization, or remote-model processing attestation.

### SDK session-history `MEMORY` is not production memory poisoning

The implemented `MEMORY` mode places complete canonical fixture JSON into a fresh per-trial object implementing the OpenAI SDK `Session` protocol. The runner retrieves that prior item through `get_items` and prepends it before current input.

The deterministic SDK test proves exact poisoned history is visible before current objective and a later ordinary run receives no inherited session poison.

This does **not** claim application-owned production session mutation, provider-managed conversation poisoning, vector databases/RAG memory, semantic retrieval manipulation, cross-user/tenant production session boundaries, filesystem/browser/sandbox memory, durable external persistence, provider-side retention, or target-side memory-delivery attestation.

### Structured inline-file `RESOURCE` is not universal resource or retrieval poisoning

The implemented `RESOURCE` mode is intentionally narrow.

It requires an identity-bearing fixture with a `resource` field. Complete canonical `AttackFixture.payload_json` becomes exact `file_data` of one structured SDK `input_file`; the evaluator supplies a fixed filename `agent-evals-resource.json`.

The deterministic SDK test proves `ScriptedModel` observes the exact structured file item and canonical file content. A later ordinary run receives only its current objective, proving no reusable agent/adapter contamination.

The repository therefore does **not** claim this mode mutates, attacks, validates, or attests:

- OpenAI hosted File Search;
- vector stores, embeddings, RAG retrieval, ranking, chunking, filtering, or citations;
- provider-uploaded `file_id` resources;
- remote `file_url` fetching or URL content;
- browser pages, databases, object stores, knowledge bases, or production document repositories;
- MCP resource servers or hosted-tool retrieval;
- external filesystem/resource lifecycle;
- provider-side file parsing, transformation, or retention;
- target-side proof that a remote hosted model consumed the injected file bytes.

A real production-resource adapter must target the actual retrieval/storage/enforcement boundary and independently verify isolation, identity, lifecycle, and side effects.

The adapter's `resource_resolver(tool_name, arguments)` callback is unrelated to adversarial `RESOURCE`: it normalizes tool-call resource identities for lexical policy checks.

### Native SDK `HANDOFF` is context poisoning, not rerouting or distributed-fabric interception

The implemented `HANDOFF` mode validates a required `handoff` field and installs a fresh per-trial `RunConfig.handoff_input_filter`. On the first actual SDK handoff, it appends complete canonical fixture JSON to cloned handoff history and returns that modified transfer to the same SDK-selected destination.

The deterministic SDK test drives a real two-agent handoff, proves receiving context, checks `HANDOFF → ATTACK_DELIVERY`, and proves a later ordinary handoff receives no inherited poison.

It does **not** choose/change destination, rewrite handoff tool identity/routing metadata, modify receiving-agent instructions/tools/policy, poison every transfer in a chain, intercept remote/distributed runtimes or message buses, or attest remote-provider consumption.

If no handoff occurs—or the SDK does not invoke the configured run-level filter—no delivery receipt is emitted and the adversarial trial remains `BLOCKED`.

### Generic `ENVIRONMENT` injection remains unimplemented

`ENVIRONMENT` is the only generic `AttackChannel` still unsupported by `OpenAIAgentsAdapter`.

The repository therefore does not yet claim process-environment mutation, network fault injection, filesystem/sandbox fault delivery, service dependency failure injection, provider configuration perturbation, clock/time faults, secret-store manipulation, or production infrastructure chaos through this adapter.

The `injector:<identity>` source is a label, not authenticated signer identity. Receipt roots are SHA-256 integrity, not signatures, MACs, trusted timestamps, hardware attestation, or non-repudiation.

Automatic adversarial generation, adaptive red-team agents, mutation/fuzzing campaigns, and sandbox-escape execution are also not implemented yet.

### No MCP server laboratory yet

The taxonomy includes MCP-relevant authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers, malicious MCP metadata/result/resource simulators, protocol-conformance claims, task/authorization fault coverage, or target-side MCP delivery attestation.

Local tool result/description poisoning, SDK session-history poisoning, inline-file resource poisoning, and native SDK handoff-context poisoning must not be described as MCP injection.

### Local persistence is not trusted-writer attestation

`LocalEvidenceStore` provides canonical payload materialization, strict manifests, bounded regular-file reads, symlink rejection, payload hashing, identity derivation checks, semantic evidence-root verification, same-record writer locks, manifest-last commit semantics, and no-clobber publication.

These controls verify local records relative to manifests and expected evaluation identity. They do not establish who authored the record. An actor with arbitrary write access to store root can replace payload and manifest coherently and recompute ordinary hashes.

The repository therefore does **not** claim digital signatures, MAC-based writer authentication, trusted timestamps, remote attestation, WORM/object-lock storage, encryption at rest, key management, cross-host durability, transparency-log anchoring, or enforced retention/deletion policy.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial, subject, and scenario identity and can re-apply delivery verification/deterministic grading to historical observations.

Replay does **not** run the injector again, prove fresh delivery/provider availability, reproduce stochastic behavior, re-run tools, re-open a session, re-send the inline resource, re-run a handoff, establish historical side effects, or authenticate original publisher/injector.

### Assurance-report validation is not oracle replay or signed attestation

`AssuranceReport` binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability output, frozen release policy, gate output, and report root. Construction/loading recompute resolved verdicts, reliability, critical-violation counts, and gate output.

Delivery-caused `BLOCKED` trials remain infrastructure uncertainty. Report roots are integrity hashes, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison establishes significant directional improvement/regression using an exact McNemar/binomial test. Lack of significant regression is **not** claimed as formal non-inferiority.

### `pass@k` / `pass^k` are empirical approximations

Current formulas use observed success proportion among resolved `PASS`/`FAIL` trials and an independent-attempt interpretation. `BLOCKED` and `INCONCLUSIVE` remain separate. Correlated trials, adaptive sampling, or non-stationary behavior can violate the independence approximation.

### Resource-prefix policy is lexical

Resource scope uses string-prefix matching over adapter-normalized tool resource identities. Provider adapters must canonicalize aliases, traversal, case folding, URL forms, and alternate identifiers before lexical comparison can represent the intended security boundary.

This policy check is separate from inline-file adversarial `RESOURCE` delivery.

### No sandbox isolation claim

The repository currently executes no target-controlled shell or arbitrary target code. Future environment adapters that do so must implement and validate process/filesystem/network containment separately.

## Current verification checkpoint

The current source checkpoint is **167 passed, 9 deselected, 93.81% branch coverage**, strict mypy clean across **34 source files**, with **9/9** deterministic OpenAI SDK tests green. The channel-specific adversarial payload implementation is absent from the missing-coverage table.

## Why these boundaries matter

Agent evaluation is vulnerable to false confidence because output can look persuasive even when surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, hashes, attack labels, delivery receipts, and SDK traces are not substitutes for the control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
