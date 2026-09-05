# Limitations and Non-Claims

This document is intentionally strict. Repository claims must never become stronger than the executable evidence supporting them.

## Current non-claims

### No credentialed live-provider assurance yet

The OpenAI integration is pinned to `openai-agents==0.22.0`. CI exercises the real SDK runner/tool/handoff/approval/context loop deterministically with `agents.testing.ScriptedModel` and no provider API call.

The SDK tier covers all seven generic adversarial channel categories at scoped local/SDK boundaries. A separate `OpenAIAgentsHandoffAuthorityAdapter` exercises run-local native handoff authority attenuation. `OpenAIAgentsHITLApprovalAdapter` exercises one exact native `ToolApprovalItem` → evaluator decision → same-`RunState` continuation relation. Four additional adapters exercise exact official-MCP-stdio/OpenAI SDK paths: one `TOOL_METADATA_POISON` discovery → model-visible target-definition bridge, one `TOOL_RESULT_POISON` same-call bridge, one causal `TOOL_ERROR` → same-argument retry → benign recovery bridge, and one host-refreshed `TOOL_SCHEMA_DRIFT` adaptation bridge. `OpenAIAgentsSemanticJudge` separately exercises one concrete public SDK `Model` through a no-tools, one-turn evaluator boundary under deterministic `ScriptedModel` integration.

None of this establishes live-model quality, production-provider availability, provider-side delivery attestation, authenticated human approval, production IAM, or credentialed end-to-end assurance.

Terminal application state remains independently observed; provider output is not the state oracle.

### Semantic judging is calibrated subordinate evidence, not deterministic truth

`SemanticRubricSpec`, `SemanticJudgeProfile`, `SemanticCalibrationReceipt`, and `SemanticJudgmentReceipt` create a bounded meaning-level grading path. They do not make model judgment deterministic, universally correct, or safety-authoritative. The runtime calls a fresh semantic judge only after deterministic policy/outcome PASS; deterministic failure therefore cannot be rescued by semantic PASS and the candidate output is not disclosed through this semantic path after deterministic failure.

Calibration is exact-profile empirical evidence, not certification. The default acceptance policy requires balanced support, zero false PASS, zero abstention, zero judge failure, and explicit `judge-prompt-injection` coverage, but those gates do not prove universal prompt-injection resistance or correctness on unseen distributions. Model, model-revision label, evaluator prompt, adapter, response schema, or behavior-configuration drift changes profile identity and invalidates calibration reuse.

Semantic FAIL is non-critical and contributes to reliability failure counts; ABSTAIN becomes `INCONCLUSIVE`; malformed/unavailable/untrusted semantic evaluation becomes `BLOCKED`. A persisted semantic receipt can be replayed and revalidated without a fresh model call, but replay does not establish current judge liveness or reproducibility. Receipt/report hashes are integrity identities, not provider attestations or signatures.

The optional OpenAI judge test exercises the pinned SDK public `Model`/`Runner` interface with `agents.testing.ScriptedModel`; it does not call a live provider, prove provider-side model revision, establish human-equivalent review, or prove that candidate-output prompt injection is solved in general. See [Calibrated Semantic Judging](SEMANTIC_JUDGING.md).

### Seven generic channels do not mean universal interception

`OpenAIAgentsAdapter` implements:

- `USER_INPUT` as the second ordered SDK user message;
- local `TOOL_RESULT` as first matching local `FunctionTool` result replacement;
- local description-level `TOOL_METADATA` on a copied `FunctionTool`;
- SDK session-history `MEMORY` through a fresh per-trial `Session`;
- structured inline-file `RESOURCE` through one `input_file` item;
- native `HANDOFF` context through the first actual SDK handoff filter invocation;
- local runtime-context `ENVIRONMENT` through one consumed key in trial-local `RunContextWrapper.context` during the first matching local `FunctionTool` call.

These are concrete implementations of a generic taxonomy, not assertions that every production system carrying a similarly named boundary is intercepted.

The dedicated handoff-authority, native-HITL, and MCP adapters are separate integrations and do not widen these seven local/SDK mechanisms.

