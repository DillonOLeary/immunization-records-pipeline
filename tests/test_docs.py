"""The docs point at things that exist.

Every path in ARCHITECTURE.md's layout tree, and every relative link in
the markdown files, must resolve. Docs drift when nothing checks them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "ARCHITECTURE.md", "ONBOARDING.md", "CLAUDE.md", "infra/README.md"]


def layout_paths() -> list[str]:
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    block = text.split("## Layout", 1)[1].split("```", 2)[1]
    paths, stack = [], []  # stack of (indent, path)
    for line in block.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        name = line.split()[0]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = (stack[-1][1] if stack else "") + name
        paths.append(path)
        if name.endswith("/"):
            stack.append((indent, path))
    return paths


def test_every_path_in_the_layout_exists():
    paths = layout_paths()
    assert len(paths) > 10
    missing = [p for p in paths if not (ROOT / p).exists()]
    assert not missing, f"ARCHITECTURE.md layout names missing paths: {missing}"


def test_every_relative_link_resolves():
    broken = []
    for doc in DOCS:
        path = ROOT / doc
        for target in re.findall(r"\]\(([^)#\s]+)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (path.parent / target).exists():
                broken.append(f"{doc} -> {target}")
    assert not broken, f"broken links: {broken}"
