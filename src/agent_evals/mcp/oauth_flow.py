"""Deterministic OAuth authorization-code/PKCE laboratory for separated MCP AS/RS roles."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal, Self
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.mcp._loopback import bind_loopback_socket, serve_prebound

_PROTOCOL_VERSION = "2026-07-28"
_POLICY_SCHEMA: Literal["agent-evals/mcp-oauth-flow-policy/v1"] = (
    "agent-evals/mcp-oauth-flow-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/mcp-oauth-flow-receipt/v1"] = (
    "agent-evals/mcp-oauth-flow-receipt/v1"
)
_TRANSPORT: Literal["oauth-code-pkce-loopback"] = "oauth-code-pkce-loopback"
_SUBJECT = "agent-evals-user"


class MCPOAuthFlowPolicy(BaseModel):
    """Content-addressed contract for a separated loopback authorization-code flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-oauth-flow-policy/v1"] = _POLICY_SCHEMA
    lab_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    revision: str = Field(min_length=1, max_length=128)
    resource_path: str = Field(default="/mcp", min_length=1, max_length=256)
    required_scopes: tuple[str, ...]
    tool_name: str = Field(min_length=1, max_length=128)
    client_name: str = Field(default="agent-evals-oauth-client", min_length=1, max_length=128)
    redirect_path: str = Field(default="/oauth/callback", min_length=1, max_length=256)

    @field_validator("resource_path", "redirect_path")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("MCP OAuth-flow paths must be absolute single-slash paths")
        if "?" in value or "#" in value:
            raise ValueError("MCP OAuth-flow paths must not contain query or fragment")
        return value

    @field_validator("required_scopes")
    @classmethod
    def validate_required_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("MCP OAuth-flow required_scopes must not be empty")
        for scope in value:
            if not scope.strip() or scope != scope.strip() or any(char.isspace() for char in scope):
                raise ValueError("MCP OAuth-flow scopes must be non-empty tokens without whitespace")
        if len(set(value)) != len(value):
            raise ValueError("MCP OAuth-flow required_scopes must not contain duplicates")
        return tuple(sorted(value))

    @field_validator("tool_name", "client_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("MCP OAuth-flow names must be non-empty without surrounding whitespace")
        return value

    @property
    def identity(self) -> str:
        return _sha256_json(
            {
                "schema_version": self.schema_version,
                "lab_id": self.lab_id,
                "revision": self.revision,
                "resource_path": self.resource_path,
                "required_scopes": self.required_scopes,
                "tool_name": self.tool_name,
                "client_name": self.client_name,
                "redirect_path": self.redirect_path,
            }
        )


class MCPOAuthFlowReceipt(BaseModel):
    """Integrity-bound observation of one exact separated AS/RS OAuth flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-oauth-flow-receipt/v1"] = _RECEIPT_SCHEMA
    policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    transport: Literal["oauth-code-pkce-loopback"] = _TRANSPORT
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: MCPOAuthFlowPolicy,
        observation_json: str,
        protocol_version: str = _PROTOCOL_VERSION,
    ) -> Self:
        observation_sha256 = _sha256_text(observation_json)
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy_identity": policy.identity,
            "protocol_version": protocol_version,
            "transport": _TRANSPORT,
            "observation_sha256": observation_sha256,
        }
        return cls(
            policy_identity=policy.identity,
            protocol_version=protocol_version,
            observation_sha256=observation_sha256,
            receipt_root=_sha256_json(material),
        )

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "policy_identity": self.policy_identity,
            "protocol_version": self.protocol_version,
            "transport": self.transport,
            "observation_sha256": self.observation_sha256,
        }
        if self.receipt_root != _sha256_json(material):
            raise ValueError("MCP OAuth-flow receipt root does not match receipt material")
        return self


class MCPOAuthFlowProbeResult(BaseModel):
    """Observable authorization, issuance, introspection, and MCP outcomes from one flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    transport: Literal["oauth-code-pkce-loopback"] = _TRANSPORT
    issuer_url: str
    resource_url: str
    protected_resource_metadata_url: str
    protected_resource_authorization_servers: tuple[str, ...]
    protected_resource_scopes_supported: tuple[str, ...]
    authorization_metadata_issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    code_challenge_methods_supported: tuple[str, ...]
    authorization_request_state_present: bool
    authorization_request_code_challenge_present: bool
    authorization_request_code_challenge_method: str
    authorization_request_resource: str
    authorization_request_scopes: tuple[str, ...]
    authorization_response_issuer: str
    registration_count: int = Field(ge=0)
    authorization_count: int = Field(ge=0)
    token_exchange_count: int = Field(ge=0)
    introspection_count: int = Field(ge=0)
    introspection_last_issuer: str
    introspection_last_resource: str
    introspection_last_scopes: tuple[str, ...]
    reused_stored_authorization: bool
    valid_tool_names: tuple[str, ...]
    valid_call_text: tuple[str, ...]
    reconnect_call_text: tuple[str, ...]
    receipt: MCPOAuthFlowReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        if self.receipt is None:
            return self
        if self.receipt.policy_identity != self.policy_identity:
            raise ValueError("MCP OAuth-flow receipt policy identity does not match probe")
        if self.receipt.protocol_version != self.protocol_version:
            raise ValueError("MCP OAuth-flow receipt protocol version does not match probe")
        return self


class _TokenStorage:
    """In-memory OAuth client storage; token material never appears in probe output."""

    def __init__(self) -> None:
        self.tokens: Any | None = None
        self.client_info: Any | None = None

    async def get_tokens(self) -> Any | None:
        return self.tokens

    async def set_tokens(self, tokens: Any) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> Any | None:
        return self.client_info

    async def set_client_info(self, client_info: Any) -> None:
        self.client_info = client_info


class _AuthorizationServerProvider:
    """Deterministic OAuth AS provider with exact resource and scope binding."""

    def __init__(
        self,
        *,
        policy: MCPOAuthFlowPolicy,
        issuer_url: str,
        resource_url: str,
    ) -> None:
        self._policy = policy
        self._issuer_url = issuer_url
        self._resource_url = resource_url
        self.clients: dict[str, Any] = {}
        self.codes: dict[str, Any] = {}
        self.access_tokens: dict[str, Any] = {}
        self.registration_count = 0
        self.authorization_count = 0
        self.token_exchange_count = 0
        self.introspection_count = 0
        self.last_introspection: dict[str, Any] = {}

    async def get_client(self, client_id: str) -> Any | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: Any) -> None:
        client_id = getattr(client_info, "client_id", None)
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("registered OAuth client must contain a client_id")
        self.clients[client_id] = client_info
        self.registration_count += 1

    async def authorize(self, client: Any, params: Any) -> str:
        from mcp.server.auth.provider import (
            AuthorizationCode,
            AuthorizeError,
            construct_redirect_uri,
        )

        client_id = getattr(client, "client_id", None)
        if not isinstance(client_id, str) or not client_id:
            raise AuthorizeError(error="unauthorized_client", error_description="missing client_id")
        requested_scopes = tuple(sorted(params.scopes or []))
        if requested_scopes != self._policy.required_scopes:
            raise AuthorizeError(
                error="invalid_scope",
                error_description="requested scopes must exactly match the evaluation policy",
            )
        if params.resource != self._resource_url:
            raise AuthorizeError(
                error="invalid_target",
                error_description="resource indicator does not match the protected MCP resource",
            )
        self.authorization_count += 1
        code_value = _opaque_fixture_value(
            "authorization-code",
            self._policy.identity,
            self.authorization_count,
        )
        code = AuthorizationCode(
            code=code_value,
            client_id=client_id,
            scopes=list(requested_scopes),
            expires_at=time.time() + 300,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=_SUBJECT,
        )
        self.codes[code.code] = code
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code.code,
            state=params.state,
            iss=self._issuer_url,
        )

    async def load_authorization_code(self, client: Any, authorization_code: str) -> Any | None:
        stored = self.codes.get(authorization_code)
        if stored is None:
            return None
        if getattr(stored, "client_id", None) != getattr(client, "client_id", None):
            return None
        return stored

    async def exchange_authorization_code(self, client: Any, authorization_code: Any) -> Any:
        from mcp.server.auth.provider import AccessToken
        from mcp.shared.auth import OAuthToken

        if authorization_code.resource != self._resource_url:
            raise RuntimeError("authorization code lost exact resource binding")
        self.token_exchange_count += 1
        access_value = _opaque_fixture_value(
            "access-token",
            self._policy.identity,
            self.token_exchange_count,
        )
        access = AccessToken(
            token=access_value,
            client_id=authorization_code.client_id,
            scopes=list(authorization_code.scopes),
            expires_at=int(time.time()) + 3600,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
            claims={"iss": self._issuer_url},
        )
        self.access_tokens[access_value] = access
        self.codes.pop(authorization_code.code, None)
        return OAuthToken(
            access_token=access_value,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(self, client: Any, refresh_token: str) -> Any | None:
        raise NotImplementedError

    async def exchange_refresh_token(
        self,
        client: Any,
        refresh_token: Any,
        scopes: list[str],
    ) -> Any:
        raise NotImplementedError

    async def load_access_token(self, token: str) -> Any | None:
        return self.access_tokens.get(token)

    async def revoke_token(self, token: Any) -> None:
        value = getattr(token, "token", None)
        if isinstance(value, str):
            self.access_tokens.pop(value, None)

    def introspect(self, token: str) -> dict[str, Any]:
        self.introspection_count += 1
        access = self.access_tokens.get(token)
        if access is None or (
            access.expires_at is not None and int(access.expires_at) <= int(time.time())
        ):
            self.last_introspection = {"active": False}
            return {"active": False}
        claims = access.claims or {}
        response = {
            "active": True,
            "aud": access.resource,
            "client_id": access.client_id,
            "exp": access.expires_at,
            "iss": str(claims.get("iss", "")),
            "scope": " ".join(access.scopes),
            "sub": access.subject,
            "token_type": "Bearer",
        }
        self.last_introspection = response
        return response


class _IntrospectionTokenVerifier:
    """Resource-server verifier that obtains token state from a separate AS over HTTP."""

    def __init__(
        self,
        *,
        introspection_url: str,
        expected_issuer: str,
        expected_resource: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._introspection_url = introspection_url
        self._expected_issuer = expected_issuer
        self._expected_resource = expected_resource
        self._client_id = client_id
        self._client_secret = client_secret

    async def verify_token(self, token: str) -> Any | None:
        import httpx2
        from mcp.server.auth.provider import AccessToken

        async with httpx2.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.post(
                    self._introspection_url,
                    data={"token": token},
                    auth=(self._client_id, self._client_secret),
                )
            except Exception:
                return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        if data.get("active") is not True:
            return None
        issuer = data.get("iss")
        resource = data.get("aud")
        if issuer != self._expected_issuer or resource != self._expected_resource:
            return None
        scopes = tuple(sorted(str(data.get("scope", "")).split()))
        client_id = data.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            return None
        expires_at = data.get("exp")
        if expires_at is not None and (
            not isinstance(expires_at, int) or expires_at <= int(time.time())
        ):
            return None
        subject = data.get("sub")
        if subject is not None and not isinstance(subject, str):
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=list(scopes),
            expires_at=expires_at,
            resource=resource,
            subject=subject,
            claims={"iss": issuer},
        )


class _HeadlessOAuth:
    """Capture OAuth request/response metadata while following authorization headlessly."""

    def __init__(self, http: Any) -> None:
        from mcp.shared.auth import AuthorizationCodeResult

        self._http = http
        self.authorization_request: dict[str, Any] = {}
        self.authorization_response: dict[str, Any] = {}
        self._result = AuthorizationCodeResult(code="", state=None, iss=None)

    async def redirect_handler(self, authorization_url: str) -> None:
        from mcp.shared.auth import AuthorizationCodeResult

        query = parse_qs(urlsplit(authorization_url).query)
        self.authorization_request = {
            "code_challenge": _single_query_value(query, "code_challenge"),
            "code_challenge_method": _single_query_value(query, "code_challenge_method"),
            "resource": _single_query_value(query, "resource"),
            "scope": _single_query_value(query, "scope"),
            "state": _single_query_value(query, "state"),
        }
        response = await self._http.get(authorization_url, follow_redirects=False)
        if response.status_code != 302:
            raise RuntimeError(
                f"MCP OAuth-flow authorization endpoint returned {response.status_code}"
            )
        redirected = parse_qs(urlsplit(response.headers.get("location", "")).query)
        issuer = _single_query_value(redirected, "iss")
        self.authorization_response = {"iss": issuer}
        self._result = AuthorizationCodeResult(
            code=_single_query_value(redirected, "code"),
            state=_single_query_value(redirected, "state") or None,
            iss=issuer or None,
        )

    async def callback_handler(self) -> Any:
        return self._result


class MCPOAuthFlowLab:
    """Exercise OAuth discovery, PKCE issuance, introspection, and protected MCP use."""

    def __init__(self, policy: MCPOAuthFlowPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> MCPOAuthFlowPolicy:
        return self._policy

    async def probe(self) -> MCPOAuthFlowProbeResult:
        import httpx2
        from mcp import Client
        from mcp.client.auth import OAuthClientProvider
        from mcp.server import MCPServer
        from mcp.server.auth.middleware.auth_context import get_access_token
        from mcp.server.auth.routes import build_resource_metadata_url
        from mcp.server.auth.settings import AuthSettings
        from mcp.shared.auth import OAuthClientMetadata
        from pydantic import AnyHttpUrl, AnyUrl

        as_listener = bind_loopback_socket()
        rs_listener = bind_loopback_socket()
        issuer_url = f"http://127.0.0.1:{int(as_listener.getsockname()[1])}"
        resource_url = (
            f"http://127.0.0.1:{int(rs_listener.getsockname()[1])}"
            f"{self._policy.resource_path}"
        )
        redirect_uri = f"http://127.0.0.1{self._policy.redirect_path}"
        introspection_url = f"{issuer_url}/introspect"
        introspection_id = "agent-evals-resource-server"
        introspection_secret = _opaque_fixture_value(
            "introspection-secret",
            self._policy.identity,
            1,
        )
        provider = _AuthorizationServerProvider(
            policy=self._policy,
            issuer_url=issuer_url,
            resource_url=resource_url,
        )
        as_app = _authorization_server_app(
            provider=provider,
            issuer_url=issuer_url,
            required_scopes=self._policy.required_scopes,
            introspection_client_id=introspection_id,
            introspection_client_secret=introspection_secret,
        )
        verifier = _IntrospectionTokenVerifier(
            introspection_url=introspection_url,
            expected_issuer=issuer_url,
            expected_resource=resource_url,
            client_id=introspection_id,
            client_secret=introspection_secret,
        )
        rs = MCPServer(
            f"agent-evals-oauth-rs:{self._policy.lab_id}",
            token_verifier=verifier,
            auth=AuthSettings(
                issuer_url=AnyHttpUrl(issuer_url),
                resource_server_url=AnyHttpUrl(resource_url),
                required_scopes=list(self._policy.required_scopes),
            ),
        )

        def protected_tool(message: str) -> str:
            token = get_access_token()
            if token is None or token.subject != _SUBJECT:
                raise RuntimeError("separated OAuth resource server lost authenticated principal")
            return f"oauth:{token.subject}:{message}"

        rs.add_tool(
            protected_tool,
            name=self._policy.tool_name,
            description="Protected MCP tool reached only through the separated OAuth flow.",
            structured_output=False,
        )
        rs_app = rs.streamable_http_app(
            streamable_http_path=self._policy.resource_path,
            json_response=True,
            stateless_http=True,
            host="127.0.0.1",
        )
        metadata_url = str(build_resource_metadata_url(AnyHttpUrl(resource_url)))
        storage = _TokenStorage()

        try:
            async with (
                serve_prebound(as_app, as_listener),
                serve_prebound(rs_app, rs_listener),
                httpx2.AsyncClient(timeout=5.0) as bare_http,
                httpx2.AsyncClient(timeout=5.0) as metadata_http,
            ):
                headless = _HeadlessOAuth(bare_http)
                oauth_auth = OAuthClientProvider(
                    server_url=resource_url,
                    client_metadata=OAuthClientMetadata(
                        client_name=self._policy.client_name,
                        redirect_uris=[AnyUrl(redirect_uri)],
                        grant_types=["authorization_code"],
                        response_types=["code"],
                        scope=" ".join(self._policy.required_scopes),
                    ),
                    storage=storage,
                    redirect_handler=headless.redirect_handler,
                    callback_handler=headless.callback_handler,
                )
                async with httpx2.AsyncClient(
                    auth=oauth_auth,
                    timeout=5.0,
                ) as authed_http:
                    first_transport = _oauth_transport(resource_url, authed_http)
                    async with Client(
                        first_transport,
                        mode=_PROTOCOL_VERSION,
                        raise_exceptions=True,
                    ) as client:
                        listed = await client.list_tools(cache_mode="refresh")
                        called = await client.call_tool(
                            self._policy.tool_name,
                            {"message": "hello"},
                        )
                        protocol_version = client.protocol_version
                    counts_after_first = (
                        provider.registration_count,
                        provider.authorization_count,
                        provider.token_exchange_count,
                    )
                    second_transport = _oauth_transport(resource_url, authed_http)
                    async with Client(
                        second_transport,
                        mode=_PROTOCOL_VERSION,
                        raise_exceptions=True,
                    ) as client:
                        reconnected = await client.call_tool(
                            self._policy.tool_name,
                            {"message": "again"},
                        )
                as_metadata_response = await metadata_http.get(
                    f"{issuer_url}/.well-known/oauth-authorization-server"
                )
                as_metadata_response.raise_for_status()
                as_metadata = as_metadata_response.json()
                prm_response = await metadata_http.get(metadata_url)
                prm_response.raise_for_status()
                prm = prm_response.json()
        finally:
            if as_listener.fileno() != -1:
                as_listener.close()
            if rs_listener.fileno() != -1:
                rs_listener.close()

        counts_after_second = (
            provider.registration_count,
            provider.authorization_count,
            provider.token_exchange_count,
        )
        valid_tool_names = tuple(sorted(tool.name for tool in listed.tools))
        valid_call_text = _text_content(called.content)
        reconnect_call_text = _text_content(reconnected.content)
        request = headless.authorization_request
        response = headless.authorization_response
        introspection = provider.last_introspection
        prm_authorization_servers = tuple(
            str(value) for value in prm.get("authorization_servers", [])
        )
        prm_scopes_supported = tuple(
            sorted(str(value) for value in prm.get("scopes_supported", []))
        )
        reused_stored_authorization = counts_after_second == counts_after_first

        observation: dict[str, Any] = {
            "authorization_count": provider.authorization_count,
            "authorization_endpoint": str(as_metadata.get("authorization_endpoint", "")),
            "authorization_metadata_issuer": str(as_metadata.get("issuer", "")),
            "authorization_request_code_challenge_method": str(
                request.get("code_challenge_method", "")
            ),
            "authorization_request_code_challenge_present": bool(request.get("code_challenge")),
            "authorization_request_resource": str(request.get("resource", "")),
            "authorization_request_scopes": tuple(sorted(str(request.get("scope", "")).split())),
            "authorization_request_state_present": bool(request.get("state")),
            "authorization_response_issuer": str(response.get("iss", "")),
            "code_challenge_methods_supported": tuple(
                str(item) for item in as_metadata.get("code_challenge_methods_supported", [])
            ),
            "introspection_count": provider.introspection_count,
            "introspection_last_issuer": str(introspection.get("iss", "")),
            "introspection_last_resource": str(introspection.get("aud", "")),
            "introspection_last_scopes": tuple(
                sorted(str(introspection.get("scope", "")).split())
            ),
            "issuer_url": issuer_url,
            "protected_resource_authorization_servers": prm_authorization_servers,
            "protected_resource_metadata_url": metadata_url,
            "protected_resource_scopes_supported": prm_scopes_supported,
            "registration_count": provider.registration_count,
            "registration_endpoint": str(as_metadata.get("registration_endpoint", "")),
            "resource_url": resource_url,
            "reconnect_call_text": reconnect_call_text,
            "reused_stored_authorization": reused_stored_authorization,
            "token_endpoint": str(as_metadata.get("token_endpoint", "")),
            "token_exchange_count": provider.token_exchange_count,
            "transport": _TRANSPORT,
            "valid_call_text": valid_call_text,
            "valid_tool_names": valid_tool_names,
        }
        observation_json = _canonical_json(observation)
        receipt = self._receipt_for_observation(
            protocol_version=protocol_version,
            issuer_url=issuer_url,
            resource_url=resource_url,
            metadata_url=metadata_url,
            as_metadata=as_metadata,
            prm=prm,
            request=request,
            response=response,
            introspection=introspection,
            valid_tool_names=valid_tool_names,
            valid_call_text=valid_call_text,
            reconnect_call_text=reconnect_call_text,
            counts_after_first=counts_after_first,
            counts_after_second=counts_after_second,
            introspection_count=provider.introspection_count,
            observation_json=observation_json,
        )
        return MCPOAuthFlowProbeResult(
            policy_identity=self._policy.identity,
            protocol_version=protocol_version,
            issuer_url=issuer_url,
            resource_url=resource_url,
            protected_resource_metadata_url=metadata_url,
            protected_resource_authorization_servers=prm_authorization_servers,
            protected_resource_scopes_supported=prm_scopes_supported,
            authorization_metadata_issuer=str(as_metadata.get("issuer", "")),
            authorization_endpoint=str(as_metadata.get("authorization_endpoint", "")),
            token_endpoint=str(as_metadata.get("token_endpoint", "")),
            registration_endpoint=str(as_metadata.get("registration_endpoint", "")),
            code_challenge_methods_supported=tuple(
                str(item) for item in as_metadata.get("code_challenge_methods_supported", [])
            ),
            authorization_request_state_present=bool(request.get("state")),
            authorization_request_code_challenge_present=bool(request.get("code_challenge")),
            authorization_request_code_challenge_method=str(request.get("code_challenge_method", "")),
            authorization_request_resource=str(request.get("resource", "")),
            authorization_request_scopes=tuple(sorted(str(request.get("scope", "")).split())),
            authorization_response_issuer=str(response.get("iss", "")),
            registration_count=provider.registration_count,
            authorization_count=provider.authorization_count,
            token_exchange_count=provider.token_exchange_count,
            introspection_count=provider.introspection_count,
            introspection_last_issuer=str(introspection.get("iss", "")),
            introspection_last_resource=str(introspection.get("aud", "")),
            introspection_last_scopes=tuple(
                sorted(str(introspection.get("scope", "")).split())
            ),
            reused_stored_authorization=reused_stored_authorization,
            valid_tool_names=valid_tool_names,
            valid_call_text=valid_call_text,
            reconnect_call_text=reconnect_call_text,
            receipt=receipt,
        )

    def _receipt_for_observation(
        self,
        *,
        protocol_version: str,
        issuer_url: str,
        resource_url: str,
        metadata_url: str,
        as_metadata: Mapping[str, Any],
        prm: Mapping[str, Any],
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        introspection: Mapping[str, Any],
        valid_tool_names: tuple[str, ...],
        valid_call_text: tuple[str, ...],
        reconnect_call_text: tuple[str, ...],
        counts_after_first: tuple[int, int, int],
        counts_after_second: tuple[int, int, int],
        introspection_count: int,
        observation_json: str,
    ) -> MCPOAuthFlowReceipt | None:
        if protocol_version != _PROTOCOL_VERSION:
            return None
        if str(as_metadata.get("issuer", "")) != issuer_url:
            return None
        if str(as_metadata.get("authorization_endpoint", "")) != f"{issuer_url}/authorize":
            return None
        if str(as_metadata.get("token_endpoint", "")) != f"{issuer_url}/token":
            return None
        if str(as_metadata.get("registration_endpoint", "")) != f"{issuer_url}/register":
            return None
        if tuple(as_metadata.get("code_challenge_methods_supported", [])) != ("S256",):
            return None
        if str(prm.get("resource", "")) != resource_url:
            return None
        if tuple(str(value) for value in prm.get("authorization_servers", [])) != (issuer_url,):
            return None
        if tuple(sorted(str(value) for value in prm.get("scopes_supported", []))) != (
            self._policy.required_scopes
        ):
            return None
        if not request.get("state") or not request.get("code_challenge"):
            return None
        if request.get("code_challenge_method") != "S256":
            return None
        if request.get("resource") != resource_url:
            return None
        if tuple(sorted(str(request.get("scope", "")).split())) != self._policy.required_scopes:
            return None
        if response.get("iss") != issuer_url:
            return None
        if introspection.get("active") is not True:
            return None
        if introspection.get("iss") != issuer_url or introspection.get("aud") != resource_url:
            return None
        if tuple(sorted(str(introspection.get("scope", "")).split())) != (
            self._policy.required_scopes
        ):
            return None
        if valid_tool_names != (self._policy.tool_name,):
            return None
        if valid_call_text != (f"oauth:{_SUBJECT}:hello",):
            return None
        if reconnect_call_text != (f"oauth:{_SUBJECT}:again",):
            return None
        if counts_after_first != (1, 1, 1) or counts_after_second != counts_after_first:
            return None
        if introspection_count < 3:
            return None
        expected_metadata_url = (
            f"http://127.0.0.1:{urlsplit(resource_url).port}"
            f"/.well-known/oauth-protected-resource{self._policy.resource_path}"
        )
        if metadata_url != expected_metadata_url:
            return None
        return MCPOAuthFlowReceipt.create(
            policy=self._policy,
            protocol_version=protocol_version,
            observation_json=observation_json,
        )


def _authorization_server_app(
    *,
    provider: _AuthorizationServerProvider,
    issuer_url: str,
    required_scopes: tuple[str, ...],
    introspection_client_id: str,
    introspection_client_secret: str,
) -> Any:
    from mcp.server.auth.routes import create_auth_routes
    from mcp.server.auth.settings import ClientRegistrationOptions
    from pydantic import AnyHttpUrl
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def introspect(request: Any) -> Any:
        expected = _basic_authorization(introspection_client_id, introspection_client_secret)
        if request.headers.get("authorization") != expected:
            return JSONResponse(
                {"active": False},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="agent-evals-introspection"'},
            )
        body = (await request.body()).decode()
        token = parse_qs(body).get("token", [""])[0]
        return JSONResponse(provider.introspect(token))

    routes = create_auth_routes(
        provider=provider,
        issuer_url=AnyHttpUrl(issuer_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=list(required_scopes),
            default_scopes=list(required_scopes),
        ),
    )
    routes.append(Route("/introspect", endpoint=introspect, methods=["POST"]))
    return Starlette(routes=routes)


@asynccontextmanager
async def _oauth_transport(url: str, http: Any) -> AsyncIterator[Any]:
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(
        url,
        http_client=http,
        terminate_on_close=False,
    ) as streams:
        yield streams


def _basic_authorization(client_id: str, client_secret: str) -> str:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {encoded}"


def _single_query_value(query: Mapping[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    if len(values) != 1:
        return ""
    return values[0]


def _opaque_fixture_value(domain: str, identity: str, sequence: int) -> str:
    return hashlib.sha256(f"agent-evals:{domain}:{identity}:{sequence}".encode()).hexdigest()


def _text_content(content: list[Any]) -> tuple[str, ...]:
    return tuple(
        text for block in content if isinstance((text := getattr(block, "text", None)), str)
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
