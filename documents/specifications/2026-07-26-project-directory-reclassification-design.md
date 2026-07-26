# OER-FTAcV 项目目录重分类设计

日期：2026-07-26
状态：已获用户设计批准，待用户复核书面规格

## 1. 目标

重构仓库目录，使用户和其他 agent 无需阅读源码即可理解：

- 每个一级目录保存什么；
- Python、MATLAB、C++ 和 Web 代码分别从哪里进入；
- 项目背景、进度、纠错、工作流和研究文档保存在哪里；
- 新代码、文档、数据和结果应该放入哪个目录；
- 如何运行测试、计算和 Web 服务。

根目录 `README.md` 是目录导航，不承担完整项目报告功能。项目目标保存在项目文档，历史进度保存在状态文档，具体设计和计划保存在独立子目录。

## 2. 设计原则

1. 按职责分类，不按创建时间分类。
2. 源码、测试、脚本和构建产物分开。
3. Python、MATLAB、C++ 和 Web 各有独立入口。
4. 项目管理文档与科研资料分开。
5. smoke 与 formal 结果分开。
6. 根目录只保留总 README、版本控制文件和必要的项目级配置。
7. 使用英文目录名，README 使用中文解释，减少 Python、Node、WSL 和 CI 的路径兼容风险。
8. 使用 Git 移动保留文件历史。
9. 迁移同步修正所有 import、脚本入口、动态库路径、测试路径和文档链接。
10. 每个迁移阶段独立验证和提交。

## 3. 目标目录

```text
OER-FTAcV/
├── README.md
├── .gitignore
├── code/
│   ├── python/
│   │   ├── src/oer_aem/
│   │   ├── tests/
│   │   ├── scripts/
│   │   ├── examples/
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── matlab/
│   │   ├── src/
│   │   ├── tests/
│   │   └── README.md
│   ├── cpp/
│   │   ├── src/
│   │   ├── tests/
│   │   ├── build/
│   │   └── README.md
│   └── web/
│       ├── frontend/
│       ├── backend/
│       ├── tests/
│       ├── package.json
│       ├── requirements.txt
│       └── README.md
├── documents/
│   ├── project/
│   ├── corrections/
│   ├── plans/
│   ├── specifications/
│   ├── research/
│   ├── environment/
│   ├── handoffs/
│   └── README.md
├── data/
│   ├── raw/
│   ├── processed/
│   └── README.md
├── results/
│   ├── formal/
│   ├── smoke/
│   ├── diagnostics/
│   └── README.md
└── config/
    └── README.md
```

## 4. 代码分类

### 4.1 Python

目标路径：`code/python/`

| 当前路径 | 目标路径 | 职责 |
|---|---|---|
| `python/oer_aem/` | `code/python/src/oer_aem/` | 科学计算核心 |
| `python/tests/` | `code/python/tests/` | Python 核心测试 |
| `python/examples/` | `code/python/examples/` | 使用示例 |
| `python/requirements.txt` | `code/python/requirements.txt` | Python 依赖 |
| `python/bench_inversion.py` | `code/python/scripts/bench_inversion.py` | 基准测试 |
| `scripts/*.py` | `code/python/scripts/` | 计算、诊断、验证和结果生成入口 |

Python 包采用 `src` 布局。测试入口必须显式加入 `code/python/src`，不得依赖旧 `python/` 路径。

### 4.2 MATLAB

目标路径：`code/matlab/`

| 当前路径 | 目标路径 |
|---|---|
| `OER_Core.m` | `code/matlab/src/OER_Core.m` |
| `OER_IO.m` | `code/matlab/src/OER_IO.m` |
| `OER_Objective.m` | `code/matlab/src/OER_Objective.m` |
| `OER_Params.m` | `code/matlab/src/OER_Params.m` |
| `OER_Physics.m` | `code/matlab/src/OER_Physics.m` |
| `OER_Signal.m` | `code/matlab/src/OER_Signal.m` |
| `apply_alkaline_aem.m` | `code/matlab/src/apply_alkaline_aem.m` |
| `initialize_oer_parameters.m` | `code/matlab/src/initialize_oer_parameters.m` |
| `test_oer_model.m` | `code/matlab/tests/test_oer_model.m` |

MATLAB README 必须写明如何把 `src/` 加入 MATLAB path，以及测试入口。

### 4.3 C++

目标路径：`code/cpp/`