### `ENVIRONMENT` means local SDK application context, not infrastructure chaos

The implemented environment mode requires an identity-bearing payload with `tool`, `key`, and `environment`. Complete canonical `AttackFixture.payload_json` becomes the injected value.

The adapter accepts only `None` or string-keyed `Mapping` runtime context. It snapshots base context into a read-only trial-local overlay and uses task-local activation during the first matching local tool invocation.

Delivery is **consumption-bound**. The receipt is created only when subject code reads the targeted value through `ctx.context[key]` or `.get(key)`. Merely creating the overlay, executing the tool, or checking key membership does not prove delivery.

This mode does not claim process-global `os.environ` mutation; filesystem/browser/container/sandbox faults; network latency/partition/DNS/outage behavior; clocks; secret managers; provider deployment configuration; Kubernetes/cloud IAM/service-mesh/database chaos; arbitrary non-`Mapping` context; external-system consumption; or production chaos engineering.

### Local `TOOL_RESULT` replacement remains local

The ordinary `OpenAIAgentsAdapter` result mode targets one exact local SDK `FunctionTool`. On the first matching call the original function is deliberately not executed; exact canonical fixture JSON becomes the result. Later calls use copied original behavior.

That local injector still does not intercept hosted tools, MCP tools, or arbitrary external services.

MCP result, ToolError-recovery, and schema-drift adaptation assurance are covered only by the **separate** controlled stdio bridges described below. Their existence must not be retroactively attributed to the local `FunctionTool` injector.

### Local `TOOL_METADATA` means OpenAI description poisoning only

The OpenAI metadata mode changes only copied `FunctionTool.description`. It does not mutate tool name, parameter schema, callback, approval semantics, routing identity, hosted metadata, or external registries.

MCP description poisoning, schema drift, and identity drift exist in the protocol laboratory. Description poisoning now has a separate narrow model-visible delivery bridge, and schema drift has a separate host-refreshed v1→v2 adaptation bridge; identity drift remains protocol-only with respect to agent behavior. The metadata bridge proves exact exposure, not attention, interpretation, compliance, resistance, or safe behavior. Neither bridge turns local `TOOL_METADATA` replacement into an MCP mechanism or establishes arbitrary metadata/schema behavior.

### SDK session-history `MEMORY` is not production memory poisoning

The memory mode uses a fresh per-trial client-side SDK `Session` and one prior user item. It does not claim application-owned production session mutation, provider-managed conversations, vector/RAG memory, semantic retrieval manipulation, cross-user persistence, or external memory lifecycle assurance.

### Structured inline-file `RESOURCE` is not retrieval-system poisoning

The resource mode places exact canonical fixture JSON in one structured SDK `input_file.file_data` field with evaluator-owned filename `agent-evals-resource.json`.

It does not claim OpenAI hosted File Search, vector stores, embeddings, RAG retrieval/ranking/chunking/filtering/citations, `file_id`, `file_url`, browser pages, databases, object stores, production document repositories, MCP resource servers, or provider-side file parsing/retention attestation.

### Native SDK `HANDOFF` is context poisoning, not rerouting

The handoff mode appends exact canonical fixture JSON to cloned context for the first actual SDK handoff invoking the run-level filter. The SDK-selected destination remains unchanged.

It does not choose a new destination, rewrite handoff routing metadata, poison every transfer, intercept remote/distributed agent fabrics, or attest provider-side consumption.

### Native handoff authority is run-local evaluation assurance, not production IAM

`OpenAIAgentsHandoffAuthorityAdapter` is a separate assurance adapter; it does not change the meaning of the generic `HANDOFF` adversarial channel above. When a scenario configures `root_agent` and directed `handoff_grants`, the adapter binds that configured root to the supplied SDK `Agent.name` before model execution and records public SDK run-item generating-agent names for normalized tool request/result/approval evidence. Native handoff evidence is accepted only when the run-item generating agent agrees with the SDK handoff source identity.

