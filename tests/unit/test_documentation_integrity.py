from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _REPO_ROOT / "docs"
_DOCS_HUB = _DOCS_DIR / "README.md"

_INLINE_TARGET = re.compile(
    r"\[[^\]\n]*\]\((?P<target><[^>\n]+>|[^)\n]+)\)"
)
_REFERENCE_TARGET = re.compile(
    r"(?m)^[ \t]*\[[^\]\n]+\]:[ \t]*(?P<target><[^>\n]+>|[^ \t\n]+)"
)
_HTML_TARGET = re.compile(
    r'''(?i)\b(?:href|src)=["'](?P<target>[^"']+)["']'''
)
_FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")


def _without_fenced_code(text: str) -> str:
    """Blank fenced-code lines while preserving line numbers for diagnostics."""

    rendered: list[str] = []
    fence_char: str | None = None
    fence_width = 0

    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence_char is None:
            if match is None:
                rendered.append(line)
                continue

            token = match.group("fence")
            fence_char = token[0]
            fence_width = len(token)
            rendered.append("\n" if line.endswith("\n") else "")
            continue

        if match is not None:
            token = match.group("fence")
            if token[0] == fence_char and len(token) >= fence_width:
                fence_char = None
                fence_width = 0
        rendered.append("\n" if line.endswith("\n") else "")

    return "".join(rendered)


def _markdown_targets(source: Path) -> Iterator[tuple[str, int]]:
    text = _without_fenced_code(source.read_text(encoding="utf-8"))
    matches = [
        match
        for pattern in (_INLINE_TARGET, _REFERENCE_TARGET, _HTML_TARGET)
        for match in pattern.finditer(text)
    ]

    for match in sorted(matches, key=lambda item: item.start()):
        line = text.count("\n", 0, match.start()) + 1
        yield match.group("target"), line


def _repository_local_path(raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<"):
        closing = target.find(">")
        if closing < 0:
            return None
        target = target[1:closing]
    else:
        target = target.split(maxsplit=1)[0]

    if not target or target.startswith(("#", "/", "//")):
        return None

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None

    path = unquote(parsed.path)
    return Path(path) if path else None


def _markdown_files() -> tuple[Path, ...]:
    return (_REPO_ROOT / "README.md", *sorted(_DOCS_DIR.glob("*.md")))


def test_repository_local_markdown_links_resolve() -> None:
    broken: list[str] = []

    for source in _markdown_files():
        for raw_target, line in _markdown_targets(source):
            relative_target = _repository_local_path(raw_target)
            if relative_target is None:
                continue

            resolved = (source.parent / relative_target).resolve()
            try:
                rendered_target = resolved.relative_to(_REPO_ROOT)
            except ValueError:
                broken.append(
                    f"{source.relative_to(_REPO_ROOT)}:{line}: "
                    f"repository-local link escapes the checkout: {raw_target!r}"
                )
                continue

            if not resolved.exists():
                broken.append(
                    f"{source.relative_to(_REPO_ROOT)}:{line}: "
                    f"{raw_target!r} -> {rendered_target} does not exist"
                )

    assert not broken, "broken repository-local Markdown links:\n" + "\n".join(broken)


def test_docs_hub_links_every_authoritative_document() -> None:
    expected = {path.resolve() for path in _DOCS_DIR.glob("*.md") if path != _DOCS_HUB}
    linked: set[Path] = set()

    for raw_target, _line in _markdown_targets(_DOCS_HUB):
        relative_target = _repository_local_path(raw_target)
        if relative_target is None:
            continue

        resolved = (_DOCS_HUB.parent / relative_target).resolve()
        if resolved.parent == _DOCS_DIR.resolve() and resolved.suffix.lower() == ".md":
            linked.add(resolved)

    missing = sorted(path.name for path in expected - linked)
    assert not missing, (
        "docs/README.md must link every authoritative Markdown document; missing: "
        + ", ".join(missing)
    )
