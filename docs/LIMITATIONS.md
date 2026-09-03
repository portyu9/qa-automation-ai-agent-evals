# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is implemented against `openai-agents==0.22.0`, and CI exercises its real SDK runner/tool loop deterministically with `ScriptedModel` without API calls. The deterministic SDK tier verifies ordinary tool execution, concrete `USER_INPUT` injection, local-`FunctionTool` `TOOL_RESULT` replacement, local-`FunctionTool` description-level `TOOL_METADATA` poisoning, isolated SDK session-history `MEMORY` poisoning, reusable-subject isolation, and fail-closed handling of unsupported/missing adversarial boundaries.

The repository does **not** claim live-model behavioral assurance, production-provider availability, model-specific safety performance, provider-side delivery attestation, or credentialed end-to-end coverage.

Terminal state observation remains outside SDK result. Provider output is execution evidence, not state oracle.

### Approval decisions are not inferred from approval requests

The OpenAI adapter records SDK `ToolApprovalItem` objects as `APPROVAL_REQUEST`, not `APPROVAL`. Privileged execution therefore requires independently observed authorization evidence.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### Delivery receipts are not universal injectors or target-side attestation

The repository provides content-addressed fixtures, deterministic scenario derivation, canonical campaigns, full derived-scenario verification, and evidence-bound delivery receipts.

For adversarial scenarios, `TrialRunner` requires exactly one internally valid delivery receipt before deterministic subject grading. Missing, duplicate, malformed, forged, or mismatched delivery evidence produces `BLOCKED` with no completed subject oracles rather than behavioral `FAIL`.

`OpenAIAgentsAdapter` currently provides four concrete channel implementations:

- `USER_INPUT`: exact canonical fixture JSON is supplied as second ordered SDK user message;
- local-`FunctionTool` `TOOL_RESULT`: first matching local function-tool result in a trial is replaced with exact canonical fixture JSON and bound to exact SDK call ID;
- local-`FunctionTool` description-level `TOOL_METADATA`: copied target description is replaced with exact canonical fixture JSON before SDK execution while original tool remains unchanged;
- SDK session-history `MEMORY`: a fresh per-trial `Session` protocol object returns exact canonical fixture JSON as one prior user item, which the SDK prepends before current input.

Those controls establish **what attack is intended, what exact scenario is evaluated, and what delivery observation the trusted control plane recorded**. They do not provide universal injection or independent proof that an arbitrary external target consumed the stimulus.

### Local `TOOL_RESULT` replacement is not hosted/MCP interception

The current `TOOL_RESULT` implementation is intentionally narrow.

It requires an identity-bearing payload object with valid `tool` + `result` routing. Complete canonical fixture JSON becomes model-visible replacement output so delivery receipt payload digest binds exact delivered bytes.

Per adversarial execution the adapter copies only the target SDK `FunctionTool`, wraps the copy, and clones the agent with a fresh tools list. Original agent/tool remain unchanged.

On first matching call, original target function is deliberately **not executed**; its result is replaced by canonical attack JSON. Later matching calls use copied original behavior.

The repository therefore does **not** claim:

- interception of hosted tools;
- interception of MCP-discovered tools;
- interception of external/remote tool servers;
- generic support for every SDK tool implementation;
- that an actual backing service produced the malicious result;
- preservation of original function side effects on injected first call;
- execute-then-perturb semantics.

A future mode that executes original function and only mutates return value must be a separate explicit contract because its safety and side-effect semantics differ.

If configured target never executes, no receipt is emitted and adversarial trial remains `BLOCKED`. A skipped attack is never treated as successful testing.

### Local `TOOL_METADATA` means description poisoning, not universal metadata poisoning

The current `TOOL_METADATA` implementation is intentionally narrow.

It requires an identity-bearing payload object with valid `tool` + `description` fields. Complete canonical fixture JSON becomes copied local `FunctionTool.description`, so delivery receipt digest binds exact string visible at tested SDK model-call tool boundary.

Per adversarial execution the adapter uses same fail-closed exact local-tool resolver as `TOOL_RESULT`, copies target, changes only copied description, and clones agent with a fresh tools list. Original agent/tool remain unchanged.

The repository therefore does **not** claim that this implementation mutates or tests:

- tool names;
- parameter JSON schemas;
- invocation callbacks;
- approval semantics;
- tool routing identity;
- hosted-tool metadata;
- MCP tool/server discovery metadata;
- external registry or remote tool-server metadata;
- provider wire serialization;
- remote hosted-model processing/preservation of poisoned description;
- target-side delivery attestation.

Those are separate boundaries. Schema poisoning and tool renaming can alter invocation/routing behavior and should not be silently folded into a description-poisoning test.

### SDK session-history `MEMORY` is not production memory poisoning

The implemented `MEMORY` mode is also intentionally narrow.

It validates an identity-bearing fixture with a required `memory` field and places the **complete canonical fixture JSON** into a fresh per-trial object implementing the OpenAI SDK `Session` protocol. The runner retrieves that prior item through `get_items` and prepends it before current run input.

