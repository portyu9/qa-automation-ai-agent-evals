# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is implemented against `openai-agents==0.22.0`, and CI exercises its real SDK runner/tool loop deterministically with `ScriptedModel` without API calls. The deterministic SDK tier verifies ordinary tool execution, concrete `USER_INPUT` injection, local-`FunctionTool` `TOOL_RESULT` replacement, isolation of the reusable original tool, and fail-closed handling of unsupported/missing adversarial boundaries.

The repository does **not** claim live-model behavioral assurance, production-provider availability, model-specific safety performance, provider-side delivery attestation, or credentialed end-to-end coverage.

Terminal state observation remains outside the SDK result. Provider output is execution evidence, not the state oracle.

### Approval decisions are not inferred from approval requests

The OpenAI adapter records SDK `ToolApprovalItem` objects as `APPROVAL_REQUEST`, not `APPROVAL`. Privileged execution therefore requires independently observed authorization evidence.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### Delivery receipts are not universal injectors or target-side attestation

The repository provides content-addressed fixtures, deterministic scenario derivation, canonical campaigns, full derived-scenario verification, and evidence-bound delivery receipts.

For adversarial scenarios, `TrialRunner` requires exactly one internally valid delivery receipt before deterministic subject grading. Missing, duplicate, malformed, forged, or mismatched delivery evidence produces `BLOCKED` with no completed subject oracles rather than behavioral `FAIL`.

`OpenAIAgentsAdapter` currently provides two concrete channel implementations:

- `USER_INPUT`: exact canonical fixture JSON is supplied as the second ordered SDK user message;
- local-`FunctionTool` `TOOL_RESULT`: the first matching local function-tool result in a trial is replaced with exact canonical fixture JSON and bound to the exact SDK call ID.

Those controls establish **what attack is intended, what exact scenario is evaluated, and what delivery observation the trusted control plane recorded**. They do not provide universal injection or independent proof that an arbitrary external target consumed the stimulus.

### Local `TOOL_RESULT` replacement is not hosted/MCP interception

The current `TOOL_RESULT` implementation is intentionally narrow.

It requires an identity-bearing payload object with a valid `tool` + `result` routing contract. The complete canonical fixture JSON becomes the model-visible replacement output so the delivery receipt's payload digest binds the exact delivered bytes.

Per adversarial execution the adapter copies only the target SDK `FunctionTool`, wraps the copy, and clones the agent with a fresh tools list. The original agent/tool remain unchanged.

On the first matching call, the original target function is deliberately **not executed**; its result is replaced by the canonical attack payload. Later matching calls in the same trial use the copied original behavior.

Therefore the repository does **not** claim:

- interception of hosted tools;
- interception of MCP-discovered tools;
- interception of external/remote tool servers;
- generic support for every SDK tool implementation;
- that an actual backing service produced the malicious result;
- preservation of original function side effects on the injected first call;
- execute-then-perturb semantics.

A future mode that executes the original function and only mutates its return value must be a separate explicit contract because its safety and side-effect semantics differ.

If the configured target never executes, no receipt is emitted and the adversarial trial remains `BLOCKED`. A skipped attack is never treated as successful testing.

### Other attack channels remain unimplemented in the OpenAI adapter

`tool_metadata`, `memory`, `resource`, `handoff`, and `environment` still require concrete controlled injectors at their real boundaries.

The repository therefore does not yet claim production memory poisoning, external-resource injection, handoff poisoning, environment-fault delivery, complete channel coverage, or universal prompt-injection harnessing across all context sources.

The `injector:<identity>` source is a label, not authenticated signer identity. Receipt roots are SHA-256 integrity, not signatures, MACs, trusted timestamps, hardware attestation, or non-repudiation. A buggy or malicious trusted injector could still lie without stronger independent acknowledgement/authentication.

Automatic adversarial generation, adaptive red-team agents, mutation/fuzzing campaigns, and sandbox-escape execution are also not implemented yet.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

### No MCP server laboratory yet

The taxonomy and adversarial layers include MCP-relevant authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers, malicious MCP metadata/result simulators, protocol conformance claims, MCP task/authorization fault coverage, or target-side MCP delivery attestation.

The local `FunctionTool` result injector must not be described as MCP result injection.

### Local persistence is not trusted-writer attestation

`LocalEvidenceStore` provides canonical payload materialization, strict manifests, bounded regular-file reads, symlink rejection, payload hashing, identity derivation checks, semantic evidence-root verification, same-record writer locks, manifest-last commit semantics, and no-clobber publication.

These controls verify local records relative to their manifests and expected evaluation identity. They do not establish who authored the record. An actor with arbitrary write access to the store root can replace payload and manifest coherently and recompute ordinary hashes.

The repository therefore does **not** claim digital signatures, MAC-based writer authentication, trusted timestamps, remote attestation, WORM/object-lock storage, encryption at rest, key management, cross-host durability, transparency-log anchoring, or enforced retention/deletion policy.

Filesystems that cannot provide the no-clobber hard-link publication primitive fail publication rather than silently falling back to overwrite semantics.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial, subject, and scenario identity. It can re-apply delivery verification and deterministic subject grading to historical observations and reproduce the evidence root for an unchanged evidence model.

Replay does **not** run the injector again, prove fresh delivery, prove current provider availability, reproduce stochastic agent behavior, re-run tools, establish that historical side effects still exist, or authenticate the original publisher/injector.

### Assurance-report validation is not oracle replay or signed attestation

`AssuranceReport` binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability output, frozen release policy, release-gate output, and a domain-separated report root. Construction/loading recompute resolved verdicts, reliability, critical-violation counts, and gate output.

Delivery-caused `BLOCKED` trials remain infrastructure uncertainty: they carry no completed deterministic oracle snapshots, are not behavioral failures, do not create critical oracle-violation counts, and can keep release `INCONCLUSIVE`.

The report stores evidence roots rather than full `TrialEvidence`; full delivery/policy/outcome regrading requires the underlying evidence and replay path. Report roots are integrity hashes, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison currently establishes significant directional improvement/regression using an exact McNemar/binomial test. Lack of significant regression is **not** claimed as formal non-inferiority.

### pass@k / pass^k are empirical approximations

The current formulas use the observed success proportion among resolved `PASS`/`FAIL` trials and an independent-attempt interpretation. `BLOCKED` and `INCONCLUSIVE` attempts remain separate. Correlated trials, adaptive sampling, or non-stationary behavior can violate the independence approximation.

### Resource-prefix policy is lexical

Resource scope currently uses string-prefix matching over adapter-normalized resource identities. Provider adapters must canonicalize aliases, path traversal, case folding, URL forms, and alternate identifiers before lexical prefix comparison can represent the intended security boundary.

### No sandbox isolation claim

The repository currently executes no target-controlled shell or arbitrary target code. Future adapters that do so must implement and validate process/filesystem/network containment separately.

## Why these boundaries matter

Agent evaluation is especially vulnerable to false confidence because output can look persuasive even when surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, hashes, attack labels, delivery receipts, and SDK traces are not substitutes for the control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
