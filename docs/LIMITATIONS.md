# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is implemented against `openai-agents==0.22.0`, and CI exercises its real SDK runner/tool loop deterministically with `ScriptedModel` without API calls. The same deterministic SDK tier also verifies the concrete `USER_INPUT` adversarial injector and fail-closed handling for an unsupported attack channel.

The repository does **not** yet claim live-model behavioral assurance, production-provider availability, model-specific safety performance, provider-side delivery attestation, or credentialed end-to-end coverage.

The adapter also keeps terminal state observation outside the SDK result. This is intentional: provider output is execution evidence, not the state oracle.

### Approval decisions are not inferred from approval requests

The OpenAI adapter records SDK `ToolApprovalItem` objects as `APPROVAL_REQUEST` evidence. A request for approval is not an approval grant. Privileged execution therefore requires independently observed `APPROVAL` evidence, bound to the exact tool call unless an evaluation environment explicitly models persistent tool-level authorization.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### Delivery receipts are not universal injectors or target-side attestation

The repository provides content-addressed `AttackFixture` objects, deterministic attack-to-scenario derivation, a provider-neutral reserved attack envelope, canonical `AdversarialCampaign` objects, full derived-scenario verification when an expected base is supplied, fail-closed detection of campaign base drift, and evidence-bound `AttackDeliveryReceipt` verification.

For an adversarial scenario, `TrialRunner` requires exactly one internally valid delivery receipt before deterministic policy/outcome grading. The receipt binds the exact derived scenario, exact attack, declared channel, environment-defined injection point, and canonical attack-payload digest. Missing, duplicate, malformed, forged, or mismatched delivery evidence produces `BLOCKED` with no completed subject oracles rather than behavioral `FAIL`.

`OpenAIAgentsAdapter` now provides one real channel implementation: `USER_INPUT`. It supplies the ordinary objective as the first SDK user message and exact canonical `AttackFixture.payload_json` as the second, emits the matching receipt for `openai-agents:Runner.run.input[1]`, and is tested through the SDK's deterministic `ScriptedModel`. Unsupported OpenAI attack channels raise a structured adapter precondition failure before any model call occurs.

Those controls establish **what attack is intended, what exact scenario is being evaluated, and what delivery observation the trusted evaluation control plane recorded**. They do not provide a universal injector for every `AttackChannel`, and they do not independently prove that an arbitrary external target consumed the stimulus.

A fixture labeled `tool_result`, `memory`, `tool_metadata`, `resource`, `handoff`, or `environment` still requires a concrete controlled injector at that real boundary. The repository therefore does not yet claim production memory poisoning, external target fault injection, complete channel coverage, or universal prompt-injection harnessing across all context sources.

The `injector:<identity>` evidence source is a label, not authenticated signer identity. The receipt root is SHA-256 integrity, not a signature, MAC, trusted timestamp, hardware attestation, or non-repudiation mechanism. A buggy or malicious trusted injector can still lie about delivery unless a stronger independent acknowledgement/authentication boundary is added.

The repository also does not yet provide automatic adversarial generation, adaptive red-team agents, mutation/fuzzing campaigns, or sandbox-escape execution.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

### No MCP server laboratory yet

The security taxonomy and adversarial fixture/delivery layers include MCP-relevant authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers, malicious MCP metadata/result simulators, protocol conformance claims, MCP task/authorization fault coverage, or target-side MCP delivery attestation.

### Local persistence is not trusted-writer attestation

`LocalEvidenceStore` provides durable local record materialization with canonical payload bytes, a strict manifest, bounded regular-file reads, symlink rejection, payload hashing, identity derivation checks, semantic evidence-root verification, same-record writer locks, manifest-last commit semantics, and no-clobber publication.

Those controls verify a local record **relative to its manifest and expected evaluation identity**. They do not establish who authored the record. An actor with arbitrary write access to the store root can replace payload and manifest coherently and recompute ordinary hashes.

The repository therefore does **not** claim digital signatures, MAC-based writer authentication, trusted timestamps, remote attestation, WORM/object-lock storage, encryption at rest, key management, cross-host durability, transparency-log anchoring, or enforced retention/deletion policy.

Filesystems that cannot provide the no-clobber hard-link publication primitive fail publication rather than silently falling back to overwrite semantics.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires the recorded trial ID, subject identity, and scenario identity to match the requested replay exactly. It can re-apply deterministic delivery verification and policy/outcome grading to historical observations and reproduce the evidence root for an unchanged evidence model.

For adversarial trials, a recorded `ATTACK_DELIVERY` receipt is replayed and revalidated as historical evidence. Replay does **not** run the injector again, prove fresh attack delivery, prove current provider availability, reproduce stochastic agent behavior, re-run tools, establish that a historical side effect still exists, or authenticate the original publisher/injector. Those claims require fresh execution or a stronger provenance/attestation system.

### Assurance-report validation is not oracle replay or signed attestation

`AssuranceReport` binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability output, a frozen release policy, release-gate output, and a domain-separated report root. Construction and loading recompute resolved trial verdicts from oracle snapshots, reliability from trial verdicts, critical-violation counts from oracle snapshots, and the release-gate result from the frozen policy.

Delivery-caused `BLOCKED` trials are intentionally preserved as infrastructure uncertainty: they carry no completed deterministic oracle snapshots, are not counted as behavioral failures, do not create critical oracle-violation counts, and can make the release decision `INCONCLUSIVE` when evidence requirements are unmet.

That makes serialized session conclusions internally auditable; it does **not** make the report an independent source of per-trial truth. The report stores evidence roots rather than full `TrialEvidence`, so it cannot rerun delivery verification or policy/outcome oracles from the hash alone. Re-establishing those checks requires loading the underlying evidence and using the replay path.

The report root is also an ordinary integrity hash, not writer authentication. An actor who can coherently rewrite an unsigned report can recompute the report root and all derived fields. The repository therefore does not claim signed reports, authenticated release approvals, trusted timestamps, transparency-log anchoring, or non-repudiation.

### No formal non-inferiority test

Paired comparison currently establishes significant directional improvement/regression using an exact McNemar/binomial test. Lack of significant regression is **not** claimed as formal non-inferiority.

### pass@k / pass^k are empirical approximations

The current formulas use the observed success proportion among resolved `PASS`/`FAIL` trials and an independent-attempt interpretation. `BLOCKED` and `INCONCLUSIVE` attempts are retained separately and are never silently counted as behavioral failures. Correlated trials, adaptive sampling, or non-stationary agent behavior can still violate the independence approximation.

### Resource-prefix policy is lexical

Resource scope currently uses string-prefix matching over adapter-normalized resource identities. A configured scoped policy fails closed when a tool request lacks resource identity, but provider adapters must still canonicalize aliases, path traversal, case folding, URL forms, and alternate identifiers before lexical prefix comparison can represent the intended security boundary.

### No sandbox isolation claim

The repository currently executes no target-controlled shell or arbitrary target code. If future adapters do so, process/filesystem/network containment must be implemented and validated separately.

## Why these boundaries matter

Agent evaluation is especially vulnerable to false confidence because output often looks persuasive even when surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, hashes, attack labels, delivery receipts, and SDK traces are not substitutes for the control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