`PolicyOracle`—not the SDK agent name, model output, or adapter—owns authorization. It advances active authority only after an observed source→target transition matches one explicit grant and that grant does not broaden the authority that actually reached its source agent. Delegated tools, resource prefixes, inherited-plus-stricter approval requirements, tool-call budgets, and handoff budgets are then graded against that path-local authority. A later grant that is independently inside root authority can still fail if it re-expands authority lost on an earlier hop.

The executable boundary is intentionally narrower than production identity and access management:

- SDK agent names are run-local evidence labels, not cryptographic principals, authenticated signer identities, or globally unique agent identities;
- the framework does not attest that a provider, remote agent runtime, or external target enforced the scenario grant;
- there is no cross-process or cross-host delegation token, capability credential, signed grant, distributed-agent-fabric attestation, or provider-side authorization proof;
- the framework does not establish organization/user identity, tenant membership, workforce identity, cloud IAM, hosted routing assurance, or production policy synchronization;
- the authority graph is evaluator-owned scenario configuration, not evidence that an independently administered production authorization system issued the same grant;
- resource-prefix authority remains lexical after adapter normalization, so deployment-grade canonicalization of aliases, traversal, URLs, case, and alternate identifiers remains external;
- the deterministic SDK tests use `agents.testing.ScriptedModel`; they do not establish live-model routing quality or provider availability.

Missing or contradictory SDK provenance—such as a configured root that does not match the supplied agent, missing call attribution, or request/result ownership disagreement—blocks evaluation as `EVALUATION_ERROR / BLOCKED`. Once the required provenance exists, an observed unauthorized transition or delegated action is deterministic subject evidence and remains a critical policy `FAIL`; evaluator uncertainty is not rewritten as a product defect, and a product defect is not downgraded to uncertainty merely because the run involved multiple agents.

### Native HITL approval intent is exact evaluator evidence, not human authentication

`OpenAIAgentsHITLApprovalAdapter` is a separate stronger approval-assurance boundary. It does not change the meaning of legacy call-scoped or persistent tool-scoped `APPROVAL` evidence for scenarios that do not configure `ApprovalIntentSpec`.

For the stronger path, the pinned SDK must expose one real `ToolApprovalItem` interruption before protected implementation execution. The framework normalizes that interruption as `APPROVAL_REQUEST`, binds the scenario-owned approve/reject intent to the exact run-local generating agent, tool, stable call ID, canonical finite JSON argument digest, normalized resource when scoped, accepted handoff-authority epoch, exact accepted handoff-path hash, and approval-request sequence, and emits one integrity-bound `APPROVAL_DECISION` receipt. The same SDK `RunState` is then resumed through `state.approve(...)` or `state.reject(...)`.

On approval, the verifier requires exactly one matching executable `TOOL_REQUEST` and exactly one matching non-rejection `TOOL_RESULT` after resume. On clean rejection, it requires explicit matching post-decision rejection-result evidence and no protected executable request. If the exact rejected invocation nevertheless reaches `TOOL_REQUEST`, that resolved chronology is preserved so deterministic policy grading can record execution-after-rejection as critical `FAIL` rather than evaluator uncertainty.

The stronger receipt is deliberately path-aware. Authority epoch is derived only from semantically accepted handoffs, not from a raw count of handoff-shaped events. The receipt also binds a domain-separated hash of the exact accepted handoff path, so different valid sibling paths that reach the same named agent at the same depth cannot reuse one another's approval.

Legacy approval evidence cannot silently downgrade this relation: neither a prior persistent tool approval nor a legacy call-scoped approval satisfies or overrides an `ApprovalIntentSpec` target.

This executable boundary still does **not** establish:

- the identity, presence, intent, competence, employment status, or authenticity of a real human approver;
- signatures, MACs, trusted timestamps, non-repudiation, hardware-backed approval, or external workflow attestation;
- enterprise approval routing, separation-of-duties policy, quorum/multi-party approval, escalation, expiry, revocation, or delegation semantics;
- production IAM/RBAC/ABAC, organization or tenant identity, workforce identity, or provider-side authorization enforcement;
- hosted approval UI correctness, anti-clickjacking/phishing properties, accessibility, or operator-session integrity;
- cross-process, cross-host, durable-queue, database-backed, or distributed resume safety;
- exactly-once distributed side effects merely because the controlled local SDK invocation executed once;
- live-model quality, provider availability, or arbitrary orchestration-framework HITL behavior;
- arbitrary hosted-tool or MCP approval behavior;
- proof that an external target enforced the evaluator's approval decision.

