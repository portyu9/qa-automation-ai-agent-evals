from __future__ import annotations

import socket

import pytest

import conftest as network_guard


class _MarkerNode:
    def __init__(self, markers: set[str]) -> None:
        self._markers = markers

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name in self._markers else None


def test_network_authority_classification_is_fail_closed() -> None:
    assert network_guard._network_mode(_MarkerNode(set())) == "deny"
    assert network_guard._network_mode(_MarkerNode({"network_loopback"})) == "loopback"
    assert network_guard._network_mode(_MarkerNode({"live"})) == "live"
    with pytest.raises(pytest.UsageError, match="mutually exclusive"):
        network_guard._network_mode(_MarkerNode({"live", "network_loopback"}))


def test_unmarked_ipv4_connect_is_denied_before_external_io() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(RuntimeError, match="unmarked tests have no IPv4/IPv6 authority"):
            client.connect(("203.0.113.1", 443))


def test_unmarked_listener_is_denied_even_on_loopback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        with pytest.raises(RuntimeError, match="unmarked tests have no IPv4/IPv6 authority"):
            listener.bind(("127.0.0.1", 0))


def test_unmarked_dns_resolution_is_denied() -> None:
    with pytest.raises(RuntimeError, match="no DNS/address-resolution authority"):
        socket.getaddrinfo("example.com", 443)


@pytest.mark.network_loopback
def test_loopback_marker_allows_ipv4_listener_and_denies_non_loopback_connect() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(RuntimeError, match="permits only literal loopback"):
            client.connect(("203.0.113.1", 443))


@pytest.mark.network_loopback
def test_loopback_marker_denies_hostname_resolution() -> None:
    with pytest.raises(RuntimeError, match="literal loopback address resolution"):
        socket.getaddrinfo("localhost", 443)


@pytest.mark.network_loopback
@pytest.mark.skipif(not socket.has_ipv6, reason="IPv6 unavailable")
def test_loopback_marker_allows_ipv6_and_denies_documentation_prefix() -> None:
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        listener.bind(("::1", 0))
        listener.listen()
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as client:
        with pytest.raises(RuntimeError, match="permits only literal loopback"):
            client.connect(("2001:db8::1", 443))


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="AF_UNIX unavailable")
def test_af_unix_ipc_remains_available(tmp_path) -> None:
    path = tmp_path / "local.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(path))
            accepted, _ = listener.accept()
            accepted.close()


def test_live_authority_allows_numeric_non_loopback_resolution_without_external_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(network_guard, "_NETWORK_MODE", "live")
    result = socket.getaddrinfo(
        "203.0.113.1",
        443,
        socket.AF_INET,
        socket.SOCK_STREAM,
        flags=socket.AI_NUMERICHOST,
    )
    assert result
