---
name: oer-ftacv-workflow
description: Use when running or continuing OER-FTAcV computations on Legion via the oer-wf CLI, judging whether a calculation may proceed to the next stage, or resuming an interrupted workflow. Applies to doctor/prepare/smoke/run/status/sync/verify/clean command sequences and any scientific gate decision on this project's frozen M0 recovery work.
---

# oer-ftacv-workflow

## Overview

OER-FTAcV 的科研计算由 `oer-wf` CLI 统一管理：工程步骤自动化，科学判断不自动化。每个命令输出结构化 JSON，只根据 `status` 和 `next_action` 推进；`fail_type` 决定是自己修复还是停下交给人。

## When to Use

- 接手 OER 计算：准备、启动、查询、同步、验收一个任务
- 判断某次计算能否进入下一阶段（smoke → formal → 验收）
- 接续被中断或已归档的任务（`wf status` / `wf sync` / `wf verify`）
- 任何涉及 Gate A1/A3/A6 边界或"是否可以宣称通过"的决策

**不使用**：纯代码开发、数据探索、Web 前端——那是其他工作流。

## 调用顺序（强制）

```text
wf doctor → wf prepare <spec> → wf smoke <spec> → wf run <spec>
→ wf status <task_id>（轮询到终态）→ wf sync <task_id> → wf verify <task_id>
```

- `wf clean <task_id> [--force]` 仅用于重置失败任务，不改变正常顺序
- 前一命令 `fail` 时**停止**，不跳过、不 `--force` 硬闯
- smoke 未 PASS 不得 run；verify 未过不得 sync 后宣称完成

## JSON 状态推进

每个命令 stdout 只有 JSON：

```json
{
  "status": "pass | fail | warning | running | inconsistent",
  "fail_type": "environment | transport | structure | numerical | scientific | null",
  "checks": [...],
  "data": {},
  "next_action": "下一步唯一动作",
  "message": "人类可读摘要"
}
```

| status | 动作 |
|--------|------|
| `pass` | 按 `next_action` 继续 |
| `fail` | 按 `fail_type` 处理（下表），不继续依赖阶段 |
| `warning` | 可继续，但把警告写入记录 |
| `running` | 轮询，不重复启动 |
| `inconsistent` | systemd 与 STATUS.json 冲突——不猜成功，先诊断 |

## 失败停止条件

| fail_type | 含义 | 处理 |
|-----------|------|------|
| environment | SSH/时钟/依赖/Git/系统 | 自查自修后重跑 |
| transport | rsync/文件缺失/哈希不符 | 自查自修后重跑 |
| structure | schema/文件齐全/provenance | 自查自修后重跑 |
| numerical | NaN/Inf/求解器失败 | 报告，不自行改阈值重跑 |
| scientific | 科学门未过 | **停止**，交 Codex/用户 |

**不得**：为通过而改阈值、边界、种子、预算或过滤规则；不得隐藏失败样本。

## 环境配置读取

正式计算前读取环境配置（先读，再动手）：

- `/Users/liushiyu/claude/本机环境配置.md`（含 Legion 连接、oer-wf 状态、冻结 commit、计算化学软件）
- `documents/project/PROJECT_SUMMARY.md`（冻结 Gate、参数角色、科学边界）

**关键前提**：Legion 需 `oer-wf 0.7.0` 已部署、systemd 存活、`WSL-Keeper` 保活、CN 库在 `cpp/liboercn.so`。正式计算一律 LSODA，CN 仅诊断。

## 科学验收边界

工程层可自动化：doctor/prepare/smoke/run/status/sync/verify/clean 的工程判断。

科学层**必须人工/Codex**：

- 任何"通过、提高、等价、可识别"结论
- 修改物理模型、参数边界、恢复阈值、数据集角色
- 把工程 PASS 升级为科学 PASS

**冻结 Gate 不可绕过**（工程 PASS 不改变）：A1 `FAIL_METADATA`、A3 `FAIL`、A6 `FAIL_RECOVERY`。`--skip-smoke`、`--force` 覆盖、resume 路径修改都需要明确授权。`task_spec.snapshot.yaml` 是 verify 的冻结契约，不得编辑已归档任务。

## Common Mistakes

- 把 smoke PASS 当作 formal PASS——smoke 只证明流程可运行
- `wf status` 返回 `inconsistent` 时直接宣称成功——双通道冲突必须诊断
- 用 `--force` 覆盖历史证据——重跑生成新时间戳目录，不覆盖旧结果
- 在任务归档后编辑 `task_spec.snapshot.yaml`——冻结契约，禁止改动
- 凭工程 PASS 改变 A1/A3/A6 结论——冻结 Gate 只由对应科学门决定
