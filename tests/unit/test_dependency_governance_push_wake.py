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
  workflow_run: # zizmor: ignore[dangerous-triggers] -- exact current-main publisher ID verified before trusted checkout or owner-token access
    workflows: ["Trusted CodeQL PR-head publication"]
    types: [completed]
    branches: [main]
  schedule:
    # Follow the trusted CodeQL publisher on a separate 10-minute phase;
    # never grant privileged PR-head execution or bypass current-main checks.
    - cron: '2,12,22,32,42,52 * * * *'"""
JOB_GUARD = """    if: >-
      github.event_name != 'pull_request' &&
      (github.event_name != 'push' ||
       (github.ref == 'refs/heads/main' && github.event.repository.default_branch == 'main')) &&
      (github.event_name != 'workflow_run' ||
       (github.event.workflow_run.conclusion == 'success' &&
        github.event.workflow_run.head_repository.full_name == github.repository &&
        github.event.workflow_run.head_branch == 'main' &&
        github.event.workflow_run.head_sha == github.sha))"""
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
PUBLISHER_GUARD = """      - name: Authenticate exact-current-main trusted publisher completion
        if: github.event_name == 'workflow_run'
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          set -euo pipefail
          test "$GITHUB_REF" = "refs/heads/main"
          test "$GITHUB_WORKFLOW_REF" = "$GITHUB_REPOSITORY/.github/workflows/dependency-governance.yml@refs/heads/main"
          live_main="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)"
          test "$live_main" = "$GITHUB_SHA"
          publisher_id="$(gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/codeql-pr-publisher.yml" --jq .id)"
          [[ "$publisher_id" =~ ^[1-9][0-9]*$ ]]
          publisher_run="$(jq -er '.workflow_run.id' "$GITHUB_EVENT_PATH")"
          [[ "$publisher_run" =~ ^[1-9][0-9]*$ ]]
          # The webhook is only a wake signal: independently verify its
          # original GitHub record, never trust a PR artifact or run title.
          gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${publisher_run}" |
            jq -e --argjson publisher_id "$publisher_id" --arg main "$live_main" \\
              --arg repo "$GITHUB_REPOSITORY" '
              .workflow_id == $publisher_id and
              .name == "Trusted CodeQL PR-head publication" and
              .status == "completed" and .conclusion == "success" and
              .head_branch == "main" and .head_sha == $main and
              .repository.full_name == $repo and
              (.event == "workflow_run" or .event == "push" or
               .event == "schedule" or .event == "workflow_dispatch")
              ' >/dev/null
"""
MERGE_ADMISSION = "            schedule|workflow_dispatch|push|workflow_run) args+=(--allow-merge) ;;"


def require_exact_source(source: str) -> None:
    for fragment in (TRIGGER, JOB_GUARD, PUSH_GUARD, PUBLISHER_GUARD, MERGE_ADMISSION):
        if source.count(fragment) != 1:
            raise ValueError("native push wake authority drifted")
    guard = source.index("      - name: Authorize only exact-current-main native push wake")
    publisher_guard = source.index("      - name: Authenticate exact-current-main trusted publisher completion")
    checkout = source.index("      - name: Checkout trusted default-branch governance code only")
    token_use = source.index(
        "          DEPENDABOT_OWNER_TOKEN: ${{ secrets.DEPENDABOT_OWNER_TOKEN }}"
    )
    if not (guard < publisher_guard < checkout < token_use):
        raise ValueError("native main guard must precede source or secret authority")
    if "pull_request_target:" in source or source.count("  workflow_run:") != 1:
        raise ValueError("unreviewed privileged event trigger")
    if source.count("          DEPENDABOT_OWNER_TOKEN: ${{ secrets.DEPENDABOT_OWNER_TOKEN }}") != 1:
        raise ValueError("owner token minting unexpectedly expanded")


def test_accepted_trusted_main_push_wake() -> None:
    require_exact_source(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("    branches: [main]", "    branches: ['*']"),
        ("    - cron: '2,12,22,32,42,52 * * * *'", "    - cron: '17 * * * *'"),
        ("    - cron: '2,12,22,32,42,52 * * * *'", "    - cron: '* * * * *'"),
        (
            '    workflows: ["Trusted CodeQL PR-head publication"]',
            '    workflows: ["CodeQL"]',
        ),
        (".workflow_id == $publisher_id", ".workflow_id != $publisher_id"),
        (
            ".head_branch == \"main\" and .head_sha == $main",
            ".head_branch == \"main\" and .head_sha != $main",
        ),
        (
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.conclusion != 'success'",
        ),
        ("        if: github.event_name == 'push'", "        if: always()"),
        ('test "$GITHUB_REF" = "refs/heads/main"', 'test "$GITHUB_REF" != "refs/heads/main"'),
        ('test "$live_main" = "$GITHUB_SHA"', 'test "$live_main" != "$GITHUB_SHA"'),
        (
            "/dependency-governance.yml@refs/heads/main",
            "/dependency-governance.yml@refs/heads/candidate",
        ),
        (
            "            schedule|workflow_dispatch|push|workflow_run) args+=(--allow-merge) ;;",
            "            schedule|workflow_dispatch) args+=(--allow-merge) ;;",
        ),
    ],
)
def test_unreviewed_push_wake_mutation_is_rejected(before: str, after: str) -> None:
    trusted = WORKFLOW.read_text(encoding="utf-8")
    assert before in trusted
    with pytest.raises(ValueError, match="authority drifted"):
        require_exact_source(trusted.replace(before, after, 1))