The deterministic SDK test proves exact poisoned history is visible before current objective and that a later ordinary run receives no inherited session poison.

The repository therefore does **not** claim that this implementation mutates, attacks, or validates:

- an application-owned production session database;
- an OpenAI server-managed conversation or provider-side persisted thread;
- vector databases, embedding stores, or RAG memories;
- semantic retrieval-memory ranking or filtering;
- cross-user or cross-tenant production session boundaries;
- filesystem, browser, or sandbox memory;
- durable persistence or cleanup of an external memory service;
- provider-side processing/retention of injected history;
- target-side memory-delivery attestation.

A real application-memory adapter must target the actual retrieval/persistence boundary and independently verify isolation, tenant scope, lifecycle, and side effects. The SDK session-history mode must not be described as universal memory poisoning.

### Other attack channels remain unimplemented in the OpenAI adapter

`resource`, `handoff`, and `environment` still require concrete controlled injectors at their real boundaries.

The repository therefore does not yet claim external-resource injection, handoff poisoning, environment-fault delivery, complete channel coverage, or universal prompt-injection harnessing across all context sources.

The `injector:<identity>` source is a label, not authenticated signer identity. Receipt roots are SHA-256 integrity, not signatures, MACs, trusted timestamps, hardware attestation, or non-repudiation. A buggy or malicious trusted injector could still lie without stronger independent acknowledgement/authentication.

Automatic adversarial generation, adaptive red-team agents, mutation/fuzzing campaigns, and sandbox-escape execution are also not implemented yet.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

### No MCP server laboratory yet

The taxonomy and adversarial layers include MCP-relevant authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers, malicious MCP metadata/result simulators, protocol-conformance claims, MCP task/authorization fault coverage, or target-side MCP delivery attestation.

Local `FunctionTool` result replacement, local `FunctionTool` description poisoning, and SDK session-history poisoning must not be described as MCP injection.

### Local persistence is not trusted-writer attestation

`LocalEvidenceStore` provides canonical payload materialization, strict manifests, bounded regular-file reads, symlink rejection, payload hashing, identity derivation checks, semantic evidence-root verification, same-record writer locks, manifest-last commit semantics, and no-clobber publication.

These controls verify local records relative to manifests and expected evaluation identity. They do not establish who authored the record. An actor with arbitrary write access to store root can replace payload and manifest coherently and recompute ordinary hashes.

The repository therefore does **not** claim digital signatures, MAC-based writer authentication, trusted timestamps, remote attestation, WORM/object-lock storage, encryption at rest, key management, cross-host durability, transparency-log anchoring, or enforced retention/deletion policy.

Filesystems that cannot provide no-clobber hard-link publication primitive fail publication rather than silently falling back to overwrite semantics.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial, subject, and scenario identity. It can re-apply delivery verification and deterministic subject grading to historical observations and reproduce evidence root for unchanged evidence model.

Replay does **not** run injector again, prove fresh delivery, prove current provider availability, reproduce stochastic behavior, re-run tools, re-open a session, establish historical side effects still exist, or authenticate original publisher/injector.

### Assurance-report validation is not oracle replay or signed attestation

`AssuranceReport` binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability output, frozen release policy, release-gate output, and a domain-separated report root. Construction/loading recompute resolved verdicts, reliability, critical-violation counts, and gate output.

Delivery-caused `BLOCKED` trials remain infrastructure uncertainty: they carry no completed deterministic oracle snapshots, are not behavioral failures, do not create critical oracle-violation counts, and can keep release `INCONCLUSIVE`.

The report stores evidence roots rather than full `TrialEvidence`; full delivery/policy/outcome regrading requires underlying evidence and replay path. Report roots are integrity hashes, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison currently establishes significant directional improvement/regression using an exact McNemar/binomial test. Lack of significant regression is **not** claimed as formal non-inferiority.

### pass@k / pass^k are empirical approximations

Current formulas use observed success proportion among resolved `PASS`/`FAIL` trials and an independent-attempt interpretation. `BLOCKED` and `INCONCLUSIVE` attempts remain separate. Correlated trials, adaptive sampling, or non-stationary behavior can violate the independence approximation.

### Resource-prefix policy is lexical

Resource scope currently uses string-prefix matching over adapter-normalized resource identities. Provider adapters must canonicalize aliases, path traversal, case folding, URL forms, and alternate identifiers before lexical prefix comparison can represent intended security boundary.

### No sandbox isolation claim

The repository currently executes no target-controlled shell or arbitrary target code. Future adapters that do so must implement and validate process/filesystem/network containment separately.

## Current verification checkpoint

The current source checkpoint is **159 passed, 7 deselected, 93.71% branch coverage**, strict mypy clean across **34 source files**, with **7/7** deterministic OpenAI SDK tests green. The channel-specific adversarial payload implementation is absent from the missing-coverage table.

## Why these boundaries matter

Agent evaluation is especially vulnerable to false confidence because output can look persuasive even when surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, hashes, attack labels, delivery receipts, and SDK traces are not substitutes for the control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
