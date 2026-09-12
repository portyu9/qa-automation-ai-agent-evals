from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_SCHEMA = "agent-evals/package-artifact-manifest/v1"
_MANIFEST_NAME = "artifact-manifest.json"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ManifestError(ValueError):
    """Package artifact manifest is malformed or does not match retained bytes."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> object:
    raise ManifestError(f"non-finite JSON number is not allowed: {value}")


def _artifact_files(dist_dir: Path) -> tuple[Path, Path]:
    wheels = sorted(path for path in dist_dir.glob("*.whl") if path.is_file())
    sdists = sorted(path for path in dist_dir.glob("*.tar.gz") if path.is_file())
    if len(wheels) != 1:
        raise ManifestError(f"expected exactly one wheel, found {len(wheels)}")
    if len(sdists) != 1:
        raise ManifestError(f"expected exactly one sdist, found {len(sdists)}")
    return wheels[0], sdists[0]


def _context(
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    if type(repository) is not str or _REPOSITORY_RE.fullmatch(repository) is None:
        raise ManifestError("repository must be canonical owner/name text")
    if type(commit_sha) is not str or _SHA40_RE.fullmatch(commit_sha) is None:
        raise ManifestError("commit_sha must be a lowercase 40-character Git SHA")
    if (
        type(workflow) is not str
        or not workflow
        or workflow != workflow.strip()
        or len(workflow) > 256
    ):
        raise ManifestError("workflow must be non-empty trimmed text <= 256 characters")
    if type(run_id) is not int or run_id < 1:
        raise ManifestError("run_id must be an integer >= 1")
    if type(run_attempt) is not int or run_attempt < 1:
        raise ManifestError("run_attempt must be an integer >= 1")
    return {
        "repository": repository,
        "commit_sha": commit_sha,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


def create_manifest(
    dist_dir: Path,
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> Path:
    wheel, sdist = _artifact_files(dist_dir)
    source = _context(
        repository=repository,
        commit_sha=commit_sha,
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    artifacts = []
    for kind, path in (("sdist", sdist), ("wheel", wheel)):
        artifacts.append(
            {
                "filename": path.name,
                "kind": kind,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": _SCHEMA,
        "source": source,
        "artifacts": sorted(artifacts, key=lambda item: str(item["filename"])),
    }
    output = dist_dir / _MANIFEST_NAME
    output.write_bytes(_canonical_bytes(manifest))
    return output


def _require_exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ManifestError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is not valid UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ManifestError("manifest root must be an object")
    if raw != _canonical_bytes(value):
        raise ManifestError("manifest JSON is not canonical")
    return value


def verify_manifest(
    dist_dir: Path,
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> None:
    manifest_path = dist_dir / _MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ManifestError(f"missing or non-regular {_MANIFEST_NAME}")
    manifest = _load_manifest(manifest_path)
    _require_exact_keys(manifest, {"schema_version", "source", "artifacts"}, label="manifest")
    if manifest["schema_version"] != _SCHEMA:
        raise ManifestError("unsupported manifest schema_version")

    source = manifest["source"]
    if type(source) is not dict:
        raise ManifestError("manifest source must be an object")
    _require_exact_keys(
        source,
        {"repository", "commit_sha", "workflow", "run_id", "run_attempt"},
        label="source",
    )
    parsed_source = _context(
        repository=source["repository"],
        commit_sha=source["commit_sha"],
        workflow=source["workflow"],
        run_id=source["run_id"],
        run_attempt=source["run_attempt"],
    )
    expected_source = _context(
        repository=repository,
        commit_sha=commit_sha,
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    for field in ("repository", "commit_sha", "workflow", "run_id"):
        if parsed_source[field] != expected_source[field]:
            raise ManifestError("manifest source context does not match expected CI context")
    if parsed_source["run_attempt"] > expected_source["run_attempt"]:
        raise ManifestError("manifest producing run attempt cannot be newer than verifier attempt")

    artifacts = manifest["artifacts"]
    if type(artifacts) is not list or len(artifacts) != 2:
        raise ManifestError("manifest artifacts must contain exactly one wheel and one sdist")
    seen_names: set[str] = set()
    seen_kinds: set[str] = set()
    ordered_names: list[str] = []
    expected_files: set[str] = {_MANIFEST_NAME}
    for item in artifacts:
        if type(item) is not dict:
            raise ManifestError("artifact entry must be an object")
        _require_exact_keys(item, {"filename", "kind", "sha256", "size_bytes"}, label="artifact")
        filename = item["filename"]
        kind = item["kind"]
        digest = item["sha256"]
        size = item["size_bytes"]
        if (
            type(filename) is not str
            or not filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
        ):
            raise ManifestError("artifact filename must be a non-empty basename")
        if filename in seen_names:
            raise ManifestError("manifest contains duplicate artifact filenames")
        seen_names.add(filename)
        ordered_names.append(filename)
        if type(kind) is not str or kind not in {"wheel", "sdist"}:
            raise ManifestError("artifact kind must be wheel or sdist")
        if kind in seen_kinds:
            raise ManifestError("manifest contains duplicate artifact kinds")
        seen_kinds.add(kind)
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ManifestError("artifact sha256 must be a lowercase SHA-256 digest")
        if type(size) is not int or size < 0:
            raise ManifestError("artifact size_bytes must be an integer >= 0")
        path = dist_dir / filename
        if not path.is_file() or path.is_symlink():
            raise ManifestError(f"manifest artifact is missing or non-regular: {filename}")
        if path.stat().st_size != size:
            raise ManifestError(f"artifact size mismatch: {filename}")
        if _sha256(path) != digest:
            raise ManifestError(f"artifact digest mismatch: {filename}")
        if kind == "wheel" and not filename.endswith(".whl"):
            raise ManifestError("wheel artifact filename must end with .whl")
        if kind == "sdist" and not filename.endswith(".tar.gz"):
            raise ManifestError("sdist artifact filename must end with .tar.gz")
        expected_files.add(filename)

    if seen_kinds != {"wheel", "sdist"}:
        raise ManifestError("manifest must contain exactly one wheel and one sdist")
    if ordered_names != sorted(ordered_names):
        raise ManifestError("manifest artifact entries must be sorted by filename")
    entries = list(dist_dir.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in entries):
        raise ManifestError("retained artifact directory must contain regular files only")
    actual_files = {path.name for path in entries}
    if actual_files != expected_files:
        raise ManifestError(
            f"retained artifact set mismatch: unexpected={sorted(actual_files - expected_files)}, "
            f"missing={sorted(expected_files - actual_files)}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.mode == "create":
            path = create_manifest(
                args.dist_dir,
                repository=args.repository,
                commit_sha=args.commit_sha,
                workflow=args.workflow,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            )
            print(path)
        else:
            verify_manifest(
                args.dist_dir,
                repository=args.repository,
                commit_sha=args.commit_sha,
                workflow=args.workflow,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            )
            print(f"verified {args.dist_dir / _MANIFEST_NAME}")
    except (ManifestError, OSError) as exc:
        raise SystemExit(f"package artifact manifest failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
