#!/usr/bin/env python3
"""Audit classified repository Markdown links."""

import re
import subprocess
import sys
from pathlib import Path


MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def broken_markdown_links(paths):
    broken = []
    for path in map(Path, paths):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for match in MARKDOWN_LINK.finditer(line):
                target = match.group(1).strip()
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                relative_target = target.split("#", 1)[0]
                if relative_target and not (path.parent / relative_target).exists():
                    broken.append(f"{path}:{line_number}: {target}")
    return broken


def repository_markdown_paths(repository_root):
    root = Path(repository_root).resolve()
    result = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    relative_paths = result.stdout.decode("utf-8").split("\0")
    return [root / relative for relative in relative_paths if relative]


def main():
    repository_root = Path(__file__).resolve().parents[3]
    broken = broken_markdown_links(repository_markdown_paths(repository_root))
    if broken:
        print("\n".join(broken))
        return 1
    print("Markdown link audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
