# Project Roadmap Documentation Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented roadmap with one handoff-ready project summary, one active two-stage plan, and a smaller set of non-duplicative project documents.

**Architecture:** `PROJECT_SUMMARY.md` becomes the single current-state and architecture entry point. `WORK_STATUS.md` remains append-only history, while `documents/plans/` contains only the active vacation/post-experiment roadmap; completed plans are deleted after their durable conclusions and interfaces are represented in the summary and formal acceptance evidence.

**Tech Stack:** Markdown, Git history, repository Markdown-link audit, shell path checks.

---

## File map

| File | Responsibility |
|---|---|
| `documents/project/PROJECT_SUMMARY.md` | Current project state, architecture, interfaces, evidence, blockers and handoff |
| `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md` | Only active scientific execution plan |
| `documents/project/WORK_STATUS.md` | Append-only chronological history with current-entry pointer |
| `documents/project/PROJECT_WORKFLOW.md` | Stable execution and verification rules |
| `README.md` | Repository entry links and current branch-neutral commands |
| `documents/README.md` | Document responsibilities and minimal reading order |
| `documents/plans/*.md` | Delete completed or superseded plans after summary coverage |
| `documents/project/architecture_validation_report.md` | Delete after durable architecture conclusions move to summary |

## Task 1: Freeze the source-of-truth inventory

- [ ] Confirm the current branch and clean worktree with:

```bash
git status --short
git branch --show-current
```

Expected: branch `codex/reclassify-project`; no unrelated changes.

- [ ] Record the formal Gate sources used by the summary:

```text
A1 results/formal/data_contract/gate-a1-a57d42f/acceptance.md
A2 results/formal/physics_invariants/gate-a2r-496a701/acceptance.md
A3 results/formal/solver_equivalence/formal-a4581de-ppc256/acceptance.md
A4 results/formal/harmonic_stability/gate-a4-6848613/acceptance.md
A5 results/formal/feature_channel_contract/gate-a5-13adcb1/acceptance.md
A6 results/formal/identifiability/gate-a6-closure-75e25ed/acceptance.md
A7 documents/project/WORK_STATUS.md section 0.7
```

- [ ] Verify every code/interface path planned for the summary exists:

```bash
test -f code/python/src/oer_aem/data_contract.py
test -f code/python/src/oer_aem/physics.py
test -f code/python/src/oer_aem/signal.py
test -f code/python/src/oer_aem/inversion.py
test -f code/python/src/oer_aem/identifiability.py
test -d code/cpp/src
test -d code/web
test -d config
```

Expected: exit code 0.

## Task 2: Rewrite the handoff-ready project summary

**Files:**

- Replace: `documents/project/PROJECT_SUMMARY.md`

- [ ] Replace the historical mixed roadmap with these exact top-level sections:

```text
1. 当前一句话状态
2. 项目目标与科学边界
3. 系统架构与数据流
4. 代码目录与关键接口
5. Gate A1–A7 状态
6. 当前数据、特征与参数口径
7. 已完成能力与证据
8. 未完成目标与依赖
9. 休假期间路线
10. 恢复实验后的路线
11. 运行、测试与远程计算
12. 后续 Agent 交接
13. 项目完成定义
```

- [ ] Include an interface table with columns:

```text
模块 | 主入口 | 输入 | 输出 | 状态/限制
```

It must cover data contract, physics, solvers, signal extraction, objective,
identifiability, validators, workflow and Web.

- [ ] Include a Gate table that preserves these exact scientific outcomes:

```text
A1 FAIL_METADATA
A2-R PASS
A3 FAIL
A4 PASS
A5 PASS
A6 FAIL_RECOVERY
A7 PASS (engineering)
```

- [ ] Include the exact current parameter roles:

```text
fixed = A, Cdl, Ru, E0_pre, k0_pre, gamma, k0_4, scaling_OOH_OH
diagnostic_only = k0_1, k0_2, k0_3, G_OH, G_O
free = []
narrow_prior = []
```

- [ ] State the current data contract without overclaiming:

```text
columns = potential, current, time
units = V vs RHE, A, s (project-owner declaration)
instrument preprocessing = unresolved
four datasets are not replicates
```

- [ ] Add current prohibitions:

```text
no formal real-data inversion
no credible parameter point estimates
no CN-based formal scientific conclusions
no threshold or budget changes that rewrite failed Gates
```

- [ ] Keep the summary within 300–450 lines and run:

