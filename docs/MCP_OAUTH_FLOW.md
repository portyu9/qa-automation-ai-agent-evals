# MCP OAuth Authorization-Code Flow Laboratory

## Purpose

This laboratory tests an OAuth trust boundary that is deliberately separate from both the in-process MCP protocol-fault laboratory and the lower-level loopback resource-server authorization laboratory.

It answers:

> Can an MCP OAuth client discover the protected resource and authorization server, register when compatible fallback registration is needed, complete authorization code + PKCE with exact issuer and resource binding, exchange a code for an access token, have a separately hosted resource server validate that token through authenticated introspection, and then complete protected MCP requests without conflating any of those observations with agent behavior?

The implementation uses `mcp==2.1.1`, the official `OAuthClientProvider`, official Streamable HTTP client transport, two independent pre-bound loopback TCP origins, Uvicorn, `httpx2`, and MCP protocol revision `2026-07-28`.

This is a deterministic protocol/security laboratory. It is not a production identity provider, production IAM deployment, or agent verdict engine.

## Why this is separate from `MCPRemoteAuthLab`

`MCPRemoteAuthLab` starts with deterministic token records and asks whether the **resource-server boundary** correctly challenges, authenticates, applies verifier policy, applies scope policy, exposes protected-resource metadata, and permits a valid protected MCP call.

`MCPOAuthFlowLab` asks a different question: whether the **OAuth client / authorization-server / resource-server protocol path** closes end to end.

```text
MCPRemoteAuthPolicy
    → resource-server bearer/scope/verifier observations
    → MCPRemoteAuthReceipt

MCPOAuthFlowPolicy
    → PRM discovery
    → authorization-server metadata
    → compatible DCR fallback
    → authorization request + state + PKCE S256 + resource
    → authorization response + exact iss
    → code exchange
    → access token
    → authenticated HTTP introspection by separate resource server
    → protected MCP tools/list + tools/call
    → stored-authorization reuse
    → MCPOAuthFlowReceipt
```

A resource server can enforce bearer and scope rules correctly while an OAuth authorization flow is broken. Conversely, a client can complete an authorization flow while resource-server enforcement is wrong. Separate identities, tests, and CI jobs keep those failures attributable.

## Network and trust topology

The laboratory binds two different ephemeral loopback origins before starting either server:

```text
OAuthClientProvider
        │
        ├── HTTP discovery / registration / authorize / token
        ▼
Authorization Server origin A
127.0.0.1:<as-port>
        │
        │ authenticated introspection
        ▼
Resource Server origin B
127.0.0.1:<rs-port>/mcp
        ▲
        │ Streamable HTTP + bearer
        └── official MCP client
```

The resource server does not share the authorization server's in-memory token map as its verification mechanism. Its verifier sends an HTTP introspection request to the authorization-server origin using deterministic Basic client authentication. The returned active-token metadata is then checked for exact issuer and exact resource before an MCP `AccessToken` is constructed.

That separation is the central property of this layer.

## Content-addressed policy

`MCPOAuthFlowPolicy` is immutable and binds:

- schema version;
- stable lab ID;
- revision;
- MCP resource path;
- canonical required scopes;
- exact protected tool name;
- OAuth client name;
- redirect path.

Its identity is SHA-256 over canonical policy material. Scope input is normalized into a canonical sorted set and duplicate/blank scopes are rejected.

The policy does not contain bearer tokens, authorization codes, client secrets, or transient ports.

## Protected-resource discovery

The MCP resource server exposes RFC 9728 protected-resource metadata through the SDK-generated route. The OAuth client discovers that metadata from the resource URL.

The laboratory independently fetches and verifies the same metadata and requires:

- `resource` equals the exact loopback MCP resource URL;
- `authorization_servers` contains exactly the separate authorization-server issuer;
- `scopes_supported` equals the canonical policy scopes.

The metadata is observation, not an inference from local construction objects.

## Authorization-server metadata

The authorization-server origin exposes metadata consumed by `OAuthClientProvider`. The receipt contract requires exact values for:

