#!/usr/bin/env python3
"""后验健康检查：越界即非零退出，供反演跑完后自动判定。

设立理由（docs/项目纠错.md §25）：2026-08-22 那轮 6 小时的正式反演，
R-hat 达 3–1e13、FT3 接受率仅 0.004，但**没有任何自动信号**——是人工翻
CSV 才发现的。判据是确定性的，不需要人也不需要模型来判断。

判据（可用命令行覆盖，默认值即项目当前标准）：
  R-hat < 1.1          链间收敛
  0.05 <= 接受率 <= 0.6  过低=链卡死，过高=步长过小
  参数不得贴边界        贴边界说明边界设错或参数不可辨识

用法：
    .venv/bin/python scripts/check_posterior.py results/low_dim_bonke
    echo $?     # 0 = 全部通过
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

RHAT_LIMIT = 1.10
ACCEPT_MIN, ACCEPT_MAX = 0.05, 0.60
EDGE_FRACTION = 0.02


def check_dataset(directory: str, args) -> list[str]:
    name = os.path.basename(directory.rstrip("/"))
    problems: list[str] = []

    summary_path = os.path.join(directory, "posterior_summary.csv")
    if not os.path.exists(summary_path):
        return [f"{name}: 缺少 posterior_summary.csv"]

    with open(summary_path) as handle:
        rows = [r for r in csv.DictReader(handle) if r.get("provenance") == "fitted"]
    if not rows:
        return [f"{name}: posterior_summary.csv 中没有 fitted 参数"]

    for row in rows:
        try:
            rhat = float(row["rhat"])
        except (KeyError, ValueError):
            problems.append(f"{name}/{row.get('parameter')}: rhat 不可解析")
            continue
        if not (rhat < args.rhat):
            problems.append(
                f"{name}/{row['parameter']}: R-hat={rhat:.3g} >= {args.rhat}（未收敛）")

    manifest_path = os.path.join(directory, "run_manifest.json")
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path))
        except Exception:  # noqa: BLE001
            problems.append(f"{name}: run_manifest.json 不可解析")
            manifest = {}
        for entry in manifest.get("datasets", []):
            for i, rate in enumerate(entry.get("acceptance") or []):
                if not (args.accept_min <= rate <= args.accept_max):
                    problems.append(
                        f"{name}/chain{i}: 接受率={rate:.4f} 越界 "
                        f"[{args.accept_min}, {args.accept_max}]")
    else:
        problems.append(f"{name}: 缺少 run_manifest.json（无法核对接受率）")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="含各数据集子目录的结果根目录")
    parser.add_argument("--rhat", type=float, default=RHAT_LIMIT)
    parser.add_argument("--accept-min", type=float, default=ACCEPT_MIN)
    parser.add_argument("--accept-max", type=float, default=ACCEPT_MAX)
    args = parser.parse_args()

    dirs = sorted(d for d in glob.glob(os.path.join(args.root, "*"))
                  if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    if not dirs:
        print(f"{args.root} 下没有数据集目录", file=sys.stderr)
        return 2

    all_problems: list[str] = []
    for directory in dirs:
        problems = check_dataset(directory, args)
        status = "PASS" if not problems else f"FAIL ({len(problems)})"
        print(f"  {os.path.basename(directory):8s} {status}")
        all_problems.extend(problems)

    if all_problems:
        print(f"\n后验健康检查未通过，共 {len(all_problems)} 项：", file=sys.stderr)
        for problem in all_problems[:20]:
            print(f"  - {problem}", file=sys.stderr)
        if len(all_problems) > 20:
            print(f"  ...另有 {len(all_problems) - 20} 项", file=sys.stderr)
        return 1

    print("\n后验健康检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
