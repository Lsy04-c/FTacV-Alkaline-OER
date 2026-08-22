#!/usr/bin/env python3
"""合并按数据集分目录运行的低维拟合结果。

在拯救者上四个数据集并发运行（16 核 / 每个 4 条链），各自写入
``results/low_dim_bonke/<DATASET>/``。本脚本把它们合并成顶层证据文件，
并校验各分片的 commit、解释器与工作树一致——docs/项目纠错.md 第 9 条
要求正式结果的源码、依赖与输出必须形成唯一证据链。

用法：
    .venv/bin/python scripts/merge_low_dim_results.py
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MERGED = ("posterior_samples.csv", "posterior_summary.csv",
          "correlation.csv", "ru_sensitivity.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="results/low_dim_bonke")
    args = parser.parse_args()

    root = PROJECT / args.root
    shards = sorted(d for d in root.iterdir()
                    if d.is_dir() and not d.name.startswith("_")
                    and (d / "run_manifest.json").exists())
    if not shards:
        raise SystemExit(f"{root} 下没有可合并的分片")

    manifests = {d.name: json.loads((d / "run_manifest.json").read_text())
                 for d in shards}

    # 证据链一致性检查：分片之间必须同源
    for field in ("commit", "interpreter", "worktree", "python", "numpy", "scipy"):
        values = {name: m.get(field) for name, m in manifests.items()}
        if len(set(values.values())) > 1:
            raise SystemExit(f"分片 {field} 不一致，拒绝合并: {values}")

    for filename in MERGED:
        header, rows = None, []
        for shard in shards:
            path = shard / filename
            if not path.exists():
                continue
            with open(path, newline="") as handle:
                reader = csv.reader(handle)
                shard_header = next(reader, None)
                if shard_header is None:
                    continue
                if header is None:
                    header = shard_header
                elif shard_header != header:
                    raise SystemExit(f"{filename} 表头不一致: {shard.name}")
                rows.extend(reader)
        if header is None:
            continue
        with open(root / filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"{filename}: {len(rows)} rows from {len(shards)} shards")

    reference = manifests[shards[0].name]
    combined = {
        key: reference[key]
        for key in ("commit", "python", "numpy", "scipy", "platform", "hostname",
                    "worktree", "interpreter", "model", "free_parameters",
                    "pinned_provenance", "fit_harmonics", "excluded_from_objective",
                    "fit_window_V", "objective_optimiser", "global_search",
                    "objective_bayesian", "sampler", "scale_degeneracy_note")
        if key in reference
    }
    combined["merged_from"] = [d.name for d in shards]
    combined["args_per_shard"] = {name: m.get("args") for name, m in manifests.items()}
    combined["datasets"] = [row for m in manifests.values() for row in m.get("datasets", [])]
    with open(root / "run_manifest.json", "w") as handle:
        json.dump(combined, handle, indent=2, ensure_ascii=False)
    print(f"run_manifest.json: merged {len(shards)} shards @ commit {combined['commit'][:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
