from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
from email.message import Message

import pytest
from pydantic import ValidationError

import agent_evals.mcp.advanced as advanced
from agent_evals.mcp.advanced import (
    MCPHostedEndpointSpec,
    MCPRemoteCondition,
)
from agent_evals.mcp.oauth_advanced import (
    OAuthAdvancedPolicy,
    OAuthAdvancedReceipt,
    OAuthAuthorizationDriftReceipt,
    OAuthAuthorizationEpoch,
    OAuthKeySetSnapshot,
    OAuthSenderBinding,
    OAuthSessionEvent,
    OAuthSessionEventKind,
)


class _FakeResponse:
    def __init__(self, raw: bytes, *, status: int = 200) -> None:
        self.raw = raw
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> bool:
        return False

    def read(self, _: int) -> bytes:
        return self.raw


class _FakeOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def open(self, request: object, *, timeout: float) -> _FakeResponse:
        del request, timeout
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if not isinstance(self.outcome, _FakeResponse):
            raise TypeError("invalid fake opener outcome")
        return self.outcome


def _endpoint(**overrides: object) -> MCPHostedEndpointSpec:
    values: dict[str, object] = {
        "endpoint_id": "hosted.boundary",
        "url": "https://mcp.example.test/rpc",
        "expected_server_identity": "remote-mcp",
        "max_latency_ms": 500,
    }
    values.update(overrides)
    return MCPHostedEndpointSpec.model_validate(values)


def _probe(
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
    *,
    endpoint: MCPHostedEndpointSpec | None = None,
    elapsed_ms: int = 20,
) -> advanced.MCPRemoteProbeObservation:
    monkeypatch.setattr(
        advanced.urllib.request,
        "build_opener",
        lambda *handlers: _FakeOpener(outcome),
    )
    monkeypatch.setattr(advanced, "_elapsed_ms", lambda _: elapsed_ms)
    return advanced.probe_hosted_mcp_endpoint(endpoint or _endpoint())


def _healthy_payload(
    *,
    response_id: int = 1,
    server_name: str | None = "remote-mcp",
) -> bytes:
    if server_name is None:
        return (
            b'{"jsonrpc":"2.0","id":'
            + str(response_id).encode()
            + b',"result":{"serverInfo":{}}}'
        )
    return (
        b'{"jsonrpc":"2.0","id":'
        + str(response_id).encode()
        + b',"result":{"serverInfo":{"name":"'
        + server_name.encode()
        + b'"}}}'
    )


def _http_error(code: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://mcp.example.test/rpc",
        code,
        "synthetic",
        headers,
        None,
    )


def test_hosted_probe_success_and_response_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = _probe(monkeypatch, _FakeResponse(_healthy_payload()))
    assert healthy.condition is MCPRemoteCondition.HEALTHY
    assert healthy.protocol_valid is True
    assert healthy.observed_server_identity == "remote-mcp"

    oversized_endpoint = _endpoint(max_response_bytes=8)
    oversized = _probe(
        monkeypatch,
        _FakeResponse(b"x" * 9),
        endpoint=oversized_endpoint,
    )
    assert oversized.condition is MCPRemoteCondition.OVERSIZED_RESPONSE
    assert oversized.error_code == "response-too-large"

    frames_endpoint = _endpoint(max_stream_frames=1)
    frames = _probe(
        monkeypatch,
        _FakeResponse(b"one\n\ntwo\n\n"),
        endpoint=frames_endpoint,
    )
    assert frames.condition is MCPRemoteCondition.RESOURCE_PRESSURE
    assert frames.error_code == "stream-frame-limit"

    slow = _probe(
        monkeypatch,
        _FakeResponse(_healthy_payload()),
        elapsed_ms=501,
    )
    assert slow.condition is MCPRemoteCondition.LATENCY_LIMIT
    assert slow.error_code == "latency-limit"


