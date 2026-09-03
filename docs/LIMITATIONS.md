# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is implemented against `openai-agents==0.22.0`, and CI exercises its real SDK tool loop deterministically with `ScriptedModel` without API calls. The repository does **not** yet claim live-model behavioral assurance, production-provider availability, model-specific safety performance, or credentialed end-to-end coverage.

The adapter also keeps terminal state observation outside the SDK result. This is intentional: provider output is execution evidence, not the state oracle.

### Approval decisions are not inferred from approval requests

The OpenAI adapter records SDK `ToolApprovalItem` objects as `APPROVAL_REQUEST` evidence. A request for approval is not an approval grant. Privileged execution therefore requires independently observed `APPROVAL` evidence, bound to the exact tool call unless an evaluation environment explicitly models persistent tool-level authorization.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### No MCP server laboratory yet

The security taxonomy includes MCP authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers or protocol conformance claims.

### Local persistence is not trusted-writer attestation

`LocalEvidenceStore` now provides durable local record materialization with canonical payload bytes, a strict manifest, bounded regular-file reads, symlink rejection, payload hashing, identity derivation checks, semantic evidence-root verification, same-record writer locks, manifest-last commit semantics, and no-clobber publication.

Those controls verify a local record **relative to its manifest and expected evaluation identity**. They do not establish who authored the record. An actor with arbitrary write access to the store root can replace payload and manifest coherently and recompute ordinary hashes.

The repository therefore does **not** claim digital signatures, MAC-based writer authentication, trusted timestamps, remote attestation, WORM/object-lock storage, encryption at rest, key management, cross-host durability, transparency-log anchoring, or enforced retention/deletion policy.

Filesystems that cannot provide the no-clobber hard-link publication primitive fail publication rather than silently falling back to overwrite semantics.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires the recorded trial ID, subject identity, and scenario identity to match the requested replay exactly. It can re-apply deterministic policy/outcome grading to historical observations and reproduce the evidence root for an unchanged evidence model.

Replay does **not** prove current provider availability, reproduce stochastic agent behavior, re-run tools, establish that a historical side effect still exists, or authenticate the original publisher. Those claims require fresh execution or a stronger provenance system.

### Assurance-report validation is not oracle replay or signed attestation

`AssuranceReport` now binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability output, a frozen release policy, release-gate output, and a domain-separated report root. Construction and loading recompute resolved trial verdicts from oracle snapshots, reliability from trial verdicts, critical-violation counts from oracle snapshots, and the release-gate result from the frozen policy.

That makes serialized session conclusions internally auditable; it does **not** make the report an independent source of per-trial truth. The report stores evidence roots rather than full `TrialEvidence`, so it cannot rerun policy/outcome oracles from the hash alone. Re-establishing oracle results requires loading the underlying evidence and using the replay path.

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

Agent evaluation is especially vulnerable to false confidence because output often looks persuasive even when surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, hashes, and SDK traces are not substitutes for the control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
