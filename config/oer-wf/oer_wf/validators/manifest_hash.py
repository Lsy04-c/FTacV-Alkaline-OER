"""Verify SHA256 entries in manifest.json against actual files (if present)."""

from __future__ import annotations

import json
from pathlib import Path

from oer_wf.models import CheckResult
from oer_wf.utils.hash import sha256_file


def run(archive_dir: Path, expected_files: list[str] | None = None) -> list[CheckResult]:
    checks: list[CheckResult] = []
    manifest = archive_dir / "manifest.json"
    if not manifest.is_file():
        checks.append(
            CheckResult(name="manifest_hash", passed=True, detail="no manifest.json (skipped)")
        )
        return checks

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [CheckResult(name="manifest_hash", passed=False, detail=f"corrupt: {e}")]

    # Accept several common shapes
    entries = data.get("files") or data.get("sha256") or data.get("hashes") or {}
    if isinstance(entries, list):
        mapping = {}
        for item in entries:
            if isinstance(item, dict):
                name = item.get("name") or item.get("path") or item.get("file")
                digest = item.get("sha256") or item.get("hash")
                if name and digest:
                    mapping[name] = digest
        entries = mapping

    if not isinstance(entries, dict) or not entries:
        checks.append(
            CheckResult(name="manifest_hash", passed=True, detail="no hash entries (skipped)")
        )
        return checks

    for name, expected in entries.items():
        p = archive_dir / name
        if not p.is_file():
            checks.append(CheckResult(name=f"hash:{name}", passed=False, detail="file missing"))
            continue
        actual = sha256_file(p)
        exp = expected if str(expected).startswith("sha256:") else f"sha256:{expected}"
        if actual == exp:
            checks.append(CheckResult(name=f"hash:{name}", passed=True, detail="match"))
        else:
            checks.append(
                CheckResult(name=f"hash:{name}", passed=False, detail=f"expected {exp}, got {actual}")
            )
    return checks