def test_hosted_probe_rejects_malformed_initialize_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_json = _probe(monkeypatch, _FakeResponse(b"{not-json"))
    assert invalid_json.condition is MCPRemoteCondition.PROTOCOL_TRICKERY
    assert invalid_json.error_code == "invalid-json"

    wrong_id = _probe(
        monkeypatch,
        _FakeResponse(_healthy_payload(response_id=9)),
    )
    assert wrong_id.condition is MCPRemoteCondition.PROTOCOL_TRICKERY
    assert wrong_id.error_code == "invalid-initialize-response"

    no_server = _probe(
        monkeypatch,
        _FakeResponse(_healthy_payload(server_name=None)),
    )
    assert no_server.condition is MCPRemoteCondition.PROTOCOL_TRICKERY
    assert no_server.error_code == "invalid-initialize-response"


@pytest.mark.parametrize(
    ("error", "condition", "status"),
    (
        (_http_error(429, retry_after="2"), MCPRemoteCondition.RATE_LIMIT, 429),
        (_http_error(503), MCPRemoteCondition.GATEWAY_FAILURE, 503),
        (_http_error(400), MCPRemoteCondition.PROTOCOL_TRICKERY, 400),
    ),
)
def test_hosted_probe_classifies_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: urllib.error.HTTPError,
    condition: MCPRemoteCondition,
    status: int,
) -> None:
    observation = _probe(monkeypatch, error)
    assert observation.condition is condition
    assert observation.http_status == status
    if status == 429:
        assert observation.retry_after_ms == 2_000


@pytest.mark.parametrize(
    ("reason", "condition", "dns_resolved"),
    (
        (ssl.SSLError("tls"), MCPRemoteCondition.TLS_FAILURE, True),
        (socket.gaierror(1, "dns"), MCPRemoteCondition.DNS_FAILURE, False),
        (TimeoutError("timeout"), MCPRemoteCondition.HANG_TIMEOUT, True),
        (OSError("disconnect"), MCPRemoteCondition.DISCONNECT, True),
    ),
)
def test_hosted_probe_classifies_url_errors(
    monkeypatch: pytest.MonkeyPatch,
    reason: BaseException,
    condition: MCPRemoteCondition,
    dns_resolved: bool,
) -> None:
    observation = _probe(monkeypatch, urllib.error.URLError(reason))
    assert observation.condition is condition
    assert observation.dns_resolved is dns_resolved


def test_hosted_probe_classifies_proxy_stream_reset_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _probe(
        monkeypatch,
        urllib.error.URLError(OSError("proxy")),
        endpoint=_endpoint(proxy_url="https://proxy.example.test"),
    )
    assert proxy.condition is MCPRemoteCondition.PROXY_FAILURE

    interrupted = _probe(
        monkeypatch,
        http.client.IncompleteRead(b"partial", 100),
    )
    assert interrupted.condition is MCPRemoteCondition.STREAM_INTERRUPTION

    reset = _probe(monkeypatch, ConnectionResetError("reset"))
    assert reset.condition is MCPRemoteCondition.DISCONNECT

    timed_out = _probe(monkeypatch, TimeoutError("timeout"))
    assert timed_out.condition is MCPRemoteCondition.HANG_TIMEOUT


def test_hosted_probe_helpers_and_exact_type_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert advanced._stream_frame_count(b"") == 0
    assert advanced._stream_frame_count(b"single") == 1
    assert advanced._parse_retry_after_ms(None) is None
    assert advanced._parse_retry_after_ms("not-an-int") is None
    assert advanced._parse_retry_after_ms("-1") is None
    assert advanced._parse_retry_after_ms("999999") == 86_400_000

    class EndpointSubclass(MCPHostedEndpointSpec):
        pass

    subclass = EndpointSubclass.model_validate(_endpoint().model_dump(mode="json"))
    with pytest.raises(ValueError, match="exact MCPHostedEndpointSpec"):
        advanced.probe_hosted_mcp_endpoint(subclass)

    monkeypatch.setattr(
        advanced.urllib.request,
        "build_opener",
        lambda *handlers: _FakeOpener(_FakeResponse(_healthy_payload())),
    )


def _keyset(
    *,
    epoch: int = 0,
    kid: str = "kid-a",
    issuer: str = "https://idp.example.test",
) -> OAuthKeySetSnapshot:
    return OAuthKeySetSnapshot(
        issuer=issuer,
        jwks_uri=f"{issuer}/jwks",
        key_ids=(kid,),
        epoch=epoch,
        verifier_revision="1",
    )


