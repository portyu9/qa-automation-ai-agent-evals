#!/usr/bin/env python3
"""Fail-closed, default-branch-only publisher for verified Dependabot pip lock outputs.

The untrusted PR matrix has no write token. This privileged entrypoint runs only
from accepted main, revalidates canonical Dependabot provenance, parses artifacts
as data, exercises both existing lock validators and binds the exact source SHA
into one GitHub-signed publisher child commit. Never executes artifact contents.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import validate_ci_locks as snapshot_policy
import validate_dependency_compatibility as compatibility_policy
from dependency_governance import (
    GitHubApi,
    GovernanceError,
    PolicyBlock,
    assess,
    load_config,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_NAME = "dependency-locks"
WORKFLOW_PATH = ".github/workflows/dependency-locks.yml"
COMMIT_MESSAGE = "chore: publish trusted Dependabot dependency lock graph"
# GitHub Dependabot will not rebase a bot PR after a trusted publisher adds
# commits unless those derived commits explicitly opt in to replacement.
DEPENDABOT_REBASE_MARKER = "[dependabot skip]"
MAX_LOCK_BYTES = 4 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")
SAFE_BRANCH = re.compile(r"dependabot/pip/[A-Za-z0-9._/-]+")


def publisher_commit_message(source: str) -> str:
    """Bind a verified bot source to a discardable, narrowly trusted lock child."""
    if SHA.fullmatch(source) is None:
        raise GovernanceError("lock publisher commit subject must be a canonical SHA")
    return (
        f"{COMMIT_MESSAGE}\\n\\n"
        f"Generated from Dependabot source head {source} by trusted default-branch "
        f"dependency-lock-publisher.\\n\\n{DEPENDABOT_REBASE_MARKER}"
    )


def expected_paths() -> dict[str, tuple[str, str]]:
    """Reuse the trusted validator profile sets, avoiding a duplicated allowlist."""
    snapshots = {
        name.removesuffix(".txt"): (f"requirements/locks/{name}", py)
        for name, (py, _) in snapshot_policy.EXPECTED.items()
    }
    compatibility = {
        name.removesuffix(".txt"): (f"requirements/compatibility/{name}", py)
        for name, (_, _, py, _) in compatibility_policy.EXPECTED.items()
    }
    if set(snapshots) & set(compatibility):
        raise GovernanceError("lock profile identities overlap")
    return {**snapshots, **compatibility}


def git_blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


def require_sha(value: Any, reason: str) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise GovernanceError(f"{reason} is not a canonical commit or blob SHA")
    return value


def validate_run(api: GitHubApi, event: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    run = event.get("workflow_run") or {}
    associations = run.get("pull_requests") or []
    if (
        run.get("name") != WORKFLOW_NAME
        or run.get("path") != WORKFLOW_PATH
        or run.get("event") != "pull_request"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or (run.get("head_repository") or {}).get("full_name") != api.repository
        or len(associations) != 1
        or not isinstance(associations[0].get("number"), int)
    ):
        raise GovernanceError(
            "lock publisher requires one successful canonical read-only PR workflow"
        )
    number = associations[0]["number"]
    pull = api.get(f"/pulls/{number}")
    if not isinstance(pull, dict):
        raise GovernanceError("could not reload lock source PR")
    head = pull.get("head") or {}
    branch = str(head.get("ref") or "")
    if (
        SAFE_BRANCH.fullmatch(branch) is None
        or (head.get("repo") or {}).get("full_name") != api.repository
        or run.get("head_branch") != branch
        or run.get("head_sha") != head.get("sha")
    ):
        raise GovernanceError("read-only lock workflow run does not bind the current Dependabot PR")
    config = load_config()
    source = assess(api, pull, config, require_checks=False)
    if source["ecosystem"] != "pip" or source["files"] != ["pyproject.toml"]:
        raise GovernanceError(
            "lock publisher only accepts canonical signed pyproject-only Dependabot source"
        )
    return pull, require_sha(source["headSha"], "source head"), branch


def validate_artifacts(
    root: Path, source_manifest: str, trusted_project_root: Path = ROOT
) -> dict[str, bytes]:
    expected = expected_paths()
    if not root.is_dir() or root.is_symlink():
        raise GovernanceError("lock artifact root must be a real directory")
    observed = {p.name for p in root.iterdir()}
    if observed != {f"lock-{stem}" for stem in expected}:
        raise GovernanceError(f"incomplete/unexpected lock artifacts: {sorted(observed)}")
    payloads: dict[str, bytes] = {}
    for stem, (destination, python) in expected.items():
        folder = root / f"lock-{stem}"
        file = folder / f"{stem}.txt"
        if (
            not folder.is_dir()
            or folder.is_symlink()
            or [p.name for p in folder.iterdir()] != [file.name]
            or not file.is_file()
            or file.is_symlink()
        ):
            raise GovernanceError(f"unsafe or incomplete lock artifact: {stem}")
        size = file.stat().st_size
        if size < 100 or size > MAX_LOCK_BYTES:
            raise GovernanceError(f"lock artifact {stem} exceeds expected size envelope")
        data = file.read_bytes()
        if len(data) != size:
            raise GovernanceError(f"lock artifact {stem} changed during inspection")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GovernanceError(f"lock artifact {stem} is not UTF-8") from exc
        if (
            "\x00" in text
            or f"# Python: {python}" not in text.splitlines()[:12]
            or "# Compiler: pip==25.3; pip-tools==7.5.2" not in text.splitlines()[:12]
            or "--hash=sha256:" not in text
        ):
            raise GovernanceError(f"lock {stem} is not a valid pinned compiler output")
        payloads[destination] = data

    # Exercise existing strict integrity/range/lock-graph validators on data
    # staged into an isolated tree. No untrusted source files are executed.
    with tempfile.TemporaryDirectory(prefix="validated-lock-graph-") as directory:
        tmp = Path(directory)
        (tmp / "pyproject.toml").write_text(source_manifest, encoding="utf-8")
        (tmp / "requirements-dev-ci-build.txt").write_bytes(
            (trusted_project_root / "requirements-dev-ci-build.txt").read_bytes()
        )
        for destination, data in payloads.items():
            file = tmp / destination
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        old_snapshot_root, old_snapshot_dir = snapshot_policy.ROOT, snapshot_policy.LOCK_DIR
        old_compat_root, old_compat_dir = compatibility_policy.ROOT, compatibility_policy.LOCK_DIR
        try:
            snapshot_policy.ROOT = tmp
            snapshot_policy.LOCK_DIR = tmp / "requirements" / "locks"
            compatibility_policy.ROOT = tmp
            compatibility_policy.LOCK_DIR = tmp / "requirements" / "compatibility"
            snapshot_policy.validate()
            compatibility_policy.validate()
        finally:
            snapshot_policy.ROOT, snapshot_policy.LOCK_DIR = old_snapshot_root, old_snapshot_dir
            compatibility_policy.ROOT, compatibility_policy.LOCK_DIR = (
                old_compat_root,
                old_compat_dir,
            )
    return payloads


def publish(
    api: GitHubApi, pull: dict[str, Any], source: str, branch: str, files: dict[str, bytes]
) -> str:
    # Revalidate after expensive artifact processing; do not repair stale heads
    # or an unrelated PR, and never force-update a Dependabot branch.
    fresh = api.get(f"/pulls/{pull['number']}")
    if fresh.get("state") != "open" or (fresh.get("head") or {}).get("sha") != source:
        raise GovernanceError("Dependabot head moved during lock compilation")
    if (fresh.get("base") or {}).get("sha") != (pull.get("base") or {}).get("sha"):
        raise GovernanceError("trusted base changed during lock compilation")
    source_commit = api.get(f"/git/commits/{source}")
    tree_sha = require_sha((source_commit.get("tree") or {}).get("sha"), "source tree")
    entries = []
    for path, data in sorted(files.items()):
        blob = api.post(
            "/git/blobs",
            {
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            },
        )
        entries.append(
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": require_sha((blob or {}).get("sha"), f"blob {path}"),
            }
        )
    tree = api.post("/git/trees", {"base_tree": tree_sha, "tree": entries})
    new_tree = require_sha((tree or {}).get("sha"), "published tree")
    message = publisher_commit_message(source)
    commit = api.post(
        "/git/commits",
        {
            "message": message,
            "tree": new_tree,
            "parents": [source],
        },
    )
    commit_sha = require_sha((commit or {}).get("sha"), "publisher child")
    if SAFE_BRANCH.fullmatch(branch) is None:
        raise GovernanceError("invalid Dependabot branch identity")
    ref_path = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")
    ref = api.get(ref_path)
    if ((ref or {}).get("object") or {}).get("sha") != source:
        raise GovernanceError("branch ref changed before lock publisher publication")
    # GitHub Actions creates the signed child, but only the authenticated
    # repository owner advances the ref so required pull_request checks rerun.
    owner = os.environ.get("DEPENDABOT_OWNER_TOKEN", "")
    if not owner:
        raise GovernanceError("owner-authorized publication token is not configured")
    identity = api.request("GET", "https://api.github.com/user", token=owner)
    trusted = load_config()
    if (
        identity.get("login") != trusted["ownerApprovalLogin"]
        or identity.get("id") != trusted["ownerApprovalUserId"]
    ):
        raise GovernanceError("publisher ref update token is not the configured owner identity")
    latest_ref = api.get(ref_path)
    if ((latest_ref or {}).get("object") or {}).get("sha") != source:
        raise GovernanceError("Dependabot ref changed before owner-authorized publication")
    api.request("PATCH", ref_path, {"sha": commit_sha, "force": False}, token=owner)
    return commit_sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert len(expected_paths()) == 12
        assert len(set(expected_paths().values())) == 12
        assert SHA.fullmatch("a" * 40)
        assert SAFE_BRANCH.fullmatch("dependabot/pip/test-123")
        assert SAFE_BRANCH.fullmatch("../evil") is None
        print("dependency lock publisher integrity self-test passed")
        return 0
    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    if not event_path.is_file():
        raise GovernanceError("trusted GitHub workflow-run event is absent")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    config = load_config()
    if repository != config["repository"]:
        raise GovernanceError("publisher repository does not match accepted policy")
    api = GitHubApi(os.environ.get("GITHUB_TOKEN", ""), repository)
    pull, source, branch = validate_run(api, event)
    # Source bytes are read only after exact verified bot provenance.
    from dependency_governance import _repo_text_at_sha

    source_manifest = _repo_text_at_sha(api, "pyproject.toml", source)
    files = validate_artifacts(args.artifact_root, source_manifest)
    new_sha = publish(api, pull, source, branch, files)
    print(
        json.dumps(
            {"pr": pull["number"], "source": source, "child": new_sha, "profiles": len(files)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GovernanceError, PolicyBlock, ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"trusted lock publisher refused unqualified update: {exc}") from None
