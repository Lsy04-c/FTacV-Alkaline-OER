# CHI CV Tafel 审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从现有 CHI CV 原始文件生成只读、双扫描支分离的 Tafel 候选审计，不向反演或正式 Gate 提供约束。

**Architecture:** 新模块独立解析 CHI header 和数值行，把转折电位两侧保留为 forward/reverse 支。它只在原始电流阈值内作线性候选拟合，并明确输出 `EXPLORATORY_ONLY` 和缺失元数据；脚本把 JSON 报告写入用户指定诊断目录。模块不导入 `inversion`，也不修改 `measure_tafel`。

**Tech Stack:** Python 3.11+、NumPy、SciPy、pytest、JSON。

---

### Task 1: 解析、双支审计和单元测试

**Files:**

- Create: `code/python/src/oer_aem/cv_tafel_audit.py`
- Create: `code/python/tests/test_cv_tafel_audit.py`

- [ ] 写失败测试：包含一个最高电位转折点、不同的正反扫电流、逗号和 Tab 分隔输入。断言两支均保留三点，滞后量大于零，且分类为 `EXPLORATORY_ONLY`。
- [ ] 运行 `.venv/bin/python -m pytest code/python/tests/test_cv_tafel_audit.py -q`，确认模块缺失导致失败。
- [ ] 实现 `parse_chi_cv(path)`、`split_branches(data)`、`summarize_branch(branch, current_window_a)` 和 `audit_chi_cv(path)`。转折点为最高电位；禁止按电位去重或平均两支。候选仅报告原始电流窗口内的 `E`–`log10(I)` 线性拟合；不足十个正电流点时返回 `available=false`。输出固定四个 blocker：参比、iR、面积和稳态未解析。
- [ ] 重跑定向测试，确认通过。

### Task 2: 可追溯 CLI 和真实数据诊断

**Files:**

- Create: `code/python/scripts/audit_chi_cv_tafel.py`
- Modify: `code/python/tests/test_cv_tafel_audit.py`

- [ ] 写失败测试：CLI 接收 `--input`（可重复）和 `--output-dir`，写出的 JSON 含 64 位输入 SHA-256、双支摘要、滞后和分类。
- [ ] 运行定向测试，确认 CLI 导入失败。
- [ ] 实现 CLI。只允许显式输出目录；若同名 JSON 已存在则拒绝覆盖；不读取或写入 `data/raw/` 以外的原始数据。
- [ ] 用三条真实 CV 运行脚本到 `results/diagnostics/cv_tafel_audit_20260809/`，确认生成三份 `EXPLORATORY_ONLY` JSON，且每份有四个 blocker。

### Task 3: 科学边界、验证与提交

**Files:**

- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`

- [ ] 写入结论：三条 CV 已审计但没有一条升级为 `validated_apparent_tafel`；诊断不改变 formal profile/CMA 的 FAIL。
- [ ] 运行 `.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q` 和 `git diff --check`。
- [ ] 由 Sol 只读检查：代码没有平均双支；输出没有把候选表述为正式 Tafel；SHA-256 与四个 blocker 均在报告内。
- [ ] 只提交代码、测试和项目文档；诊断 JSON 保留本机/归档，不加入 Git。
