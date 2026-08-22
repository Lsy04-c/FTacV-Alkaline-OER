"""校验 WORK_STATUS.md 的机器生成块与实际一致，并检查两份交接文档的写入规则。

设立理由：2026-08-22 审计发现 WORK_STATUS 头部声称「最新已推送 3edb8de」
「17 passed」，而实际相差 40 多个提交；文件头的「当前主线」宣传的正是当天
被撤回的结论（`docs/项目纠错.md` §10）。规则治不好这种事——写规则的项目
本来就有 PROJECT_WORKFLOW §2 而没人执行。只有测试能守住。

失败时的修法是一条命令，不是负担：
    .venv/bin/python scripts/refresh_status_header.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent.parent
WORK_STATUS = PROJECT / "WORK_STATUS.md"
SUMMARY = PROJECT / "PROJECT_SUMMARY.md"
ERRORS = PROJECT / "docs" / "项目纠错.md"


def test_status_block_matches_reality():
    """STATUS 块必须与当前 git 状态一致。"""
    result = subprocess.run(
        [sys.executable, str(PROJECT / "scripts" / "refresh_status_header.py"), "--check"],
        cwd=PROJECT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "WORK_STATUS.md 的 STATUS 块已过期。\n"
        "修法：.venv/bin/python scripts/refresh_status_header.py\n"
        f"{result.stdout}{result.stderr}"
    )


def test_status_block_is_not_hand_edited():
    """STATUS 块必须保留生成标记，防止有人手改后与脚本脱节。"""
    text = WORK_STATUS.read_text()
    assert "STATUS:BEGIN" in text and "STATUS:END" in text
    assert "请勿手改" in text


def test_handoff_documents_declare_write_rules():
    """两份交接文档都必须在文件内声明写入规则——规则要躲不掉。"""
    for path in (WORK_STATUS, SUMMARY):
        assert "## 写入规则" in path.read_text(), f"{path.name} 缺少写入规则小节"


def test_history_sections_carry_dates():
    """历史小节必须带日期，否则无法判断'未解决'挂了多久。

    只对 2026-08-22 规则生效之后新增的小节强制（编号 >= 20）。
    """
    text = WORK_STATUS.read_text()
    for match in re.finditer(r"^## (\d+)\.\s+(.+)$", text, re.M):
        number, title = int(match.group(1)), match.group(2)
        if number < 20:
            continue
        assert re.search(r"\d{4}-\d{2}-\d{2}", title), (
            f"WORK_STATUS §{number} 标题缺少日期：{title}"
        )


def test_no_bare_section_references_across_documents():
    """禁止裸 §N 引用——WORK_STATUS 与 项目纠错 的编号会撞车。

    实例：两份文档都有 §19，内容分别是求解器等价性门和 WSL 后台作业被销毁。
    """
    offenders = []
    for path in PROJECT.glob("**/*.py"):
        if ".venv" in str(path) or "worktrees" in str(path):
            continue
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            for m in re.finditer(r"§\s*(\d+)", line):
                prefix = line[: m.start()]
                if not re.search(r"(WORK_STATUS|纠错|项目纠错)\S*\s*$", prefix):
                    offenders.append(f"{path.relative_to(PROJECT)}:{lineno}: {line.strip()[:70]}")
    assert not offenders, (
        "发现裸 §N 引用，必须写成 `WORK_STATUS §N` 或 `纠错 §N`：\n"
        + "\n".join(offenders)
    )


def test_error_log_entries_have_status_field():
    """纠错每条必须有状态字段——否则无法统计还剩几条未解决。"""
    text = ERRORS.read_text()
    entries = re.split(r"^### \d+\.", text, flags=re.M)[1:]
    missing = [e.strip().splitlines()[0][:40] for e in entries
               if "- 状态：" not in e]
    assert not missing, f"以下纠错条目缺少「状态」字段：{missing}"