- canonical issuer;
- authorization endpoint;
- token endpoint;
- registration endpoint;
- PKCE challenge methods containing exactly `S256` for this laboratory.

The issuer is intentionally canonical and slash-terminated. Authorization-response issuer validation is exact; `http://127.0.0.1:<port>` and `http://127.0.0.1:<port>/` are not treated as interchangeable after metadata establishes the issuer identity.

## Dynamic Client Registration compatibility fallback

The deterministic authorization server exposes a registration endpoint and the official OAuth client performs Dynamic Client Registration when it has no stored client information.

This is tested **compatibility fallback behavior**, not a claim that DCR is the preferred enrollment mechanism for new MCP deployments. MCP `2026-07-28` deprecates DCR in favor of Client ID Metadata Documents while retaining DCR compatibility during the transition.

The receipt requires exactly one registration during the first authorization flow and no second registration on the reconnect that reuses stored authorization state.

## PKCE, state, issuer, and resource binding

A receipt is withheld unless the observed authorization request contains:

- a non-empty OAuth `state` value;
- a non-empty PKCE `code_challenge`;
- `code_challenge_method=S256`;
- the exact RFC 8707 `resource` value for the protected MCP resource;
- exactly the policy-required scopes.

The headless authorization handler follows the authorization endpoint only to capture deterministic protocol metadata. It does not weaken SDK-side validation.

The authorization response must carry the exact issuer expected from authorization-server metadata. The official MCP OAuth client validates that `iss` before token redemption. A mismatch causes the flow to fail rather than being normalized away.

## Authorization code and access token issuance

The loopback authorization-server provider mints deterministic opaque fixture values for the code and access token so the flow can be reproduced without credentials or randomness in the evidence contract.

The authorization code binds:

- registered client identity;
- requested scopes;
- PKCE challenge;
- redirect URI;
- exact resource;
- deterministic subject.

The token exchange refuses to lose that resource binding. The resulting access token carries the same client/scopes/resource/subject plus the canonical issuer claim.

The deterministic values are test credentials used to exercise the boundary. They are not production credentials and are not serialized into the probe result or receipt.

## Authenticated token introspection

The resource-server verifier calls the separate authorization-server `/introspect` endpoint over HTTP.

```text
resource server verifier
    → Basic-authenticated POST /introspect
    → token=<opaque access token>
    ← active + client_id + scope + exp + sub + iss + aud
```

The verifier fails closed when:

- the introspection endpoint is unavailable or returns a non-200 response;
- JSON is invalid;
- `active` is not true;
- issuer differs from the exact expected issuer;
- audience/resource differs from the exact MCP resource;
- `client_id` is absent/invalid;
- expiration is invalid or expired;
- subject type is invalid.

Only after those checks does the verifier construct an MCP `AccessToken` for resource-server middleware.

The authorization server's in-memory token table is therefore not directly consulted by the resource server.

## Protected MCP use and stored-authorization reuse

After authorization closes, the official MCP client must:

1. refresh `tools/list` and observe exactly the protected tool;
2. call the protected tool and receive the deterministic authenticated-subject result;
3. disconnect;
4. reconnect through the same OAuth-authenticated HTTP client;
5. call the protected tool again.

The provider counters must remain unchanged after reconnect:

```text
registration_count   = 1
authorization_count  = 1
token_exchange_count = 1
```

That proves the second MCP connection reused stored OAuth client/token state rather than silently repeating the interactive authorization path.

The laboratory does not currently exercise refresh-token rotation; reuse here means reuse of still-valid stored authorization material.

## Receipt integrity

`MCPOAuthFlowReceipt` binds:

- schema version;
- exact `MCPOAuthFlowPolicy.identity`;
- MCP protocol version;
- transport identity `oauth-code-pkce-loopback`;
- SHA-256 of the canonical complete observation;
- receipt root derived from those fields.

The canonical observation covers the discovered metadata, authorization request properties, authorization response issuer, registration/authorization/token-exchange counts, introspection observations, protected tool discovery/call results, and reconnect behavior.

