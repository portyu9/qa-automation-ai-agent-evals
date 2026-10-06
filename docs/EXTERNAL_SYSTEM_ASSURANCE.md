# External-System Assurance: MCP, OAuth, HITL, Side Effects, Retrieval, Memory and Chaos

This layer expands the framework beyond its original stdio/loopback/run-local boundaries while preserving the same authority rule: **protocol, control-plane, authentication, target acknowledgement, retrieval, memory and chaos evidence are evaluation preconditions or diagnostics unless a separate scenario-owned deterministic oracle consumes them. They never become behavioral PASS by themselves.**

## Hosted and remote MCP

`MCPHostedEndpointSpec` defines one HTTPS Streamable-HTTP endpoint with explicit timeout, latency, response-size and stream-frame ceilings. `probe_hosted_mcp_endpoint()` can issue a bounded MCP initialize request to an operator-selected Internet endpoint. The probe classifies TLS, DNS, proxy, gateway, latency, disconnect, stream interruption, rate limiting, oversized response, timeout and protocol-shape failures rather than flattening them into subject failure.

`MCPRemoteAssuranceReceipt` binds a campaign to one endpoint identity and a declared set of required transport conditions. A healthy observation must bind the expected server identity and remain inside transport ceilings. Fault observations require bounded error codes. A receipt hash is an integrity commitment, not server authentication or remote attestation.

The ordinary PR suite remains network-independent. Operators can invoke the network probe against controlled hosted endpoints; external availability is not permitted to make structural PR CI flaky.

## Advanced MCP protocol surfaces

`MCPCapabilitySnapshot` inventories resources, prompts, roots, subscriptions, elicitation, sampling, Tasks and `tools/list_changed` capability. `MCPToolsListChangedReceipt` requires an actual before/after discovery delta and a notification sequence.

`MCPConcurrencyReceipt` recomputes peak parallelism from bounded logical intervals and rejects duplicate request IDs. `MCPMultiServerReceipt` reports cross-server tool-name collisions instead of silently aliasing them. `MCPHostileServerReceipt` keeps oversized responses, hangs, protocol trickery and resource pressure inside declared byte/time/message ceilings.

These contracts do not infer that an advertised capability is correct merely because a server declares it. Runtime integrations must bind observations at the protocol boundary they claim.

## OAuth, JWT/JWKS and authorization drift

`OAuthKeySetSnapshot` binds observed issuer/JWKS key sets by logical epoch. `OAuthSessionEvent` records only token digests plus externally verified JWT/signature facts; raw bearer material is not persisted. `OAuthAdvancedReceipt` can require key rotation, refresh, revocation rejection, replay rejection and sender constraining by DPoP or mTLS, including third-party issuers declared by policy.

`OAuthAuthorizationDriftReceipt` requires an observed scope contraction during an active session plus a post-contraction denial. It does not treat a successful authorization flow as behavioral correctness.

## Authenticated human approval and durable resume

The existing scenario-owned `ApprovalIntentSpec` remains the authority for what decision is expected at one exact invocation. `HumanApprovalEvidence` is a separate evidence domain for signer ID, session ID, timestamp, authentication method and credential fingerprint. Its `authentication_verified` bit must come from an external verifier; the evidence root is not a signature.

`ApprovalGovernanceReceipt` evaluates expiry, revocation, delegation, escalation approvers, quorum, distinct sessions and separation of duties. Invalid or unauthenticated approvals simply cannot satisfy quorum.

`HITLResumeCheckpoint` content-addresses a paused run/invocation/approval state. `HITLResumeReceipt` accepts exactly one completed continuation and permits only explicitly rejected duplicate resumes after it. This supplies a durable duplicate-safe contract without claiming a particular database or queue is crash-proof.

## Distributed side effects and target acknowledgements

`DistributedSideEffectReceipt` expands run-local idempotency evidence to concurrent duplicates, timeout/cancellation retries, crash recovery, queue redelivery and multi-worker races. Attempts remain bound to one operation/idempotency key, and duplicate causes cannot compensate for a second committed mutation.

`TargetEffectAcknowledgement` records target-system effect identity plus external cryptographic verification metadata. `verify_target_acknowledgement()` requires an externally verified acknowledgement to bind the unique committed mutation. The framework does not implement the target's signature verifier and does not reinterpret its own hash as authentication.

## Production retrieval

`RetrievalPipelinePolicy` and `RetrievalPipelineReceipt` cover lexical/vector/hybrid modes, document lifecycle, collection/filter constraints, reranking, query rewrite evidence, citations and tenant isolation. Scores use bounded integers so acceptance never depends on floating-point rounding. Wrong-tenant, tombstoned/expired, filter-mismatched or uncited documents remain explicit violations.

The receipt verifies the declared pipeline observations; it does not prove a vector database or search service is globally correct.

## Persisted memory

`MemoryAssuranceReceipt` verifies a bounded record trace for persistence, cross-user/tenant isolation, deletion, TTL expiry and poisoning rejection. Cross-user leakage cannot be relabeled as successful persistence. The contract is backend-neutral and does not claim secure deletion from physical media.

## Environment chaos

`ChaosDomain` covers clock, DNS, filesystem, network, credential expiry, latency and resource pressure. `ChaosAssuranceReceipt` requires coverage and evaluator resource ceilings while preserving three outcomes separately: RECOVERED, SUBJECT_FAILURE and BLOCKED.

A complete chaos qualification means the declared disturbances were injected, bounded and classified. It is not a release PASS, and a BLOCKED evaluator condition is never flattened into subject failure.

## Non-claims

This layer does not establish universal Internet availability, arbitrary MCP-server safety, identity-provider correctness, real-human presence, cryptographic validity without an external verifier, exactly-once guarantees in an unmodeled distributed target, global retrieval correctness, physical secure deletion, or production chaos resilience outside the observed campaign. Those claims require the corresponding external evidence boundary.
