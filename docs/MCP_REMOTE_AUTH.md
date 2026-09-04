# MCP Remote Streamable HTTP Authorization

## Purpose

This laboratory tests a different trust boundary from both the in-process MCP fault laboratory and the separated OAuth authorization-code laboratory: a **real loopback TCP Streamable HTTP resource server protected by bearer authorization**.

It answers:

> Did the resource-server boundary enforce the configured authentication and authorization contract over actual HTTP, and can an authorized MCP client complete a real protocol request through that boundary?

The implementation uses `mcp==2.1.1`, `httpx2`, Uvicorn, a pre-bound `127.0.0.1` TCP socket, `MCPServer.streamable_http_app()`, the official Streamable HTTP client transport, and protocol revision `2026-07-28`.

It does not turn authorization evidence into an agent verdict. It also does not itself prove authorization-code issuance, PKCE, registration, or introspection; those are exercised by the separate [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md).

## Trust and enforcement ownership

Authentication, authorization, and token-policy decisions are deliberately attributed to the component that actually enforces them.

| Property | Enforcing component in this laboratory | Observation |
|---|---|---|
| bearer token present and verifier accepts token | MCP SDK bearer authentication middleware + configured verifier | HTTP 401 for missing/unknown/rejected token |
| token expiry | MCP SDK bearer authentication middleware | expired deterministic token returns HTTP 401 |
| exact issuer binding | deterministic lab `TokenVerifier` | wrong issuer is rejected before an `AccessToken` reaches MCP authorization |
| exact resource binding | deterministic lab `TokenVerifier` | token bound to a different resource is rejected with HTTP 401 |
| required scopes | MCP SDK authorization middleware | authenticated token missing a required scope returns HTTP 403 |
| protected-resource discovery | MCP SDK RFC 9728 route | metadata exposes exact resource, authorization server, and supported scopes |
| authorized protocol use | official MCP client over Streamable HTTP | valid scoped bearer completes `tools/list` and protected `tools/call` |

The SDK is **not** credited with issuer/resource validation that the custom verifier performs. Conversely, the verifier is not credited with the SDK's required-scope gate.

## Network boundary

The test does not use an in-process ASGI client.

```text
MCPRemoteAuthPolicy
        ↓
pre-bound 127.0.0.1 TCP socket
        ↓
Uvicorn
        ↓
MCP Streamable HTTP resource server
        ↓
bearer authentication / scope middleware
        ↓
protected MCP protocol endpoint
        ↓
real HTTP client + official MCP Streamable HTTP client
        ↓
MCPRemoteAuthProbeResult
        ↓
MCPRemoteAuthReceipt
```

A socket is bound before Uvicorn starts, preventing a check-then-bind race when selecting an ephemeral port. Server startup and shutdown are bounded, and the listener is closed even when the probe fails.

The transport label in evidence is:

```text
streamable-http-loopback
```

That label is intentionally narrower than `remote`, `Internet`, or `production` transport assurance.

## Content-addressed policy

`MCPRemoteAuthPolicy` is immutable and binds:

- schema version;
- stable lab ID;
- revision;
- absolute HTTPS authorization-server issuer URL;
- MCP resource path;
- canonical required-scope set;
- exact protected tool name.

Its SHA-256 identity is computed from canonical policy material. Scope order is normalized so equivalent scope sets do not acquire different identities merely because input order changed.

The policy rejects malformed issuer URLs, invalid resource paths, blank/duplicate scopes, and malformed tool names before the network probe begins.

## Deterministic authorization matrix

The test constructs deterministic non-secret token values and a verifier-owned token record set. It then observes this matrix through real HTTP:

```text
missing token           → 401 invalid_token
unknown token           → 401 invalid_token
expired token           → 401 invalid_token
wrong issuer            → verifier rejects → 401 invalid_token
wrong resource          → verifier rejects → 401 invalid_token
missing required scope  → 403 insufficient_scope
valid scoped token      → tools/list + protected tools/call succeed
```

Both 401 and 403 challenges must expose the protected-resource metadata location through `WWW-Authenticate`.

The successful MCP call must return the controlled result:

```text
authorized:hello
```

A successful HTTP status alone is insufficient for a receipt. The probe also requires the expected tool discovery and call result.

## RFC 9728 protected-resource metadata

The laboratory retrieves the actual protected-resource metadata endpoint over HTTP and requires:

- `resource` equals the exact loopback MCP resource URL;
- `authorization_servers` contains exactly the configured issuer;
- `scopes_supported` equals the canonical configured required scopes.

