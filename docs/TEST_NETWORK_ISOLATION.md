# Pytest network isolation

The deterministic pytest process fails closed for IPv4 and IPv6 networking unless a test declares an explicit network authority marker.

## Authority classes

Unmarked tests have no IPv4/IPv6 authority. The root pytest guard blocks connect/connect_ex, bind/listen, connected sends, datagram sends, and Python socket name/address resolution before the operation reaches the network stack.

`network_loopback` is the only deterministic networking authority. It permits literal loopback IPv4/IPv6 addresses only (`127.0.0.0/8` and `::1`). Hostname resolution is deliberately unavailable in this mode, including `localhost`, so DNS or resolver behavior cannot widen the granted destination set. The real-TCP MCP remote-auth and OAuth laboratories carry this marker in addition to their existing protocol-specific markers.

`live` is the only pytest classification that removes the Python socket guard and therefore permits non-loopback networking. Ordinary pytest selection explicitly excludes `live`; provider canaries remain separately governed and must not be relabeled as deterministic evidence.

The two authorities are mutually exclusive. A test carrying both `live` and `network_loopback` is a configuration error.

AF_UNIX/local Unix-domain IPC is outside the IPv4/IPv6 authority boundary and remains available.

## What this establishes

The guard is installed for the pytest process before test protocols execute and remains fail-closed outside a test's declared authority. Self-tests cover default denial, loopback IPv4/IPv6 allowance, non-loopback denial, hostname-resolution denial, live authority without external I/O, and AF_UNIX preservation.

## Non-claims

This is pytest-process policy, not an OS/container firewall, network namespace, eBPF policy, seccomp sandbox, provider attestation, or proof of host isolation. A subprocess, native extension, raw syscall, or deliberately hostile code that bypasses Python's patched `socket` surface is outside this guarantee unless separately sandboxed. Loopback permission is destination authority only; it is not authentication, confidentiality, target identity, or production-network fidelity.