`ApprovalIntentReceipt.root_sha256` is an integrity value over evaluator-owned evidence, not an authenticated approver signature. The narrow claim remains historical and local to the controlled pinned-SDK relation: the exact interruption observed by the evaluator is the exact invocation whose approve/reject continuation is then verified.

---

## MCP protocol laboratory remains protocol evidence by default

`MCPFaultLab` uses official `mcp==2.1.1`, a real in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Six exact fault families are implemented:

- target-tool description poisoning through `tools/list`;
- first-call target-tool result poisoning through `tools/call`;
- model-visible first-call `ToolError` containing the canonical payload in the SDK-generated envelope;
- private `tools/list` stale discovery after server-side target removal;
- tool-schema drift across cached discovery, current call validation, refresh, and recovery;
- tool-identity drift across cached discovery, stale lookup, refresh, and recovery.

`MCPFaultReceipt` binds fault identity, protocol version, tool, observation point, controlled fault-material digest, exact canonical-observation digest, and a receipt root without duplicating raw fault content.

A raw `MCPFaultReceipt` does **not** establish agent consumption, resistance, correctness, `PASS`, `FAIL`, or release acceptance.

Two of the six fault families remain **protocol-only** with respect to agent behavior:

- `tool_list_stale_cache`;
- `tool_identity_drift`.

Four bridged families remain explicit additional contracts rather than exceptions to the trust model: `tool_metadata_poison`, `tool_result_poison`, `tool_error`, and `tool_schema_drift` each require independent cross-domain evidence and fault-specific relation closure before `PROTOCOL_DELIVERY` exists. For metadata poison, that relation closes at exact model-visible exposure and still does not establish a behavioral verdict.

## Controlled MCP `TOOL_METADATA_POISON` → OpenAI model-visible definition bridge

`OpenAIAgentsMCPToolMetadataAdapter` exercises one exact deterministic path through a fresh official MCP stdio server and the pinned OpenAI Agents SDK.

The bridge requires:

- a `TOOL_METADATA_POISON` fault only;
- fresh `MCPServerStdio` process/session state per trial;
- negotiated protocol `2026-07-28`;
- a base Agent with no preconfigured MCP servers, prefixed MCP naming, or local target-name collision;
- a concrete public SDK `Model` instance so evaluator observation does not change provider model resolution;
- one exact target description observed through official MCP discovery, producing a valid `MCPFaultReceipt`;
- exactly one target definition in the first bound public model-tool snapshot;
- exact target-name and description-digest equality across protocol/model observations;
- exact canonical JSON parameter-schema digest equality across those same observations;
- one `MCPAgentToolMetadataReceipt` binding scenario, protocol receipt, target, description/schema digests, model snapshot ordinal, and domain-separated root;
- metadata `PROTOCOL_DELIVERY` after any genuine leading pre-model `ATTACK_DELIVERY` but before normalized behavioral evidence;
- replay revalidation of that chronology and typed receipt.

The target tool does **not** need to execute. This is a delivery property, not a call property: poisoned tool metadata can affect selection before any invocation exists. Streaming is covered at the public `Model.stream_response(...)` boundary so it cannot bypass the observer.

The bridge does **not** establish that the model attended to, understood, followed, or resisted the description; arbitrary MCP metadata fields; live-provider behavior; hosted/remote MCP; schema poisoning; identity-drift adaptation; provider/target-side attestation; or safe behavior merely because delivery closed. Deterministic policy/outcome evidence remains the grading authority.

## Controlled MCP `TOOL_RESULT_POISON` → OpenAI agent bridge

`OpenAIAgentsMCPToolResultAdapter` exercises one exact deterministic path through a fresh official MCP stdio server and the pinned OpenAI Agents SDK.

