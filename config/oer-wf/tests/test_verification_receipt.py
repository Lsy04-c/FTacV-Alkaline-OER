"""Append-only verification receipt tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from oer_wf.verification_receipt import archive_tree_hash, write_receipt


def test_receipt_is_written_outside_archive_and_contains_hashes(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive" / "results" / "abc" / "task" / "ts"
    archive.mkdir(parents=True)
    (archive / "STATUS.json").write_text('{"status":"SUCCESS"}')
    before = archive_tree_hash(archive)

    path = write_receipt(
        tmp_path / "archive",
        task_id="abc/task",
        result_timestamp="ts",
        payload={
            "task_id": "abc/task",
            "archive_tree_hash": before,
            "status": "pass",
        },
        now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert path.parent == (
        tmp_path / "archive" / "verifications" / "abc" / "task" / "ts"
    )
    saved = json.loads(path.read_text())
    assert saved["archive_tree_hash"] == before
    assert saved["receipt_hash"] in path.name
    assert archive_tree_hash(archive) == before


def test_receipt_refuses_to_overwrite_collision(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    payload = {"task_id": "abc/task", "status": "pass"}
    write_receipt(
        tmp_path,
        task_id="abc/task",
        result_timestamp="ts",
        payload=payload,
        now=now,
    )

    with pytest.raises(FileExistsError):
        write_receipt(
            tmp_path,
            task_id="abc/task",
            result_timestamp="ts",
            payload=payload,
            now=now,
        )