| 当前路径 | 目标路径 | 处理 |
|---|---|---|
| `cpp/oer_cn_solver.cpp` | `code/cpp/src/oer_cn_solver.cpp` | 正式 CN 求解器 |
| `cpp/oer_ode_core.cpp` | `code/cpp/src/experimental/oer_ode_core.cpp` | 实验实现 |
| `cpp/oer_core_mex_port.cpp` | `code/cpp/src/experimental/oer_core_mex_port.cpp` | 实验 MEX 端口 |
| `cpp/*.dylib`、`cpp/*.so`、`cpp/*.dll` | `code/cpp/build/` | 本机构建产物，不提交 |

`python/oer_aem/cpp_bridge.py` 迁移后必须从新 build 路径加载动态库。正式结果必须记录源码 commit 和动态库平台。

### 4.4 Web

目标路径：`code/web/`

| 当前路径 | 目标路径 |
|---|---|
| `web/frontend/` | `code/web/frontend/` |
| `web/backend/main.py` | `code/web/backend/main.py` |
| `web/backend/test_*.py` | `code/web/tests/backend/` |
| `web/package.json` | `code/web/package.json` |
| `web/requirements.txt` | `code/web/requirements.txt` |
| `web/dev.sh` | `code/web/dev.sh` |

Web 后端只调用 `code/python/src/oer_aem`，不得复制科学计算逻辑。Web README 说明前端、后端和联合启动方式。

## 5. 文档分类

目标路径：`documents/`

### 5.1 项目管理

`documents/project/` 保存：

- `PROJECT_SUMMARY.md`：目标、完成定义和总路线；
- `WORK_STATUS.md`：按时间记录实际进度；
- `PROJECT_WORKFLOW.md`：版本、验证和提交工作流；
- `context_compact_*.md`：项目上下文快照；
- `workflow_summary_*.md`：阶段工作流总结；
- `architecture_validation_report.md`：架构验证报告。

### 5.2 纠错

`documents/corrections/` 保存：

- `项目纠错.md`；
- 其他项目内问题、根因、修复和残余风险。

项目结束后才把跨项目经验提炼到仓库外的全局纠错文档。

### 5.3 计划与规格

- `documents/plans/`：可执行计划；
- `documents/specifications/`：设计规格。

现有 `docs/superpowers/plans/` 和 `docs/superpowers/specs/` 分别迁入这两个目录。

### 5.4 科研资料

`documents/research/` 保存：

- 机理分析；
- 参数设计；
- 文献阅读；
- 论文资料；
- 模型假设和对照分析。

现有 `docs/papers/`、`gamma_calibration_proposal.md`、`her_oer_comparison_critique.md` 和 `parameter_importance_design.md` 迁入该目录。

### 5.5 环境与交接

- `documents/environment/`：脱敏后的环境问题、解决状态和复现要求；
- `documents/handoffs/`：agent 交接文档，默认加入 `.gitignore`。

含密码、token、私钥或具体秘密连接信息的文件不得提交。迁移前先做敏感信息扫描；发现秘密时保留本机文件并从 Git 暂存范围排除。

## 6. 数据与结果

### 6.1 数据

保留 `data/raw/` 和 `data/processed/`。`data/README.md` 说明：

- 原始数据不可覆盖；
- 处理数据必须记录来源和生成脚本；
- 大文件和敏感实验数据的 Git 策略。

### 6.2 结果

结果按证据等级分类：

- `results/formal/`：通过正式配置产生、可进入科学结论的结果；
- `results/smoke/`：只验证流程；
- `results/diagnostics/`：数据质量、残差、网格、求解器和模型缺口诊断。

迁移旧结果时不根据文件名猜等级。已有正式 manifest 支持的结果进入 `formal/`；明确的小预算结果进入 `smoke/`；其余进入 `diagnostics/` 并在结果 README 标注证据等级。

## 7. README 体系

### 7.1 根 README

根 `README.md` 面向首次进入仓库的用户和 agent，只包含：

1. 一句话项目说明；
2. 目录树；
3. 每个一级目录的职责；
4. 用户入口；
5. agent 入口；
6. 常用命令索引；
7. 新文件放置规则；
8. 文档维护规则；
9. 当前主线文档链接。

根 README 不复制项目历史、完整科研结论或长篇环境修复记录。

### 7.2 子目录 README

`code/python/`、`code/matlab/`、`code/cpp/`、`code/web/`、`documents/`、`data/`、`results/` 和 `config/` 各自包含 README，说明：

