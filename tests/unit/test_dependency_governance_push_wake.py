"""Native bot recovery must wake from an accepted protected-main push.

This test is an exact-source regression barrier, not a replacement for the
repository's independent runtime policy, signed Dependabot head, or CI checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/dependency-governance.yml"
TRIGGER = """  push:
    branches: [main]
  schedule:
    - cron: '17 * * * *'"""
JOB_GUARD = (
    "    if: github.event_name != 'pull_request' && "
    "(github.event_name != 'push' || "
    "(github.ref == 'refs/heads/main' && "
    "github.event.repository.default_branch == 'main'))"
)
PUSH_GUARD = """      - name: Authorize only exact-current-main native push wake
        if: github.event_name == 'push'
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          set -euo pipefail
          test "$GITHUB_REF" = "refs/heads/main"
          test "$GITHUB_WORKFLOW_REF" = "$GITHUB_REPOSITORY/.github/workflows/dependency-governance.yml@refs/heads/main"
          live_main="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)"
          test "$live_main" = "$GITHUB_SHA"
"""
MERGE_ADMISSION = "            schedule|workflow_dispatch|push) args+=(--allow-merge) ;;"


def require_exact_source(source: str) -> None:
    for fragment in (TRIGGER, JOB_GUARD, PUSH_GUARD, MERGE_ADMISSION):
        if source.count(fragment) != 1:
            raise ValueError("native push wake authority drifted")
    guard = source.index("      - name: Authorize only exact-current-main native push wake")
    checkout = source.index("      - name: Checkout trusted default-branch governance code only")
    token_use = source.index("          DEPENDABOT_OWNER_TOKEN: ${{ secrets.DEPENDABOT_OWNER_TOKEN }}")
    if not (guard < checkout < token_use):
        raise ValueError("native main guard must precede source or secret authority")
    if "pull_request_target:" in source or "workflow_run:" in source:
        raise ValueError("unreviewed privileged event trigger")
    if source.count("          DEPENDABOT_OWNER_TOKEN: ${{ secrets.DEPENDABOT_OWNER_TOKEN }}") != 1:
        raise ValueError("owner token minting unexpectedly expanded")


def test_accepted_trusted_main_push_wake() -> None:
    require_exact_source(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("    branches: [main]", "    branches: ['*']"),
        ("        if: github.event_name == 'push'", "        if: always()"),
        ('test "$GITHUB_REF" = "refs/heads/main"', 'test "$GITHUB_REF" != "refs/heads/main"'),
        ('test "$live_main" = "$GITHUB_SHA"', 'test "$live_main" != "$GITHUB_SHA"'),
        ("/dependency-governance.yml@refs/heads/main",
         "/dependency-governance.yml@refs/heads/candidate"),
        ("            schedule|workflow_dispatch|push) args+=(--allow-merge) ;;",
         "            schedule|workflow_dispatch) args+=(--allow-merge) ;;"),
    ],
)
def test_unreviewed_push_wake_mutation_is_rejected(before: str, after: str) -> None:
    trusted = WORKFLOW.read_text(encoding="utf-8")
    assert before in trusted
    with pytest.raises(ValueError, match="authority drifted"):
        require_exact_source(trusted.replace(before, after, 1))
