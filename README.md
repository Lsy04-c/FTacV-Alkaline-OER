# OER-FTAcV

碱性 OER FTacV 微观动力学建模、谐波分析和参数反演项目。

本 README 用于帮助用户和其他 agent 快速理解仓库结构、找到运行入口，并把新增文件放入正确目录。项目目标、历史进度和科研结论保存在 `documents/`，不在此重复。

## 目录索引

| 路径 | 内容 | 入口 |
|---|---|---|
| `code/python/` | Python 科学计算核心、测试和计算脚本 | `code/python/README.md` |
| `code/matlab/` | MATLAB 参考实现和测试 | `code/matlab/README.md` |
| `code/cpp/` | C++ 数值求解器和本机构建目录 | `code/cpp/README.md` |
| `code/web/` | 前端和 FastAPI 服务 | `code/web/README.md` |
| `documents/` | 项目、纠错、计划、规格、科研和环境文档 | `documents/README.md` |
| `data/` | 原始数据和处理数据 | `data/README.md` |
| `results/` | formal、smoke 和 diagnostics 证据 | `results/README.md` |
| `config/` | 不含秘密的项目配置 | `config/README.md` |

## 项目主入口

- 项目目标与总路线：`documents/project/PROJECT_SUMMARY.md`
- 当前工作状态：`documents/project/WORK_STATUS.md`
- 项目工作流：`documents/project/PROJECT_WORKFLOW.md`
- 项目纠错：`documents/corrections/项目纠错.md`
- 当前实施计划：`documents/plans/2026-07-26-project-directory-reclassification.md`

## 常用命令

目录迁移完成后统一使用：

```bash
# Python 全量测试
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q

# Web 后端测试
.venv/bin/python -m pytest code/web/tests/backend -q

# C++ CN 构建（macOS）
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.dylib code/cpp/src/oer_cn_solver.cpp
```

## 新文件放置规则

| 新内容 | 保存位置 |
|---|---|
| Python 核心代码 | `code/python/src/oer_aem/` |
| Python 测试 | `code/python/tests/` |
| 计算、诊断和验证脚本 | `code/python/scripts/` |
| MATLAB 代码 | `code/matlab/src/` |
| C++ 代码 | `code/cpp/src/` |
| 前端或 FastAPI | `code/web/` |
| 项目目标、状态、工作流 | `documents/project/` |
| 错误、根因、修复 | `documents/corrections/` |
| 可执行任务步骤 | `documents/plans/` |
| 架构和接口规格 | `documents/specifications/` |
| 文献、机理和研究分析 | `documents/research/` |
| 脱敏环境说明 | `documents/environment/` |
| agent 交接 | `documents/handoffs/` |
| 原始实验数据 | `data/raw/` |
| 可复现处理数据 | `data/processed/` |
| 正式科学证据 | `results/formal/` |
| 小预算流程检查 | `results/smoke/` |
| 诊断结果 | `results/diagnostics/` |

## 维护规则

1. 不在仓库根目录新增项目背景 Markdown。
2. README 只负责索引、入口和放置规则；详细内容写入对应子目录。
3. 编译产物放入 `code/cpp/build/`，不得提交 Git。
4. 含密码、token、私钥或完整认证命令的环境文件仅保存在忽略目录。
5. smoke 结果不得覆盖 formal 结果。
6. 移动或新增文件后同步更新所在目录 README。
7. 每个验证版本运行测试、更新项目状态、提交并推送。
