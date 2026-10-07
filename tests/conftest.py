from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest


class NetworkIsolationError(RuntimeError):
    """Raised when a test exceeds its declared pytest network authority."""


_NETWORK_MODE = "deny"
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_BIND = socket.socket.bind
_ORIGINAL_LISTEN = socket.socket.listen
_ORIGINAL_SEND = socket.socket.send
_ORIGINAL_SENDALL = socket.socket.sendall
_ORIGINAL_SENDTO = socket.socket.sendto
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_ORIGINAL_GETHOSTBYADDR = socket.gethostbyaddr
_ORIGINAL_GETNAMEINFO = socket.getnameinfo
_ORIGINAL_SENDMSG = getattr(socket.socket, "sendmsg", None)


def _network_mode(node: pytest.Node) -> str:
    live = node.get_closest_marker("live") is not None
    loopback = node.get_closest_marker("network_loopback") is not None
    if live and loopback:
        raise pytest.UsageError(\n            "live and network_loopback are mutually exclusive network authorities"\n        )
    if live:
        return "live"
    if loopback:
        return "loopback"
    return "deny"


def _host_text(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        return value
    return None


def _is_loopback_host(value: object) -> bool:
    host = _host_text(value)
    if not host:
        return False
    host = host.split("%", 1)[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guard_inet_address(*, family: int, address: object, operation: str) -> None:
    if family not in (socket.AF_INET, socket.AF_INET6) or _NETWORK_MODE == "live":
        return
    if _NETWORK_MODE == "deny":
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: unmarked tests have no IPv4/IPv6 authority"
        )
    if not isinstance(address, tuple) or not address or not _is_loopback_host(address[0]):
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: "
            "network_loopback permits only literal loopback IPv4/IPv6 addresses"
        )


def _guard_connected_socket(sock: socket.socket, *, operation: str) -> None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6) or _NETWORK_MODE == "live":
        return
    if _NETWORK_MODE == "deny":
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: unmarked tests have no IPv4/IPv6 authority"
        )
    try:
        peer = sock.getpeername()
    except OSError as exc:
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: loopback socket has no verified peer"
        ) from exc
    _guard_inet_address(family=sock.family, address=peer, operation=operation)


def _guard_name_resolution(*, host: object, operation: str) -> None:
    if _NETWORK_MODE == "live":
        return
    if _NETWORK_MODE == "deny":
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: "
            "unmarked tests have no DNS/address-resolution authority"
        )
    if not _is_loopback_host(host):
        raise NetworkIsolationError(
            f"network isolation blocked {operation}: "
            "network_loopback permits only literal loopback address resolution"
        )


def _guarded_connect(sock: socket.socket, address: object) -> None:
    _guard_inet_address(family=sock.family, address=address, operation="connect")
    _ORIGINAL_CONNECT(sock, address)  # type: ignore[arg-type]


def _guarded_connect_ex(sock: socket.socket, address: object) -> int:
    _guard_inet_address(family=sock.family, address=address, operation="connect_ex")
    return _ORIGINAL_CONNECT_EX(sock, address)  # type: ignore[arg-type]


def _guarded_bind(sock: socket.socket, address: object) -> None:
    _guard_inet_address(family=sock.family, address=address, operation="bind")
    _ORIGINAL_BIND(sock, address)  # type: ignore[arg-type]


def _guarded_listen(sock: socket.socket, *args: Any) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6) and _NETWORK_MODE != "live":
        if _NETWORK_MODE == "deny":
            raise NetworkIsolationError(
                "network isolation blocked listen: unmarked tests have no IPv4/IPv6 authority"
            )
        _guard_inet_address(
            family=sock.family,
            address=sock.getsockname(),
            operation="listen",
        )
    _ORIGINAL_LISTEN(sock, *args)


def _guarded_send(sock: socket.socket, data: Any, *args: Any) -> int:
    _guard_connected_socket(sock, operation="send")
    return _ORIGINAL_SEND(sock, data, *args)