A receipt is emitted only when the complete relation closes. Individual successes—such as a correct metadata response, a token response, or one protected tool call—are insufficient by themselves.

The surrounding `MCPOAuthFlowProbeResult` is a diagnostic result model, not a persisted authenticated evidence envelope. The embedded receipt validates its own policy/protocol/observation identity, but independently changing an outer diagnostic field does not cryptographically re-bind that field to the receipt.

## Credential minimization

The following deterministic values exist during execution but must not appear in `MCPOAuthFlowProbeResult` or `MCPOAuthFlowReceipt` serialization:

- authorization code;
- access token;
- resource-server introspection secret.

The standardized token type label `Bearer` is protocol metadata, not credential material.

## Evidence-domain separation

The repository currently has four distinct protocol/adversarial evidence identities:

```text
AttackFixture          → AttackDeliveryReceipt
MCPFaultSpec           → MCPFaultReceipt
MCPRemoteAuthPolicy    → MCPRemoteAuthReceipt
MCPOAuthFlowPolicy     → MCPOAuthFlowReceipt
```

The OAuth-flow receipt is not inserted into `TrialEvidence`, does not become OpenAI `ATTACK_DELIVERY`, and does not derive agent `PASS`, `FAIL`, release `ACCEPT`, or release `REJECT`.

A future agent-through-MCP integration must define the explicit bridge between protocol security evidence and subject behavior.

## CI boundary

The OAuth-flow laboratory has its own marker and CI job:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp_oauth tests/integration/test_mcp_oauth_flow.py
```

It is independent from:

```bash
pytest -m mcp tests/integration/test_mcp_fault_lab.py
pytest -m mcp_remote tests/integration/test_mcp_remote_auth.py
```

Verified OAuth-flow checkpoint: **3/3 passed** at implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc` (protected-main CI run `33881346071`).

## Explicit non-claims

This laboratory does **not** establish:

- a third-party or production authorization server / identity provider;
- Internet, cross-host, TLS, reverse-proxy, gateway, load-balancer, service-mesh, DNS, or hosted MCP fidelity;
- JWT access-token signatures, JWKS retrieval/rotation, asymmetric token verification, or production token formats;
- federation or arbitrary issuer discovery beyond the exact separated loopback issuer;
- Client ID Metadata Documents (CIMD) enrollment;
- Enterprise Managed Authorization or SEP-990 identity-assertion flows;
- DPoP, mTLS, certificate binding, hardware-backed keys, or other proof-of-possession mechanisms;
- refresh-token issuance, refresh rotation, token revocation, revocation propagation, replay detection, or distributed token caches;
- production credential storage/rotation or secret-manager integration;
- browser/user-consent UX or anti-phishing properties;
- compromise resistance of the deterministic loopback authorization server;
- production RFC 7662 deployment interoperability—the introspection endpoint is a deterministic laboratory implementation using RFC 7662-style active-token metadata and authenticated lookup;
- production IAM policy, tenant isolation, or organization authorization semantics;
- agent behavior after OAuth success/failure;
- release acceptance from OAuth evidence alone.

The correct claim is narrower: the repository executes and verifies a separated two-origin loopback OAuth authorization-code/PKCE flow with MCP discovery, exact issuer/resource binding, compatibility DCR, token exchange, authenticated HTTP introspection, protected MCP access, and stored-authorization reuse.

## Verified implementation checkpoint

Implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc`, protected-main CI run `33881346071`:

- deterministic core: **330 passed, 23 deselected**;
- branch coverage: **93.61%** against the 90% gate;
- strict mypy: **0 issues across 40 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint identifies the audited implementation revision. This documentation-only synchronization is validated separately by pull-request CI and does not silently redefine the implementation evidence.

[← MCP Remote Authorization](MCP_REMOTE_AUTH.md) · [MCP Protocol Fault Laboratory](MCP_LAB.md) · [Documentation hub](README.md)
