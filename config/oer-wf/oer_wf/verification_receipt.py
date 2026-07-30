"""Immutable archive hashing and append-only verification receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def archive_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def write_receipt(
    archive_root: Path,
    *,
    task_id: str,
    result_timestamp: str,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> Path:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid task_id: {task_id}")
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated_at = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    base = {**payload, "generated_at": generated_at}
    receipt_hash = hashlib.sha256(_canonical_bytes(base)).hexdigest()
    receipt = {**base, "receipt_hash": receipt_hash}
    directory = (
        archive_root
        / "verifications"
        / parts[0]
        / parts[1]
        / result_timestamp
    )
    directory.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    final = directory / f"{stamp}-{receipt_hash}.json"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".receipt-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(_canonical_bytes(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, final)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return final
