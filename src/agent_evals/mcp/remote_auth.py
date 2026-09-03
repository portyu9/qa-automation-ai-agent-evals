"""Deterministic remote Streamable HTTP authorization laboratory for MCP resource servers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PROTOCOL_VERSION = "2026-07-28"
_POLICY_SCHEMA: Literal["agent-evals/mcp-remote-auth-policy/v1"] = (
    "agent-evals/mcp-remote-auth-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/mcp-remote-auth-receipt/v1"] = (
    "agent-evals/mcp-remote-auth-receipt/v1"
)
_TRANSPORT: Literal["streamable-http-loopback"] = "streamable-http-loopback"


class MCPRemoteAuthPolicy(BaseModel):
    """Content-addressed resource-server policy exercised over real loopback HTTP."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-remote-auth-policy/v1"] = _POLICY_SCHEMA
    lab_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    revision: str = Field(min_length=1, max_length=128)
    issuer_url: str = Field(min_length=1, max_length=2048)
    resource_path: str = Field(default="/mcp", min_length=1, max_length=256)
    required_scopes: tuple[str, ...]
    tool_name: str = Field(min_length=1, max_length=128)

    @field_validator("issuer_url")
    @classmethod
    def validate_issuer_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("MCP remote-auth issuer_url must be an absolute HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "MCP remote-auth issuer_url must not contain userinfo, query, or fragment"
            )
        return value

    @field_validator("resource_path")
    @classmethod
    def validate_resource_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("MCP remote-auth resource_path must be one absolute path")
        if "?" in value or "#" in value:
            raise ValueError("MCP remote-auth resource_path must not contain query or fragment")
        return value

    @field_validator("required_scopes")
    @classmethod
    def validate_required_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("MCP remote-auth required_scopes must not be empty")
        for scope in value:
            if not scope.strip() or scope != scope.strip():
                raise ValueError(
                    "MCP remote-auth scopes must be non-empty without surrounding whitespace"
                )
        if len(set(value)) != len(value):
            raise ValueError("MCP remote-auth required_scopes must not contain duplicates")
        return tuple(sorted(value))

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError(
                "MCP remote-auth tool_name must be non-empty without surrounding whitespace"
            )
        return value

    @property
    def identity(self) -> str:
        return _sha256_json(
            {
                "schema_version": self.schema_version,
                "lab_id": self.lab_id,
                "revision": self.revision,
                "issuer_url": self.issuer_url,
                "resource_path": self.resource_path,
                "required_scopes": self.required_scopes,
                "tool_name": self.tool_name,
            }
        )


class MCPRemoteAuthReceipt(BaseModel):
    """Integrity-bound observation of one exact remote HTTP authorization matrix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-remote-auth-receipt/v1"] = _RECEIPT_SCHEMA
    policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    transport: Literal["streamable-http-loopback"] = _TRANSPORT
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: MCPRemoteAuthPolicy,
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
            raise ValueError("MCP remote-auth receipt root does not match receipt material")
        return self


class MCPRemoteAuthProbeResult(BaseModel):
    """HTTP and MCP observations produced by one remote authorization probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    transport: Literal["streamable-http-loopback"] = _TRANSPORT
    resource_url: str
    protected_resource_metadata_url: str
    missing_token_status: int
    invalid_token_status: int
    expired_token_status: int
    wrong_issuer_status: int
    wrong_resource_status: int
    insufficient_scope_status: int
    unauthorized_www_authenticate: str
    forbidden_www_authenticate: str
    metadata_resource: str
    metadata_authorization_servers: tuple[str, ...]
    metadata_scopes_supported: tuple[str, ...]
    valid_tool_names: tuple[str, ...]
    valid_call_text: tuple[str, ...]
    receipt: MCPRemoteAuthReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        if self.receipt is None:
            return self
        if self.receipt.policy_identity != self.policy_identity:
            raise ValueError("MCP remote-auth receipt policy identity does not match probe")
        if self.receipt.protocol_version != self.protocol_version:
            raise ValueError("MCP remote-auth receipt protocol version does not match probe")
        return self


@dataclass(frozen=True)
class _TokenRecord:
    issuer: str
    resource: str
    scopes: tuple[str, ...]
    expires_at: int | None = None


class _DeterministicTokenVerifier:
    """Verifier-owned exact issuer/resource binding for deterministic HTTP tests."""

    def __init__(
        self,
        *,
        expected_issuer: str,
        expected_resource: str,
        records: Mapping[str, _TokenRecord],
    ) -> None:
        self._expected_issuer = expected_issuer
        self._expected_resource = expected_resource
        self._records = records

    async def verify_token(self, token: str) -> Any:
        from mcp.server.auth.provider import AccessToken

        record = self._records.get(token)
        if record is None:
            return None
        if record.issuer != self._expected_issuer or record.resource != self._expected_resource:
            return None
        return AccessToken(
            token=token,
            client_id="agent-evals-client",
            scopes=list(record.scopes),
            expires_at=record.expires_at,
            resource=record.resource,
            subject="agent-evals-subject",
            claims={"iss": record.issuer},
        )


