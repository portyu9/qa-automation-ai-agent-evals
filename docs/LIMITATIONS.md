# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No live provider assurance yet

The current adapter is deterministic/scripted. The package exposes an optional OpenAI dependency group, but a production OpenAI Agents SDK adapter and live-model evaluation path have not yet landed.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. This is deliberate until grader calibration, provenance, failure semantics, and precedence relative to deterministic oracles are implemented.

### No MCP server laboratory yet

The security taxonomy includes MCP authorization/tool-poisoning concepts, but the repository does not yet provide executable MCP fault servers or protocol conformance claims.

### No persistent evidence store

`TrialEvidence` has a hash-chain root but is currently an in-memory model. There is no durable append-only journal, signature, remote attestation, retention policy, or tamper-resistant artifact backend yet.

### No formal non-inferiority test

Paired comparison currently establishes significant directional improvement/regression using an exact McNemar/binomial test. Lack of significant regression is **not** claimed as formal non-inferiority.

### pass@k / pass^k are empirical approximations

The current formulas use the observed per-trial success proportion and an independent-attempt interpretation. Correlated trials, adaptive sampling, or non-stationary agent behavior can violate that approximation.

### Resource-prefix policy is lexical

Resource scope currently uses string-prefix matching over normalized adapter evidence. Provider adapters must normalize resource identities canonically before relying on this control for domains where aliases, path traversal, case folding, URL normalization, or alternate identifiers could bypass a lexical prefix.

### No sandbox isolation claim

The repository currently executes no target-controlled shell or code. If future adapters do so, process/filesystem/network containment must be implemented and validated separately.

## Why these boundaries matter

Agent evaluation is especially vulnerable to false confidence because the output often looks persuasive even when the surrounding state is wrong. The same discipline applies to the framework itself: documentation, badges, scores, and hashes are not substitutes for the actual control they describe.

New capabilities should move out of this document only after implementation, tests, and review make the claim true.