def _event(
    *,
    event_id: str = "event.initial",
    kind: OAuthSessionEventKind = OAuthSessionEventKind.INITIAL,
    epoch: int = 0,
    token: str = "token-a",
    kid: str = "kid-a",
    issuer: str = "https://idp.example.test",
    accepted: bool = True,
    sender_binding: OAuthSenderBinding = OAuthSenderBinding.DPOP,
    sender_key: str | None = "sender-key",
    sender_verified: bool = True,
    signature_verified: bool = True,
    parent: str | None = None,
) -> OAuthSessionEvent:
    return OAuthSessionEvent(
        event_id=event_id,
        kind=kind,
        epoch=epoch,
        issuer=issuer,
        subject="subject",
        audience="https://api.example.test",
        token_sha256=advanced.hashlib.sha256(token.encode()).hexdigest(),
        jti_sha256=advanced.hashlib.sha256(f"jti:{event_id}".encode()).hexdigest(),
        signing_kid=kid,
        scopes=frozenset({"read"}),
        sender_binding=sender_binding,
        sender_key_sha256=(
            None if sender_key is None else advanced.hashlib.sha256(sender_key.encode()).hexdigest()
        ),
        sender_binding_verified=sender_verified,
        jwt_signature_verified=signature_verified,
        accepted_by_resource=accepted,
        parent_token_sha256=(
            None if parent is None else advanced.hashlib.sha256(parent.encode()).hexdigest()
        ),
    )


def test_oauth_contract_validators_reject_ambiguous_or_unverified_material() -> None:
    with pytest.raises(ValidationError, match="trimmed"):
        OAuthKeySetSnapshot(
            issuer="https://idp.example.test",
            jwks_uri="https://idp.example.test/jwks",
            key_ids=(" kid-a",),
            epoch=0,
            verifier_revision="1",
        )
    with pytest.raises(ValidationError, match="unique"):
        OAuthKeySetSnapshot(
            issuer="https://idp.example.test",
            jwks_uri="https://idp.example.test/jwks",
            key_ids=("kid-a", "kid-a"),
            epoch=0,
            verifier_revision="1",
        )
    with pytest.raises(ValidationError, match="sender-key"):
        _event(sender_binding=OAuthSenderBinding.BEARER, sender_key="unexpected", sender_verified=False)
    with pytest.raises(ValidationError, match="cannot claim"):
        _event(sender_binding=OAuthSenderBinding.BEARER, sender_key=None, sender_verified=True)
    with pytest.raises(ValidationError, match="sender-key fingerprint"):
        _event(sender_key=None)
    with pytest.raises(ValidationError, match="sender-binding verification"):
        _event(sender_verified=False)
    with pytest.raises(ValidationError, match="parent token"):
        _event(kind=OAuthSessionEventKind.REFRESH)
    with pytest.raises(ValidationError, match="cannot carry parent"):
        _event(parent="parent")
    with pytest.raises(ValidationError, match="must not be accepted"):
        _event(kind=OAuthSessionEventKind.REPLAY, accepted=True)
    with pytest.raises(ValidationError, match="trimmed"):
        OAuthAdvancedPolicy(allowed_issuers=frozenset({" https://idp.example.test"}))
    with pytest.raises(ValidationError, match="at least one binding"):
        OAuthAdvancedPolicy(
            allowed_issuers=frozenset({"https://idp.example.test"}),
            allowed_sender_bindings=frozenset(),
        )


