import importlib.util
from pathlib import Path
import subprocess


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "code"
    / "python"
    / "scripts"
    / "audit_repository_layout.py"
)
SPEC = importlib.util.spec_from_file_location("audit_repository_layout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_markdown_audit_reports_broken_relative_link(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("# Target\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text(
        "[valid](target.md)\n[broken](missing.md)\n",
        encoding="utf-8",
    )

    broken = MODULE.broken_markdown_links([source])

    assert broken == [f"{source}:2: missing.md"]


def test_repository_markdown_paths_only_returns_tracked_markdown(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.md").write_text("# Tracked\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("# Untracked\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "tracked.md", "tracked.txt"],
        cwd=tmp_path,
        check=True,
    )

    paths = MODULE.repository_markdown_paths(tmp_path)

    assert paths == [tmp_path / "tracked.md"]


def test_repository_markdown_paths_preserves_unicode_names(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    document = tmp_path / "项目纠错.md"
    document.write_text("# 项目纠错\n", encoding="utf-8")
    subprocess.run(["git", "add", document.name], cwd=tmp_path, check=True)

    paths = MODULE.repository_markdown_paths(tmp_path)

    assert paths == [document]