The bridge requires:

- a `TOOL_RESULT_POISON` fault only;
- fresh `MCPServerStdio` process/session state per trial;
- base Agent with no preconfigured MCP servers;
- no local tool collision with the target;
- unprefixed MCP target naming for unambiguous identity;
- negotiated protocol `2026-07-28` from the connected MCP session;
- exactly one behavioral target call;
- one successful target text result creating a valid `MCPFaultReceipt`;
- one exact normalized OpenAI target `TOOL_REQUEST` with stable call ID;
- one exact matching `TOOL_RESULT`;
- logical output equivalence across the protocol result and SDK model-visible tool result;
- one `MCPAgentToolResultReceipt` binding scenario, protocol receipt, tool, call ID, and agent output;
- `PROTOCOL_DELIVERY` ordered before the matching `TOOL_RESULT`;
- same-argument benign recovery through the same still-connected MCP session **after** the agent run.

The bridge therefore establishes a narrow evaluation precondition: the controlled MCP result and the result attributed to that exact agent tool call are the same evaluated delivery fact.

It does **not** establish that the agent behaved safely merely because delivery closed. Policy and outcome oracles still decide behavioral PASS/FAIL.

## Controlled MCP `TOOL_ERROR` → causal OpenAI retry/recovery bridge

`OpenAIAgentsMCPToolErrorRecoveryAdapter` exercises a different deterministic path. Both target calls are part of the behavioral agent run.

The bridge requires:

- a `TOOL_ERROR` fault only;
- fresh official MCP stdio process/session state per trial;
- negotiated protocol `2026-07-28`;
- exactly two behavioral target calls;
- a real first-call MCP error result with the exact expected SDK-generated model-visible envelope;
- a valid `MCPFaultReceipt` created from that actual protocol observation;
- two stable, non-empty, distinct OpenAI target call IDs;
- exactly one normalized result for each call ID;
- finite canonical original/retry arguments whose digests are equal;
- strict normalized chronology `request₁ < result₁ < request₂ < result₂`;
- exact benign recovery on the second target call through the same live MCP session;
- one `MCPAgentToolErrorRecoveryReceipt` binding scenario, fault/protocol receipt, call identities, argument digest, error observation, recovery observation, and domain-separated root;
- `PROTOCOL_DELIVERY` emitted only after the recovery `TOOL_RESULT`.

The strict chronology is central to the claim. Two identical target calls issued before the first model-visible error result do **not** establish a retry reaction. That evidence fails closed as `mcp_error_retry_causality_unverified / EVALUATION_ERROR / BLOCKED`.

The bridge also blocks on missing retry, extra target calls, changed arguments, reused/missing call IDs, ambiguous result identity, protocol drift, malformed error/recovery shape, error mismatch, recovery mismatch, or malformed receipt.

It establishes one exact error → observed result → same-argument retry → benign recovery relation. It does not establish general fault tolerance merely because that relation closes.

## Controlled MCP `TOOL_SCHEMA_DRIFT` → host-refreshed OpenAI adaptation bridge

`OpenAIAgentsMCPToolSchemaDriftAdapter` exercises one exact v1→v2 schema-adaptation relation through a fresh official MCP stdio session and the pinned Agents SDK.

The bridge requires:

- a `TOOL_SCHEMA_DRIFT` fault whose payload matches the bound deterministic v1/v2 scalar-required fixture and positive TTL;
- fresh official MCP stdio process/session state per trial;
- negotiated protocol `2026-07-28`;
- a base Agent with no preconfigured MCP servers or colliding local target/control names;
- an evaluator-only server-side schema-swap control that is filtered from every agent-visible tool list;
- exact initial and cached v1 target schema observation;
- exactly two behavioral target calls with stable, non-empty, distinct OpenAI call IDs;
- the first target call using the exact bound stale v1 arguments;
- the hidden live schema swap occurring after v1 model selection but before the first call reaches MCP validation;
- a real MCP v2 validation rejection of the stale v1 arguments;
- exact equivalence between that protocol rejection and the pinned SDK's model-visible rejection;
- one evaluator/host-owned tool-cache invalidation only **after** the stale rejection;
- the first fresh post-invalidation `tools/list` exposing the exact bound v2 schema before recovery;
- the second target call using the exact bound v2 arguments;
- the exact replacement result through the same live MCP session;
- strict protocol chronology `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call`;
- one `MCPAgentToolSchemaDriftReceipt` binding the protocol receipt, schema/argument/observation digests, call identities, ordinals, and domain-separated root;
- `PROTOCOL_DELIVERY` emitted only after the recovery `TOOL_RESULT`.

