"""Verify the exact GitHub-signed Dependabot + trusted-lock-publisher chain.

This module runs from accepted main. It never executes code from a pull request
or an artifact; the derived lock graph is parsed by existing strict validators.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from dependency_governance import (
    GitHubApi, PolicyBlock, _repo_text_at_sha, validate_pyproject_dependency_semantics,
)
from dependency_lock_publisher import (
    COMMIT_MESSAGE, expected_paths, validate_artifacts,
)

PUBLISHER_LOGIN = "github-actions[bot]"
PUBLISHER_USER_ID = 41898282
PUBLISHER_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
SHA = re.compile(r"[0-9a-f]{40}")


def validate_published_pip_chain(
    api: GitHubApi,
    pull: dict[str, Any],
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
    base_sha: str,
    head_sha: str,
    config: dict[str, Any],
) -> None:
    expected_locks = set(expected_paths().values())
    allowed_paths = {"pyproject.toml"} | {p for p, _ in expected_locks}
    names = {str(row.get("filename") or "") for row in files}
    if (
        len(commits) != 2 or pull.get("commits") != 2
        or not str((pull.get("head") or {}).get("ref") or "").startswith("dependabot/pip/")
        or names - allowed_paths or "pyproject.toml" not in names
    ):
        raise PolicyBlock("only exact signed bot source + trusted derived lock chain can qualify")
    source_sha = str(commits[0].get("sha") or "")
    child_sha = str(commits[1].get("sha") or "")
    if (
        SHA.fullmatch(source_sha) is None
        or SHA.fullmatch(child_sha) is None
        or child_sha != head_sha
    ):
        raise PolicyBlock("published lock chain source/head SHA is invalid")
    source = api.get(f"/commits/{source_sha}")
    child = api.get(f"/commits/{child_sha}")
    if (
        not isinstance(source, dict)
        or {row.get("filename") for row in (source.get("files") or [])} != {"pyproject.toml"}
        or len(source.get("parents") or []) != 1
        or (source["parents"][0] or {}).get("sha") != base_sha
    ):
        raise PolicyBlock("canonical Dependabot source must change only the manifest on current main")
    # The main governor already independently checks the first bot commit's
    # verified signature, author, committer, Signed-off-by, and update classes.
    git = child.get("commit") or {}
    git_author = git.get("author") or {}
    git_committer = git.get("committer") or {}
    verification = git.get("verification") or {}
    actor = child.get("author") or {}
    committer = child.get("committer") or {}
    expected_message = (
        f"{COMMIT_MESSAGE}\n\n"
        f"Generated from Dependabot source head {source_sha} by trusted default-branch "
        "dependency-lock-publisher."
    )
    if (
        actor.get("login") != PUBLISHER_LOGIN
        or actor.get("id") != PUBLISHER_USER_ID
        or committer.get("login") != "web-flow"
        or git_author.get("name") != PUBLISHER_LOGIN
        or git_author.get("email") != PUBLISHER_EMAIL
        or git_committer.get("name") != "GitHub"
        or git_committer.get("email") != "noreply@github.com"
        or verification.get("verified") is not True
        or verification.get("reason") != "valid"
        or not verification.get("signature")
        or len(child.get("parents") or []) != 1
        or (child.get("parents") or [{}])[0].get("sha") != source_sha
        or git.get("message") != expected_message
    ):
        raise PolicyBlock("derived lock commit lacks canonical GitHub Actions publisher identity")
    child_paths = {str(row.get("filename") or "") for row in (child.get("files") or [])}
    if not child_paths or not child_paths.issubset({path for path, _ in expected_locks}):
        raise PolicyBlock("trusted publisher changed non-lock paths or no lock data")
    for row in files:
        if row.get("status") != "modified":
            raise PolicyBlock("published bot PR cannot add/delete/rename source or lock paths")

    source_manifest = _repo_text_at_sha(api, "pyproject.toml", source_sha)
    head_manifest = _repo_text_at_sha(api, "pyproject.toml", head_sha)
    if source_manifest != head_manifest:
        raise PolicyBlock("publisher tampered with signed Dependabot source manifest")
    base_manifest = _repo_text_at_sha(api, "pyproject.toml", base_sha)
    validate_pyproject_dependency_semantics(base_manifest, head_manifest)

    # Exact HEAD lock graph must satisfy both independently accepted validators.
    # No files from PR are imported or executed.
    with tempfile.TemporaryDirectory(prefix="governed-bot-graph-") as directory:
        root = Path(directory)
        for stem, (path, _) in expected_paths().items():
            folder = root / f"lock-{stem}"
            folder.mkdir()
            (folder / f"{stem}.txt").write_text(
                _repo_text_at_sha(api, path, head_sha), encoding="utf-8"
            )
        try:
            validate_artifacts(root, head_manifest)
        except (ValueError, OSError, KeyError) as exc:
            raise PolicyBlock(f"published lock graph fails exact validated contract: {exc}") from exc