```bash
wc -l documents/project/PROJECT_SUMMARY.md
git diff --check
```

Expected: line count between 300 and 450; no whitespace errors.

## Task 3: Create the only active two-stage roadmap

**Files:**

- Create: `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`

- [ ] Write the vacation phase with ordered tasks:

```text
V1 user-declared metadata update
V2 conditional model reachable-set analysis
V3 DC/H1-H3 residual attribution
V4 experiment-information design
V5 solver acceleration only if justified by V2/V3 budget
```

Each task must include inputs, outputs, acceptance, stop conditions and prohibited claims.

- [ ] Write the post-experiment phase with ordered tasks:

```text
E1 primary metadata capture
E2 independent Ru/Cdl/area/loading/site-density constraints
E3 structured FTacV condition matrix
E4 sensitivity and profile rebuild
E5 A6-v2 synthetic recovery
E6 formal real-data joint inversion
E7 uncertainty and mechanism validation
```

- [ ] Add a dependency diagram and a decision table distinguishing:

```text
model cannot reach experiment
model reaches experiment but parameters are non-unique
new data breaks coupling
new data does not break coupling
```

- [ ] Verify the plan contains no authorization for current formal TPE:

```bash
rg -n "正式.*TPE|真实.*正式反演" \
  documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md
```

Expected: every match is explicitly prohibited until A6-v2 passes.

## Task 4: Update navigation and history entry points

**Files:**

- Modify: `README.md`
- Modify: `documents/README.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_WORKFLOW.md`

- [ ] Replace the stale root README current-plan link with:

```text
documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md
```

- [ ] Add this minimum reading order to `documents/README.md`:

```text
PROJECT_SUMMARY → active roadmap → task acceptance → WORK_STATUS only when history is needed
```

- [ ] Add a notice at the top of `WORK_STATUS.md`:

```text
本文件只保存历史执行记录，不是当前计划入口。
```

- [ ] Update `PROJECT_WORKFLOW.md`:

```text
branch = codex/reclassify-project
current priority = follow PROJECT_SUMMARY and active roadmap
formal real-data inversion remains blocked
```

- [ ] Run:

```bash
git diff --check
```

Expected: no whitespace errors.

## Task 5: Delete duplicated and superseded plans

**Files:**

- Delete all pre-existing `documents/plans/*.md`
- Preserve only:
  `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`

- Delete:
  `documents/project/architecture_validation_report.md`

- [ ] Before deletion, confirm every old plan is tracked:

```bash
git ls-files 'documents/plans/*.md'
```

- [ ] Delete completed/superseded plans after Tasks 2–4 cover their durable
  conclusions.

- [ ] Confirm the final plan directory contains exactly one Markdown file:

```bash
find documents/plans -maxdepth 1 -type f -name '*.md' -print
```

Expected:

```text
documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md
```

- [ ] Search retained Markdown for deleted plan references:

```bash
deleted_paths=$(git diff --name-only --diff-filter=D -- 'documents/plans/*.md')
for path in $deleted_paths; do
  rg -l --fixed-strings "$path" --glob '*.md' . || true
done
```

Expected: no retained Markdown references.

## Task 6: Pressure-test the rewritten handoff

- [ ] Verify every interface path extracted from the summary:

```bash
rg -o '`(code|config|data|results)/[^`]+`' \
  documents/project/PROJECT_SUMMARY.md
```

Inspect every emitted path and confirm it exists.

- [ ] Verify formal states are not contradicted:

```bash
rg -n "A1|A2-R|A3|A4|A5|A6|A7|FAIL_METADATA|FAIL_RECOVERY" \
  documents/project/PROJECT_SUMMARY.md
```

Expected: one consistent current-state table and matching boundary statements.

- [ ] Run repository documentation audits:

```bash
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

Expected: Markdown link audit passed; no whitespace errors.

- [ ] Run the full Python suite because the layout audit is part of repository tests:

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

Expected: all tests pass.

## Task 7: Publish the documentation refactor

- [ ] Review the final scope:

```bash
git status --short
git diff --stat
git diff
```

Expected: only project Markdown files; no code, data, environment-private or result changes.

- [ ] Read `/Users/liushiyu/gpt/本机环境配置.md` before remote Git operations.

- [ ] Commit:

```bash
git add README.md documents
git commit -m "docs(project): consolidate roadmap and handoff"
```

- [ ] Push:

```bash
git push origin codex/reclassify-project
```

- [ ] Confirm:

```bash
git status --short
```

Expected: clean worktree.