class MCPRemoteAuthLab:
    """Exercise MCP bearer authorization over a real loopback TCP Streamable HTTP server."""

    def __init__(self, policy: MCPRemoteAuthPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> MCPRemoteAuthPolicy:
        return self._policy

    async def probe(self) -> MCPRemoteAuthProbeResult:
        import httpx2
        from mcp import Client
        from mcp.server import MCPServer
        from mcp.server.auth.routes import build_resource_metadata_url
        from mcp.server.auth.settings import AuthSettings

        listener = _bind_loopback_socket()
        port = int(listener.getsockname()[1])
        resource_url = f"http://127.0.0.1:{port}{self._policy.resource_path}"
        verifier, tokens = _build_verifier(self._policy, resource_url)
        auth_settings = AuthSettings(
            issuer_url=self._policy.issuer_url,
            resource_server_url=resource_url,
            required_scopes=list(self._policy.required_scopes),
        )
        resource_server_url = auth_settings.resource_server_url
        if resource_server_url is None:  # pragma: no cover - required by policy construction
            raise RuntimeError("MCP remote-auth resource_server_url was unexpectedly absent")
        server = MCPServer(
            f"agent-evals-remote-auth:{self._policy.lab_id}",
            token_verifier=verifier,
            auth=auth_settings,
        )

        def protected_tool(message: str) -> str:
            """Return one deterministic value through the authenticated MCP path."""
            return f"authorized:{message}"

        server.add_tool(
            protected_tool,
            name=self._policy.tool_name,
            description="Protected deterministic MCP tool.",
            structured_output=False,
        )
        app = server.streamable_http_app(
            streamable_http_path=self._policy.resource_path,
            json_response=True,
            stateless_http=True,
            host="127.0.0.1",
        )
        metadata_url = str(build_resource_metadata_url(resource_server_url))

        try:
            async with _serve_prebound(app, listener):
                async with httpx2.AsyncClient(timeout=5.0) as http:
                    missing = await _protected_post(http, resource_url)
                    invalid = await _protected_post(http, resource_url, tokens["invalid"])
                    expired = await _protected_post(http, resource_url, tokens["expired"])
                    wrong_issuer = await _protected_post(http, resource_url, tokens["wrong_issuer"])
                    wrong_resource = await _protected_post(
                        http, resource_url, tokens["wrong_resource"]
                    )
                    insufficient = await _protected_post(
                        http, resource_url, tokens["insufficient_scope"]
                    )
                    metadata_response = await http.get(metadata_url)
                    metadata_response.raise_for_status()
                    metadata = metadata_response.json()

                transport = _authenticated_transport(resource_url, tokens["valid"])
                async with Client(
                    transport,
                    mode=_PROTOCOL_VERSION,
                    raise_exceptions=True,
                ) as client:
                    listed = await client.list_tools(cache_mode="refresh")
                    called = await client.call_tool(
                        self._policy.tool_name,
                        {"message": "hello"},
                    )
                    protocol_version = client.protocol_version
        finally:
            if listener.fileno() != -1:
                listener.close()

        valid_tool_names = tuple(sorted(tool.name for tool in listed.tools))
        valid_call_text = _text_content(called.content)
        metadata_resource = str(metadata.get("resource", ""))
        metadata_authorization_servers = tuple(
            str(value) for value in metadata.get("authorization_servers", [])
        )
        metadata_scopes_supported = tuple(
            sorted(str(value) for value in metadata.get("scopes_supported", []))
        )

        observation: dict[str, Any] = {
            "expired_token_status": expired.status_code,
            "forbidden_www_authenticate": insufficient.headers.get("www-authenticate", ""),
            "insufficient_scope_status": insufficient.status_code,
            "invalid_token_status": invalid.status_code,
            "metadata_authorization_servers": metadata_authorization_servers,
            "metadata_resource": metadata_resource,
            "metadata_scopes_supported": metadata_scopes_supported,
            "missing_token_status": missing.status_code,
            "protected_resource_metadata_url": metadata_url,
            "resource_url": resource_url,
            "transport": _TRANSPORT,
            "unauthorized_www_authenticate": missing.headers.get("www-authenticate", ""),
            "valid_call_text": valid_call_text,
            "valid_tool_names": valid_tool_names,
            "wrong_issuer_status": wrong_issuer.status_code,
            "wrong_resource_status": wrong_resource.status_code,
        }
        observation_json = _canonical_json(observation)
        receipt = self._receipt_for_observation(
            protocol_version=protocol_version,
            resource_url=resource_url,
            metadata_url=metadata_url,
            observation=observation,
            observation_json=observation_json,
        )
        return MCPRemoteAuthProbeResult(
            policy_identity=self._policy.identity,
            protocol_version=protocol_version,
            resource_url=resource_url,
            protected_resource_metadata_url=metadata_url,
            missing_token_status=missing.status_code,
            invalid_token_status=invalid.status_code,
            expired_token_status=expired.status_code,
            wrong_issuer_status=wrong_issuer.status_code,
            wrong_resource_status=wrong_resource.status_code,
            insufficient_scope_status=insufficient.status_code,
            unauthorized_www_authenticate=missing.headers.get("www-authenticate", ""),
            forbidden_www_authenticate=insufficient.headers.get("www-authenticate", ""),
            metadata_resource=metadata_resource,
            metadata_authorization_servers=metadata_authorization_servers,
            metadata_scopes_supported=metadata_scopes_supported,
            valid_tool_names=valid_tool_names,
            valid_call_text=valid_call_text,
            receipt=receipt,
        )

    def _receipt_for_observation(
        self,
        *,
        protocol_version: str,
        resource_url: str,
        metadata_url: str,
        observation: Mapping[str, Any],
        observation_json: str,
    ) -> MCPRemoteAuthReceipt | None:
        if protocol_version != _PROTOCOL_VERSION:
            return None
        if any(
            observation[key] != 401
            for key in (
                "missing_token_status",
                "invalid_token_status",
                "expired_token_status",
                "wrong_issuer_status",
                "wrong_resource_status",
            )
        ):
            return None
        if observation["insufficient_scope_status"] != 403:
            return None
        if observation["metadata_resource"] != resource_url:
            return None
        if observation["metadata_authorization_servers"] != (self._policy.issuer_url,):
            return None
        if observation["metadata_scopes_supported"] != self._policy.required_scopes:
            return None
        if observation["valid_tool_names"] != (self._policy.tool_name,):
            return None
        if observation["valid_call_text"] != ("authorized:hello",):
            return None
        unauthorized = str(observation["unauthorized_www_authenticate"])
        forbidden = str(observation["forbidden_www_authenticate"])
        if (
            'error="invalid_token"' not in unauthorized
            or f'resource_metadata="{metadata_url}"' not in unauthorized
        ):
            return None
        if (
            'error="insufficient_scope"' not in forbidden
            or f'resource_metadata="{metadata_url}"' not in forbidden
        ):
            return None
        return MCPRemoteAuthReceipt.create(
            policy=self._policy,
            protocol_version=protocol_version,
            observation_json=observation_json,
        )


def _build_verifier(
    policy: MCPRemoteAuthPolicy,
    resource_url: str,
) -> tuple[_DeterministicTokenVerifier, dict[str, str]]:
    valid = _token_value("valid")
    invalid = _token_value("invalid")
    expired = _token_value("expired")
    wrong_issuer = _token_value("wrong-issuer")
    wrong_resource = _token_value("wrong-resource")
    insufficient_scope = _token_value("insufficient-scope")
    records = {
        valid: _TokenRecord(policy.issuer_url, resource_url, policy.required_scopes),
        expired: _TokenRecord(
            policy.issuer_url,
            resource_url,
            policy.required_scopes,
            expires_at=1,
        ),
        wrong_issuer: _TokenRecord(
            "https://wrong-issuer.agent-evals.invalid",
            resource_url,
            policy.required_scopes,
        ),
        wrong_resource: _TokenRecord(
            policy.issuer_url,
            f"{resource_url}/other",
            policy.required_scopes,
        ),
        insufficient_scope: _TokenRecord(
            policy.issuer_url,
            resource_url,
            ("agent-evals.other",),
        ),
    }
    return (
        _DeterministicTokenVerifier(
            expected_issuer=policy.issuer_url,
            expected_resource=resource_url,
            records=records,
        ),
        {
            "valid": valid,
            "invalid": invalid,
            "expired": expired,
            "wrong_issuer": wrong_issuer,
            "wrong_resource": wrong_resource,
            "insufficient_scope": insufficient_scope,
        },
    )


def _bind_loopback_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    return listener


@asynccontextmanager
async def _serve_prebound(app: Any, listener: socket.socket) -> AsyncIterator[None]:
    import uvicorn

    port = int(listener.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(500):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("MCP remote-auth loopback server did not start")
        yield
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            server.force_exit = True
            await asyncio.wait_for(task, timeout=2.0)


@asynccontextmanager
async def _authenticated_transport(url: str, token: str) -> AsyncIterator[Any]:
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    async with (
        httpx2.AsyncClient(
            headers={"authorization": f"Bearer {token}"},
            timeout=5.0,
        ) as http,
        streamable_http_client(
            url,
            http_client=http,
            terminate_on_close=False,
        ) as streams,
    ):
        yield streams


async def _protected_post(http: Any, resource_url: str, token: str | None = None) -> Any:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return await http.post(resource_url, content=b"{}", headers=headers)


def _token_value(label: str) -> str:
    return hashlib.sha256(f"agent-evals-mcp-auth:{label}".encode()).hexdigest()


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