- 本目录用途；
- 子目录说明；
- 主要入口；
- 测试或验证命令；
- 新文件归类规则；
- 禁止存放的内容。

### 7.3 后续文档规则

新增 Markdown 前必须先选择：

| 文档内容 | 目录 |
|---|---|
| 项目目标、状态、工作流 | `documents/project/` |
| 错误、根因、修复 | `documents/corrections/` |
| 执行步骤 | `documents/plans/` |
| 架构与接口设计 | `documents/specifications/` |
| 文献、机理、研究分析 | `documents/research/` |
| 脱敏环境说明 | `documents/environment/` |
| agent 交接 | `documents/handoffs/` |

根 README 和 `documents/README.md` 必须包含这张规则表。后续 agent 不得在仓库根目录新增背景 Markdown。

## 8. 路径迁移与兼容

迁移必须更新：

- Python import 和 `sys.path`；
- `scripts/run_tests.py` 的解释器与测试路径；
- Web 后端的 Python 路径；
- C++ bridge 的动态库路径；
- shell 启动脚本；
- pytest 配置；
- GitHub 或本地自动化中的路径；
- 文档内部相对链接；
- Legion 正式计算命令和输出路径；
- manifest 中记录的脚本路径。

不保留长期兼容软链接。迁移期间可在一个提交内使用临时兼容路径，但最终提交必须删除，以免形成两个入口。

## 9. 分阶段迁移

### 阶段 1：目录骨架与 README

创建目标目录和 README，冻结映射表。此阶段不移动科学代码。

### 阶段 2：文档

移动项目、纠错、计划、规格、科研和环境文档，修正链接并扫描秘密。

### 阶段 3：MATLAB 与 C++

移动 MATLAB、C++ 源码和测试；更新动态库构建与加载路径。

### 阶段 4：Python

移动包、测试和脚本；统一 `src` 布局；修复所有 import 和执行入口。

### 阶段 5：Web

移动前端与后端；修复联合启动、API 测试和 Python 核心引用。

### 阶段 6：结果分类

按 manifest 和运行预算分类 formal、smoke 与 diagnostics，禁止凭主观判断升级证据。

### 阶段 7：全链路验收

运行 Python、Web、MATLAB 可用性、C++ 编译、求解器 bridge、路径扫描和 Markdown 链接检查。更新根 README 的最终目录树。

每个阶段独立提交并推送。阶段失败时停止后续迁移。

## 10. 验收标准

- 根目录不再散放 MATLAB、项目背景和工作流 Markdown；
- Python、MATLAB、C++ 和 Web 位于四个独立代码目录；
- 每个代码目录有明确 README；
- 项目、纠错、计划、规格、研究、环境和交接文档分类明确；
- 根 README 能让新用户和 agent 在三分钟内找到目标文件与运行入口；
- Python 全量测试通过；
- Web 后端测试通过；
- C++ 动态库能从新路径加载；
- MATLAB 入口能定位全部依赖；
- 所有被跟踪 Markdown 相对链接有效；
- `rg` 不再发现旧路径依赖；
- smoke 和 formal 结果不混放；
- Git 暂存区不包含秘密、编译产物或无关用户文件。

## 11. 风险与控制

### 路径依赖遗漏

**信号：** 测试收集失败、脚本找不到包、Web 后端无法导入。
**控制：** 移动前生成旧路径引用清单；每阶段移动后再次扫描。

### 正式计算仍使用旧目录

**信号：** Legion 日志或 manifest 记录旧脚本路径。
**控制：** 当前求解器正式结果先完成验收；迁移后所有新任务使用新路径，不重写旧结果 provenance。

### 文档秘密进入 Git

**信号：** 环境文档出现密码、token、私钥或完整认证命令。
**控制：** 文档迁移前秘密扫描；敏感文件保留本机并加入忽略规则。

### Git 历史难以审查

**信号：** 大量移动和内容改写混在同一提交。
**控制：** 先纯移动，再单独修复路径和 README；使用阶段提交。

### 结果证据等级误判

**信号：** 3-trial smoke 被放入 formal。
**控制：** 只有 manifest、配置和预算均满足正式标准的结果可进入 `formal/`。

## 12. 非目标

- 本次不修改科学模型、特征定义、参数边界或验收阈值；
- 本次不启动新的正式 TPE；
- 本次不重写历史结果；
- 本次不安装或升级依赖；
- 本次不把仓库外的全局 agent 配置迁入项目；
- 本次不将编译产物加入 Git。
