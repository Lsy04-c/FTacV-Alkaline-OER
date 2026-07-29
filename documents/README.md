# 文档索引

本目录保存项目背景、执行记录和科研资料。根 README 只提供导航。

## 最小阅读顺序

后续用户或 Agent 默认按以下顺序读取：

1. `project/PROJECT_SUMMARY.md`：当前架构、接口、Gate 和未完成目标；
2. `plans/2026-07-29-vacation-and-post-experiment-roadmap.md`：当前行动；
3. 当前任务对应的正式 `acceptance.md` 或冻结 summary；
4. 只有需要追溯历史时才读取 `project/WORK_STATUS.md`；
5. 需要远程环境时再读取仓库外的本机环境配置。

| 新内容 | 保存位置 |
|---|---|
| 项目目标、状态、工作流 | `project/` |
| 错误、根因、修复 | `corrections/` |
| 可执行任务步骤 | `plans/` |
| 架构和接口规格 | `specifications/` |
| 文献、机理和研究分析 | `research/` |
| 脱敏环境说明 | `environment/` |
| agent 交接 | `handoffs/` |

`handoffs/` 和 `environment/private/` 仅供本机使用，默认不提交。后续 agent 不得在仓库根目录新增背景 Markdown。

`plans/` 只保留当前有效计划。已完成计划由项目总览、历史状态、正式验收和
Git 历史承担追溯，不继续堆放在当前计划目录。

DeepSeek 接续项目时必须先遵循
`specifications/deepseek-project-continuation-governance.md`；涉及计算时再遵循
`specifications/deepseek-compute-delivery-acceptance.md` 的任务冻结、数据留痕和验收规则。