The ownership boundary is intentional. The controlled harness owns the live schema replacement. The evaluator/host adapter owns one cache invalidation. The official MCP session supplies the first fresh post-invalidation listing. The pinned Agents SDK turns refreshed v2 discovery into the next model-visible tool definition. The agent is credited only for changing its second call after that v2 contract becomes visible.

Accordingly, this bridge does **not** establish model-initiated refresh or automatic `tools/list_changed` handling. Later SDK turns may reuse the already-refreshed v2 cache; such cached reads do not create additional refresh claims.

The bridge blocks on missing or extra target calls, recovery before refreshed discovery, repeated stale arguments, wrong v1/v2 schemas, wrong arguments or recovery, control-tool leakage, protocol drift, ambiguous identities, malformed observations, chronology violations, or receipt tampering.

It establishes one exact host-refreshed schema-adaptation relation. It does not establish arbitrary MCP schema migration or general dynamic-tool adaptation.

### The bridges are not generic MCP assurance

The implemented bridges do not claim:

- model attention to, interpretation of, compliance with, or resistance to MCP metadata poison after verified exposure;
- agent behavior for generic stale-cache or identity-drift faults;
- arbitrary MCP result/error/schema behavior outside the exact controlled contracts;
- generic retry policy, exponential backoff, jitter, retry budgets, idempotency, or side-effect safety;
- more than one ToolError retry;
- model-initiated MCP refresh or automatic `tools/list_changed` handling;
- arbitrary JSON Schema compatibility, optional/default/coercion semantics, or schema migration beyond the exact bound v1/v2 fixture;
- arbitrary tool rename/identity-drift adaptation;
- multiple controlled MCP servers or arbitrary parallel target plans;
- OpenAI hosted MCP interception;
- arbitrary third-party MCP servers;
- remote/Internet MCP fidelity;
- generic stdio transport correctness, subprocess isolation, or transport-chaos assurance beyond the exact deterministic fixture paths;
- TLS, DNS, proxy, gateway, load-balancer, service-mesh, latency, disconnect, retry, or packet-fault behavior;
- production authorization or identity-provider behavior;
- target-side cryptographic delivery attestation.

The bridge tests use `agents.testing.ScriptedModel`. They do not make live provider calls.

### Raw protocol receipt still is not a verdict

The distinction is:

```text
MCPFaultReceipt only
    = verified protocol observation

MCPFaultReceipt
+ exact agent call/result identity
+ fault-specific bridge invariants
    = verified PROTOCOL_DELIVERY receipt

verified PROTOCOL_DELIVERY
+ deterministic subject evidence
    = eligible for policy/outcome grading
```

For `TOOL_RESULT_POISON`, the fault-specific invariants are same-call output equivalence plus post-run same-session recovery. For `TOOL_ERROR`, they are exact model-visible error equivalence, distinct call IDs, same arguments, causal request/result chronology, and exact same-session recovery. For `TOOL_SCHEMA_DRIFT`, they are exact v1/v2 schema and argument digests, hidden live replacement, real stale rejection, host invalidation, first fresh v2 discovery before recovery, distinct call IDs, strict protocol chronology, and exact same-session replacement result.

Protocol evidence is necessary for these paths but never sufficient for behavioral conclusions by itself.

---

## Loopback MCP resource-server authorization is not OAuth issuance assurance