def test_oauth_receipt_rejects_wrong_issuer_kid_signature_and_bad_sequences() -> None:
    policy = OAuthAdvancedPolicy(
        allowed_issuers=frozenset({"https://idp.example.test"}),
        require_key_rotation=False,
        require_refresh=False,
        require_revocation_rejection=False,
        require_replay_rejection=False,
        require_sender_constraint=False,
    )
    bearer = _event(
        sender_binding=OAuthSenderBinding.BEARER,
        sender_key=None,
        sender_verified=False,
    )
    receipt = OAuthAdvancedReceipt.create(
        policy=policy,
        keysets=(_keyset(),),
        events=(bearer,),
    )
    assert receipt.accepted is True
    assert receipt.key_rotation_observed is False
    assert receipt.refresh_observed is False
    assert receipt.sender_constraint_observed is False

    with pytest.raises(ValueError, match="issuer outside policy"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(issuer="https://other.example.test"),),
            events=(
                _event(
                    issuer="https://other.example.test",
                    sender_binding=OAuthSenderBinding.BEARER,
                    sender_key=None,
                    sender_verified=False,
                ),
            ),
        )
    with pytest.raises(ValueError, match="signing kid"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(),),
            events=(
                _event(
                    kid="unknown",
                    sender_binding=OAuthSenderBinding.BEARER,
                    sender_key=None,
                    sender_verified=False,
                ),
            ),
        )
    with pytest.raises(ValueError, match="signature verification"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(),),
            events=(
                _event(
                    signature_verified=False,
                    sender_binding=OAuthSenderBinding.BEARER,
                    sender_key=None,
                    sender_verified=False,
                ),
            ),
        )
    with pytest.raises(ValueError, match="keyset epochs"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(epoch=1), _keyset(epoch=0, kid="kid-b")),
            events=(bearer,),
        )
    with pytest.raises(ValueError, match="event IDs"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(),),
            events=(bearer, bearer),
        )
    with pytest.raises(ValueError, match="ordered by epoch"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=(_keyset(),),
            events=(
                _event(
                    event_id="event.late",
                    epoch=2,
                    sender_binding=OAuthSenderBinding.BEARER,
                    sender_key=None,
                    sender_verified=False,
                ),
                _event(
                    event_id="event.early",
                    epoch=1,
                    token="token-b",
                    sender_binding=OAuthSenderBinding.BEARER,
                    sender_key=None,
                    sender_verified=False,
                ),
            ),
        )


def test_oauth_receipt_rejects_unknown_refresh_revoke_replay_and_revoked_request() -> None:
    policy = OAuthAdvancedPolicy(
        allowed_issuers=frozenset({"https://idp.example.test"}),
        require_key_rotation=False,
        require_refresh=False,
        require_revocation_rejection=False,
        require_replay_rejection=False,
        require_sender_constraint=False,
    )
    keysets = (_keyset(),)

    with pytest.raises(ValueError, match="refresh parent"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=keysets,
            events=(
                _event(
                    event_id="event.refresh",
                    kind=OAuthSessionEventKind.REFRESH,
                    token="token-b",
                    parent="unknown-parent",
                ),
            ),
        )
    with pytest.raises(ValueError, match="revocation"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=keysets,
            events=(
                _event(
                    event_id="event.revoke",
                    kind=OAuthSessionEventKind.REVOKE,
                    token="unknown",
                    accepted=False,
                ),
            ),
        )
    with pytest.raises(ValueError, match="replay"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=keysets,
            events=(
                _event(
                    event_id="event.replay",
                    kind=OAuthSessionEventKind.REPLAY,
                    token="unknown",
                    accepted=False,
                ),
            ),
        )

    initial = _event()
    revoke = _event(
        event_id="event.revoke",
        kind=OAuthSessionEventKind.REVOKE,
        epoch=1,
        accepted=False,
    )
    request = _event(
        event_id="event.request",
        kind=OAuthSessionEventKind.REQUEST,
        epoch=2,
    )
    with pytest.raises(ValueError, match="revoked OAuth token"):
        OAuthAdvancedReceipt.create(
            policy=policy,
            keysets=keysets,
            events=(initial, revoke, request),
        )


def test_oauth_authorization_drift_rejects_bad_epochs_and_cross_target_evidence() -> None:
    first = OAuthAuthorizationEpoch(
        epoch=0,
        scopes=frozenset({"read", "write"}),
        resource_identity="tenant/7",
        operation="write",
        allowed=True,
    )
    with pytest.raises(ValueError, match="unique and increasing"):
        OAuthAuthorizationDriftReceipt.create((first, first))

    later = OAuthAuthorizationEpoch(
        epoch=1,
        scopes=frozenset({"read"}),
        resource_identity="tenant/7",
        operation="read",
        allowed=False,
    )
    with pytest.raises(ValueError, match="one resource and operation"):
        OAuthAuthorizationDriftReceipt.create((first, later))