For a resource path `/mcp`, the route is expected at the SDK-generated form:

```text
/.well-known/oauth-protected-resource/mcp
```

Metadata is independent evidence. The laboratory does not infer it merely from local configuration objects.

## Receipt integrity

`MCPRemoteAuthReceipt` binds:

- schema version;
- exact `MCPRemoteAuthPolicy.identity`;
- negotiated/adopted protocol version;
- transport identity;
- SHA-256 of the canonical complete authorization observation;
- domain-separated receipt root.

The canonical observation includes status results, challenge headers, metadata values, protected resource URL, discovered tool names, and successful call text.

A receipt is emitted only when the complete matrix closes. A single correct 401, a correct metadata document, or one successful authorized call is not enough.

The surrounding `MCPRemoteAuthProbeResult` is a diagnostic result model, not a persisted authenticated evidence envelope. The embedded receipt validates its own policy/protocol/observation identity, but independently changing an outer diagnostic field does not cryptographically re-bind that field to the receipt.

## Credential handling

The deterministic token values exist only to exercise the resource-server boundary. The result and receipt do not serialize those token values.

The `WWW-Authenticate` **scheme** `Bearer` remains in evidence because it is required protocol output. Treating the word `Bearer` itself as a secret would erase the authentication challenge the test is supposed to verify.

The relevant invariant is:

```text
protocol challenge metadata may be evidence
actual bearer credential values must not be evidence
```

## CI boundary

The remote authorization laboratory has its own marker and job:

```bash
python -m pip install -e '.[dev,mcp]'
pytest -m mcp_remote tests/integration/test_mcp_remote_auth.py
```

This is separate from:

```bash
pytest -m mcp tests/integration/test_mcp_fault_lab.py
pytest -m mcp_oauth tests/integration/test_mcp_oauth_flow.py
```

The separation is architectural. In-process protocol semantics, resource-server enforcement, and OAuth-flow behavior can fail independently without one green result masking another.

Verified remote-auth checkpoint: **3/3 passed** over loopback TCP at implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc` (protected-main CI run `33881346071`).

## Relationship to the other MCP laboratories

The [MCP Protocol Fault Laboratory](MCP_LAB.md) verifies controlled content and discovery-state faults with an in-process official client/server pair.

This document verifies the isolated loopback resource-server authentication/authorization boundary.

The [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md) adds a separate authorization-server origin and official OAuth client path for protected-resource discovery, authorization-server metadata, compatibility Dynamic Client Registration, PKCE, RFC 9207 issuer validation, RFC 8707 resource binding, code exchange, authenticated token introspection, protected MCP use, and stored-authorization reuse.

The evidence models remain different:

```text
MCPFaultSpec          → MCPFaultReceipt
MCPRemoteAuthPolicy   → MCPRemoteAuthReceipt
MCPOAuthFlowPolicy    → MCPOAuthFlowReceipt
```

None is an OpenAI `AttackDeliveryReceipt`, `TrialEvidence`, agent verdict, or release decision.

Keeping those identities separate prevents a successful resource-server challenge from being confused with an OAuth issuance proof, prevents either auth result from being confused with schema-drift evidence, and prevents any protocol result from being confused with subject behavior.

## Explicit non-claims for this laboratory

`MCPRemoteAuthLab` itself does **not** establish:

- OAuth authorization-code, PKCE, registration, token issuance, or token-introspection behavior—those are tested separately by `MCPOAuthFlowLab`;
- a production or third-party authorization server / identity provider;
- real JWT signature/JWKS verification or production token formats;
- arbitrary issuer discovery or federation behavior;
- DPoP, mTLS, certificate binding, proof-of-possession, or hardware-backed credentials;
- credential rotation, refresh-token lifecycle, revocation, replay detection, or distributed token caches;
- credential-reuse resistance across real services beyond the exact deterministic resource binding exercised here;
- TLS, DNS, reverse proxies, gateways, load balancers, service meshes, cross-host routing, Internet transport, or remote hosted MCP fidelity;
- malformed HTTP/framing, disconnect, timeout, retry, rate-limit, or transport-chaos fault injection;
- authentication of the MCP server to an external client beyond local loopback transport and the deterministic harness;
- agent behavior after authorization succeeds or fails;
- production identity-provider or IAM assurance.

Those claims require tests at their actual enforcement boundaries.

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

[← MCP Protocol Fault Laboratory](MCP_LAB.md) · [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md) · [Documentation hub](README.md)