def _guarded_sendall(sock: socket.socket, data: Any, *args: Any) -> None:
    _guard_connected_socket(sock, operation="sendall")
    _ORIGINAL_SENDALL(sock, data, *args)


def _guarded_sendto(sock: socket.socket, data: Any, *args: Any) -> int:
    if not args:
        raise TypeError("sendto expected an address")
    _guard_inet_address(family=sock.family, address=args[-1], operation="sendto")
    return _ORIGINAL_SENDTO(sock, data, *args)


def _guarded_getaddrinfo(host: object, *args: Any, **kwargs: Any) -> list[Any]:
    _guard_name_resolution(host=host, operation="getaddrinfo")
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]


def _guarded_gethostbyname(host: str) -> str:
    _guard_name_resolution(host=host, operation="gethostbyname")
    return _ORIGINAL_GETHOSTBYNAME(host)


def _guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
    _guard_name_resolution(host=host, operation="gethostbyname_ex")
    return _ORIGINAL_GETHOSTBYNAME_EX(host)


def _guarded_gethostbyaddr(host: str) -> tuple[str, list[str], list[str]]:
    _guard_name_resolution(host=host, operation="gethostbyaddr")
    return _ORIGINAL_GETHOSTBYADDR(host)


def _guarded_getnameinfo(sockaddr: tuple[Any, ...], flags: int) -> tuple[str, str]:
    host = sockaddr[0] if sockaddr else None
    _guard_name_resolution(host=host, operation="getnameinfo")
    return _ORIGINAL_GETNAMEINFO(sockaddr, flags)


def _guarded_sendmsg(sock: socket.socket, *args: Any, **kwargs: Any) -> int:
    if _ORIGINAL_SENDMSG is None:
        raise AttributeError("sendmsg unavailable")
    address = kwargs.get("address")
    if address is None and len(args) >= 4:
        address = args[3]
    if address is not None:
        _guard_inet_address(family=sock.family, address=address, operation="sendmsg")
    else:
        _guard_connected_socket(sock, operation="sendmsg")
    return _ORIGINAL_SENDMSG(sock, *args, **kwargs)


def pytest_configure(config: pytest.Config) -> None:
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.socket.bind = _guarded_bind
    socket.socket.listen = _guarded_listen
    socket.socket.send = _guarded_send
    socket.socket.sendall = _guarded_sendall
    socket.socket.sendto = _guarded_sendto
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.gethostbyname = _guarded_gethostbyname
    socket.gethostbyname_ex = _guarded_gethostbyname_ex
    socket.gethostbyaddr = _guarded_gethostbyaddr
    socket.getnameinfo = _guarded_getnameinfo
    if _ORIGINAL_SENDMSG is not None:
        socket.socket.sendmsg = _guarded_sendmsg


def pytest_unconfigure(config: pytest.Config) -> None:
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX
    socket.socket.bind = _ORIGINAL_BIND
    socket.socket.listen = _ORIGINAL_LISTEN
    socket.socket.send = _ORIGINAL_SEND
    socket.socket.sendall = _ORIGINAL_SENDALL
    socket.socket.sendto = _ORIGINAL_SENDTO
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO
    socket.gethostbyname = _ORIGINAL_GETHOSTBYNAME
    socket.gethostbyname_ex = _ORIGINAL_GETHOSTBYNAME_EX
    socket.gethostbyaddr = _ORIGINAL_GETHOSTBYADDR
    socket.getnameinfo = _ORIGINAL_GETNAMEINFO
    if _ORIGINAL_SENDMSG is not None:
        socket.socket.sendmsg = _ORIGINAL_SENDMSG


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Any:
    global _NETWORK_MODE
    previous = _NETWORK_MODE
    _NETWORK_MODE = _network_mode(item)
    try:
        yield
    finally:
        _NETWORK_MODE = previous


def pytest_make_parametrize_id(
    config: pytest.Config,
    val: object,
    argname: str,
) -> str | None:
    """Keep pytest ID generation from invoking hostile string-subclass overrides."""

    if isinstance(val, str) and type(val) is not str:
        return f"{type(val).__name__}-{argname}"
    return None