`MCPRemoteAuthLab` binds a real `127.0.0.1` TCP socket, runs Uvicorn with an MCP Streamable HTTP app, exercises resource-server authorization, fetches RFC 9728 protected-resource metadata, and completes an authenticated MCP request through the official client transport.

The deterministic matrix covers missing/unknown/expired/wrong-issuer/wrong-resource bearer rejection, missing-scope 403, and successful protected discovery/call for a valid scoped bearer.

Issuer/resource binding belongs to the deterministic `TokenVerifier`; bearer/expiry and required-scope handling are credited to the MCP SDK middleware.

`MCPRemoteAuthReceipt` binds the exact content-addressed policy and canonical observation. Deterministic bearer values are excluded from serialized result/receipt evidence.

This laboratory does not itself establish authorization-code/PKCE, client registration, token issuance, token introspection, agent behavior, or release acceptance.

It also does not establish production JWT/JWKS verification, DPoP/mTLS, refresh/revocation, replay detection, Internet transport, hosted MCP fidelity, production IAM, or authorization-server/IdP assurance.

## Separated loopback MCP OAuth flow is not production identity assurance

`MCPOAuthFlowLab` uses the official MCP `OAuthClientProvider` and independent loopback authorization-server/resource-server origins.

The deterministic flow closes RFC 9728 protected-resource discovery, authorization-server metadata, compatibility Dynamic Client Registration fallback, OAuth state, PKCE `S256`, exact RFC 9207 issuer validation, RFC 8707 resource binding, authorization-code exchange, opaque access-token issuance, authenticated HTTP introspection, fail-closed introspection policy, protected MCP use, and stored-authorization reuse on reconnect.

The resource-server verifier does not directly consult the authorization server's in-memory token table. Authorization code, access token, and introspection secret are excluded from serialized evidence.

This remains a deterministic loopback laboratory. It does not establish third-party/production IdP behavior, CIMD, enterprise-managed authorization, production JWT/JWKS/federation, DPoP/mTLS, refresh/revocation/replay lifecycle, browser consent/anti-phishing properties, production RFC 7662 interoperability, production IAM/tenant isolation, agent behavior after OAuth success/failure, or release acceptance from OAuth evidence alone.

Dynamic Client Registration is compatibility fallback behavior, not the preferred modern enrollment claim.

---

### Approval requests are not approvals; stronger decisions are still evaluator evidence

SDK `ToolApprovalItem` observations normalize as `APPROVAL_REQUEST`, never legacy `APPROVAL` and never executable `TOOL_REQUEST`. Asking for permission is not proof that permission was granted, and a pending invocation is not proof that protected implementation code ran.

Legacy provider-neutral call-scoped and persistent tool-scoped `APPROVAL` evidence remains supported. Separately, when a scenario configures `ApprovalIntentSpec`, only its exact integrity-bound `APPROVAL_DECISION` relation can satisfy the stronger native HITL requirement. Neither legacy approval scope can substitute for or override it.

Even a valid `ApprovalIntentReceipt` remains evaluator-owned evidence. It is not an authenticated human signature, production IAM decision, external workflow attestation, or proof that a remote target enforced the approval.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. Deterministic state and policy authority remain primary. A future semantic grader requires calibration, provenance, explicit failure semantics, and non-overriding precedence relative to critical deterministic failures.

### Delivery, approval, and protocol receipts are not target-side attestation

A valid OpenAI attack receipt proves consistency relative to the trusted evaluator's controlled observation. `ApprovalIntentReceipt` proves consistency between one scenario-owned decision and one exact recorded native approval interruption/continuation relation. `MCPFaultReceipt` proves consistency relative to a trusted protocol observation. `MCPAgentToolResultReceipt` proves consistency between one verified MCP result and one exact normalized OpenAI agent call/result boundary. `MCPAgentToolErrorRecoveryReceipt` proves consistency across one verified ToolError observation and one exact normalized causal retry/recovery relation. `MCPAgentToolSchemaDriftReceipt` proves consistency across one verified schema-drift protocol relation and one exact normalized host-refreshed agent adaptation relation. `MCPAgentToolMetadataReceipt` proves consistency between one exact verified MCP target-description observation and one exact model-visible target definition with the same parameter-schema digest. `MCPRemoteAuthReceipt` and `MCPOAuthFlowReceipt` prove their respective deterministic loopback observations.

