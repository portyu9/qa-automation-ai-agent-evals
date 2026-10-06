from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)(?:\s*;.*)?(?:\s*\\)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CompactLockError(ValueError):
    pass


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_pins(path: Path) -> tuple[list[str], dict[str, str]]:
    raw = path.read_text(encoding="utf-8")
    headers: list[str] = []
    pins: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("#"):
            headers.append(line)
            continue
        if not line or line[:1].isspace():
            continue
        match = PIN_RE.match(line)
        if match is None:
            raise CompactLockError(f"unexpected raw lock requirement line: {line!r}")
        name = canonical_name(match.group(1))
        if name in pins:
            raise CompactLockError(f"duplicate raw lock pin: {name}")
        pins[name] = match.group(2)
    if not pins:
        raise CompactLockError("raw lock contains no package pins")
    return headers, pins


def load_selected_hashes(path: Path) -> dict[str, tuple[str, str]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompactLockError(f"could not parse pip selection report: {exc}") from exc
    if type(report) is not dict or type(report.get("install")) is not list:
        raise CompactLockError("pip selection report must contain an install array")

    selected: dict[str, tuple[str, str]] = {}
    for item in report["install"]:
        if type(item) is not dict:
            raise CompactLockError("pip selection report install entries must be objects")
        metadata = item.get("metadata")
        download = item.get("download_info")
        if type(metadata) is not dict or type(download) is not dict:
            raise CompactLockError("pip selection report entry lacks metadata/download_info")
        name_value = metadata.get("name")
        version = metadata.get("version")
        archive = download.get("archive_info")
        if type(name_value) is not str or type(version) is not str or type(archive) is not dict:
            raise CompactLockError("pip selection report entry lacks package identity/archive info")
        hashes = archive.get("hashes")
        sha256 = hashes.get("sha256") if type(hashes) is dict else None
        if type(sha256) is not str or SHA256_RE.fullmatch(sha256) is None:
            raise CompactLockError(
                f"pip selection report lacks canonical SHA-256 for {name_value}=={version}"
            )
        name = canonical_name(name_value)
        if name in selected:
            raise CompactLockError(f"pip selection report duplicates package {name}")
        selected[name] = (version, sha256)
    return selected


def compact(raw_lock: Path, report_path: Path, output: Path) -> None:
    headers, pins = parse_pins(raw_lock)
    selected = load_selected_hashes(report_path)
    if set(selected) != set(pins):
        raise CompactLockError(
            "pip selection set does not match raw lock: "
            f"missing={sorted(set(pins) - set(selected))}, "
            f"extra={sorted(set(selected) - set(pins))}"
        )
    for name, version in pins.items():
        selected_version, _sha256 = selected[name]
        if selected_version != version:
            raise CompactLockError(
                f"selected version drift for {name}: {selected_version} != {version}"
            )

    filtered_headers = [
        line for line in headers if not line.startswith("# Artifact-Selection:")
    ]
    insertion = next(
        (
            index + 1
            for index, line in enumerate(filtered_headers)
            if line.startswith("# Python:")
        ),
        None,
    )
    if insertion is None:
        raise CompactLockError("raw lock lacks Python header")
    filtered_headers.insert(insertion, "# Artifact-Selection: linux-x86_64")

    lines = [*filtered_headers, ""]
    for name in sorted(pins):
        version, sha256 = selected[name]
        lines.append(f"{name}=={version} \\")
        lines.append(f"    --hash=sha256:{sha256}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"compacted {len(pins)} exact package pins for linux-x86_64 into {output}"
    )


def self_test() -> None:
    assert canonical_name("OpenAI_Agents") == "openai-agents"
    try:
        load_selected_hashes(Path("/definitely/missing"))
    except CompactLockError:
        pass
    else:
        raise AssertionError("missing report must fail closed")
    print("compact compatibility lock self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-lock", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if args.raw_lock is None or args.report is None or args.output is None:
            parser.error("--raw-lock, --report, and --output are required unless --self-test")
        compact(args.raw_lock, args.report, args.output)
    except CompactLockError as exc:
        raise SystemExit(f"compact compatibility lock failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
