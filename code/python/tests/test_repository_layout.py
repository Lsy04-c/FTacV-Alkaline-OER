from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]


def test_required_top_level_directories_exist():
    required = {
        "code/python",
        "code/matlab",
        "code/cpp",
        "code/web",
        "documents/project",
        "documents/corrections",
        "documents/plans",
        "documents/specifications",
        "documents/research",
        "documents/environment",
        "data/raw",
        "data/processed",
        "results/formal",
        "results/smoke",
        "results/diagnostics",
        "config",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_dir())
    assert missing == []


def test_root_markdown_is_limited_to_navigation():
    actual = {path.name for path in ROOT.glob("*.md")}
    assert actual == {"README.md"}


def test_code_and_document_indexes_exist():
    required = {
        "README.md",
        "code/python/README.md",
        "code/matlab/README.md",
        "code/cpp/README.md",
        "code/web/README.md",
        "documents/README.md",
        "data/README.md",
        "results/README.md",
        "config/README.md",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_file())
    assert missing == []


def test_active_validation_scripts_use_classified_web_test_paths():
    scripts = [
        ROOT / "code/python/scripts/audit_workspace_baseline.py",
        ROOT / "code/python/scripts/build_validation_manifest.py",
    ]
    obsolete = []
    for script in scripts:
        for line_number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if "code/web/backend/test_" in line:
                obsolete.append(f"{script.relative_to(ROOT)}:{line_number}")
    assert obsolete == []


def test_git_does_not_track_legacy_source_directories():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    legacy_prefixes = ("python/", "web/", "scripts/", "cpp/", "docs/")
    legacy = sorted(
        path
        for path in result.stdout.splitlines()
        if path.startswith(legacy_prefixes)
    )
    assert legacy == []