None is independent cryptographic proof that a real human approved an invocation, an arbitrary remote target consumed content, a production issuer minted a token correctly, or a deployed agent respected policy.

Control-plane identities are labels/content identities, not authenticated signer identities. Receipt roots are SHA-256 integrity values, not signatures, MACs, trusted timestamps, or hardware attestation.

The public `MCPRemoteAuthProbeResult` and `MCPOAuthFlowProbeResult` envelopes are diagnostic result models, not persisted authenticated evidence envelopes. Their embedded receipt identities are validated, but independently changing an outer diagnostic field does not cryptographically re-bind that field to the receipt.

### Local persistence is not hostile-writer authentication

`LocalEvidenceStore` revalidates manifests, payload hashes, identities, evidence schema, semantic roots, symlink/file constraints, and no-clobber publication behavior. It does not authenticate a writer who can coherently replace all controlled files and recompute ordinary hashes.

The repository does not claim signatures/MACs, key management, trusted timestamps, remote attestation, WORM/object-lock storage, transparency-log anchoring, or cross-host durable retention.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial/subject/scenario identity and can reapply deterministic grading to recorded evidence. It does not rerun providers, tools, sessions, resources, handoffs, approval interruptions/human review, environment injectors, any of the MCP stdio bridges, protocol probes, authorization probes, OAuth flows, or external state readers and cannot establish fresh delivery or fresh authorization.

Persisted `APPROVAL_DECISION` evidence is semantically revalidated against its exact request, decision, continuation, scenario identity, canonical argument/resource identity, and accepted authority epoch/path. Persisted `PROTOCOL_DELIVERY` receipts are likewise semantically revalidated. Replay does not recreate the SDK/protocol relation that originally produced either receipt family.

### Assurance-report validation is not signed attestation

`AssuranceReport` rederives verdict consistency, reliability, critical-violation counts, release-gate output, and report root. The report root is integrity, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison uses an exact McNemar/binomial test for directional improvement/regression. Failure to detect significant regression is **not** formal non-inferiority.

### `pass@k` / `pass^k` are empirical approximations

Current formulas use observed resolved success proportion and an independent-attempt interpretation. Correlated, adaptive, or non-stationary trials can violate that approximation. `BLOCKED` and `INCONCLUSIVE` remain separate uncertainty.

### Resource-prefix policy is lexical

Resource scope uses string-prefix matching after adapter normalization. Real deployments must canonicalize aliases, traversal, case, URL forms, and alternate identifiers before lexical prefix comparison can represent the intended security boundary.

### No sandbox-isolation claim

The repository currently executes only controlled deterministic fixture subprocesses; it does not claim containment for arbitrary target-controlled code. Any future arbitrary-code executor must separately validate process, filesystem, and network isolation.

## Audited implementation checkpoint

Audited merged implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the original controlled MCP stdio result bridge: **15/15 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality jobs, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit reported **no known vulnerabilities**; the project package itself is skipped because it is not published on PyPI.

This checkpoint remains the historical audited merged implementation baseline. Capabilities added after it, including ToolError recovery, host-refreshed schema-drift adaptation, native OpenAI handoff-authority attenuation, and native HITL approval-intent binding, are accepted only after their own exact-head CI, merge, and post-merge `main` verification; documentation does not retroactively relabel the older checkpoint.

## Why these boundaries matter

Agent evaluation is unusually vulnerable to false confidence because outputs can look persuasive while surrounding state, authority, evaluator preconditions, approval provenance, protocol discovery, authorization boundaries, identity-flow assumptions, or cross-domain correlation are wrong.

The same discipline applies to this framework: documentation, badges, hashes, approval decisions, attack labels, protocol receipts, bridge receipts, HTTP statuses, OAuth responses, and traces are not substitutes for the exact control they describe.

Capabilities move out of this document only after implementation, deterministic evidence, and documentation review make the stronger claim true.
