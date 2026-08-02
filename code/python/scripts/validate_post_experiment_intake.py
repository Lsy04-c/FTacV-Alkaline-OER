#!/usr/bin/env python3
"""Validate a post-experiment intake manifest before a new Gate A1 audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.experiment_intake import validate_intake


EXIT_CODES = {
    "READY_FOR_A1_AUDIT": 0,
    "WAITING_FOR_DATA": 2,
    "FAIL_METADATA": 3,
    "FAIL_STRUCTURE": 4,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise ValueError("intake manifest must be a JSON object")
    return value


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )


def _acceptance_markdown(summary: dict[str, Any]) -> str:
    status = summary["status"]
    next_action = summary["next_action"]
    return (
        "# 恢复实验接入验收\n\n"
        f"- 状态：`{status}`\n"
        f"- 唯一下一动作：`{next_action}`\n"
        f"- 缺失条件：{', '.join(summary['missing_conditions']) or '无'}\n"
        f"- 结构错误数：{len(summary['structure_errors'])}\n"
        f"- 元数据错误数：{len(summary['metadata_errors'])}\n\n"
        "本结果不代表 Gate A1 PASS；不授权 A6-v2、真实反演或参数点估计。\n"
    )


def _a1_seed(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    datasets = [
        {
            "dataset_id": row["dataset_id"],
            "condition_id": row["condition_id"],
            "analysis_role": row["analysis_role"],
            "experiment_id": row["experiment_id"],
            "raw_file": dict(row["raw_file"]),
            "method_file": dict(row["method_file"]),
        }
        for row in manifest["datasets"]
        if row.get("collection_state") == "collected"
    ]
    return {
        "schema_version": 1,
        "status": "UNVALIDATED_SEED",
        "requires_new_batch_a1_validator": True,
        "source_intake_id": manifest["intake_id"],
        "source_manifest_sha256": manifest_sha256,
        "datasets": datasets,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    manifest_path = args.manifest.resolve()
    output = args.output.resolve()
    try:
        manifest_relative = manifest_path.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError("manifest must be inside project-root") from exc
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"non-empty output directory is forbidden: {output}")
    manifest = _read_json(manifest_path)
    manifest_sha256 = _sha256(manifest_path)
    result = validate_intake(project_root, manifest)
    summary = {
        "schema_version": 1,
        "intake_id": manifest.get("intake_id"),
        "source_manifest": manifest_relative,
        "source_manifest_sha256": manifest_sha256,
        **result,
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "intake_summary.json", summary)
    _atomic_write(output / "acceptance.md", _acceptance_markdown(summary))
    if result["status"] == "READY_FOR_A1_AUDIT":
        _write_json(output / "a1_seed.json", _a1_seed(manifest, manifest_sha256))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
