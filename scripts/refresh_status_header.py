#!/usr/bin/env python3
"""刷新 WORK_STATUS.md 顶部「当前态」块。

当前态字段（HEAD、分支、测试数、核实时间）一律由本脚本从 git 与 pytest
生成，不手写——手写的字段会过期。2026-08-22 审计发现 WORK_STATUS 头部
声称的「最新已推送 3edb8de」「17 passed」与实际相差 40 多个提交，
而文件头的「当前主线」宣传的正是当天被撤回的结论。

用法：
    .venv/bin/python scripts/refresh_status_header.py
    .venv/bin/python scripts/refresh_status_header.py --check   # 只校验不写
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TARGET = PROJECT / "WORK_STATUS.md"
BEGIN = "<!-- STATUS:BEGIN 由 scripts/refresh_status_header.py 生成，请勿手改 -->"
END = "<!-- STATUS:END -->"


def _run(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=PROJECT, text=True).strip()


def count_tests() -> str:
    """收集测试数量（--collect-only，不实际执行）。"""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "python/tests", "-q", "--collect-only"],
            cwd=PROJECT, text=True, capture_output=True, timeout=300,
            env={**__import__("os").environ, "PYTHONPATH": str(PROJECT / "python")},
        ).stdout
        match = re.search(r"(\d+)\s+tests? collected", out)
        return match.group(1) if match else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def build_block() -> str:
    head = _run(["git", "rev-parse", "--short", "HEAD"])
    subject = _run(["git", "log", "-1", "--format=%s"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return "\n".join([
        BEGIN,
        "",
        "| 机器生成字段 | 值 |",
        "|---|---|",
        f"| 最后核实 | {date.today().isoformat()} |",
        f"| 分支 | `{branch}` |",
        f"| 生成时 HEAD | `{head}` {subject} |",
        f"| 收集到的测试数 | {count_tests()} |",
        "",
        "> 本表由 `scripts/refresh_status_header.py` 生成。增删测试后请重跑，",
        "> `python/tests/test_status_header.py` 校验「测试数」与「分支」；",
        "> 「最后核实」与「生成时 HEAD」仅供追溯，不参与校验（它们每次提交都变，",
        "> 纳入校验会自指循环）。",
        "",
        END,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验，不写入")
    args = parser.parse_args()

    text = TARGET.read_text()
    block = build_block()
    if BEGIN not in text or END not in text:
        print(f"{TARGET.name} 缺少 STATUS 标记块", file=sys.stderr)
        return 2

    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    current = pattern.search(text).group(0)

    def comparable(s: str) -> str:
        """只比较'会真正过期'的字段。

        `最后核实` 与 `HEAD` 每次提交都变——刷新本身就会产生新提交，把它们
        纳入校验会导致永远处于过期状态（自指循环）。真正有意义的不变量是
        测试数与分支：它们只在做了实质改动时才变，而那正是文档声称的
        「验证状态」失效的时刻。
        """
        s = re.sub(r"^\| 最后核实 \|.*$", "", s, flags=re.M)
        s = re.sub(r"^\| 生成时 HEAD \|.*$", "", s, flags=re.M)
        return s

    if comparable(current) == comparable(block):
        print("STATUS 块与实际一致")
        return 0
    if args.check:
        print("STATUS 块已过期，运行 scripts/refresh_status_header.py 刷新",
              file=sys.stderr)
        return 1
    TARGET.write_text(pattern.sub(lambda _: block, text))
    print("STATUS 块已刷新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
