# DeepSeek 计算交付与验收协议

> 适用范围：DeepSeek/Claude Code 在 Legion 上执行 OER-FTAcV 计算。
> 目标：允许其他 Agent 用少量上下文复核、接续或否决计算结果。
> 原则：DeepSeek 负责执行和留痕，不负责修改科学标准或宣布项目结论。

## 1. 职责边界

DeepSeek 可以：

- 按冻结的任务规格运行已有脚本；
- 执行预先列出的 smoke、formal 和验收命令；
- 收集环境、日志、状态、文件哈希和统计摘要；
- 报告基础设施失败、数值失败或验收门结果。

DeepSeek 不可以：

- 自行修改模型、参数边界、随机种子、采样规模、容差或验收阈值；
- 为使结果通过而删除异常样本、重跑部分 seed 或选择性汇报；
- 用日志片段、截图或口头总结替代原始文件；
- 将 smoke 结果写入 formal 目录；
- 将“命令退出码为 0”等同于科学验证通过；
- 未经 Codex 或用户验收就更新项目科学结论。

任何未授权变更均使该次运行无效，必须保留证据并重新建立任务。

## 2. 任务冻结

计算前必须建立不可变任务规格 `TASK_SPEC.yaml`，至少包含：

```yaml
task_id: "<commit_short>/<task_name>/<run_id>"
purpose: "<本次计算只回答的一个问题>"
stage: "smoke | formal"
git_commit: "<40位commit>"
git_dirty_allowed: false
entrypoint: "<相对仓库路径>"
config_files:
  - path: "<相对仓库路径>"
    sha256: "<哈希>"
arguments: []
environment:
  python: "<绝对解释器路径>"
  workers: 8
  blas_threads_per_worker: 1
randomness:
  seeds: []
expected_outputs: []
structural_gates: []
numerical_gates: []
scientific_gates: []
stop_conditions: []
```

冻结规则：

1. `git_commit` 必须存在于 Git；formal 默认要求工作树干净。
2. task spec、配置文件和运行脚本均计算 SHA-256。
3. smoke 与 formal 使用不同 `run_id` 和输出目录。
4. formal 必须引用已通过的 smoke `run_id`、spec hash 和 commit。
5. 修改任何冻结字段都必须创建新 `run_id`，不得编辑旧运行目录。

## 3. 唯一运行目录

每次运行写入：

```text
results/<stage>/<task_name>/<run_id>/
├── TASK_SPEC.yaml
├── STATUS.json
├── MANIFEST.json
├── HANDOFF.md
├── provenance/
│   ├── git.json
│   ├── environment.json
│   ├── command.json
│   └── inputs.sha256
├── logs/
│   ├── stdout.log
│   ├── stderr.log
│   └── events.jsonl
├── raw/
├── derived/
├── validation/
│   ├── validation.json
│   ├── validation.log
│   └── outputs.sha256
└── failure/
    └── failure.json
```

规则：

- `run_id` 使用 `YYYYMMDD_HHMMSS-<commit_short>-<spec_hash8>`。
- 目录创建后禁止覆盖；重跑必须创建新目录。
- 原始结果进入 `raw/`，后处理结果进入 `derived/`。
- 日志只追加，不截断。每条事件包含 UTC 时间、阶段、命令和返回码。
- 临时文件先写入同目录，再原子重命名。
- 大文件可以不提交 Git，但必须保留路径、大小和 SHA-256。
- Mac 归档保持相同目录结构；同步不得覆盖已有归档。

## 4. 必需状态文件

`STATUS.json` 是接续入口，只允许以下终态：

```text
SUCCESS
FAIL_INFRA
FAIL_NUMERICAL
FAIL_STRUCTURE
FAIL_SCIENTIFIC
INTERRUPTED
```

至少包含：

```json
{
  "schema_version": 1,
  "task_id": "...",
  "run_id": "...",
  "stage": "formal",
  "status": "FAIL_NUMERICAL",
  "git_commit": "...",
  "spec_sha256": "...",
  "pid": 1234,
  "started_at": "...Z",
  "finished_at": "...Z",
  "exit_code": 2,
  "output_dir": "...",
  "failed_gate": "finite_values",
  "error_summary": "12 rows contain non-finite loss",
  "next_action": "STOP_AND_REVIEW"
}
```

状态规则：

- 启动时写 `STARTING`，子进程建立后写 `RUNNING`。
- 进程结束必须写终态；缺失终态按 `INTERRUPTED` 处理。
- 基础设施、数值、结构和科学失败必须分开。
- 任何必需文件缺失、JSON 损坏或哈希不符，均不得标记 `SUCCESS`。
- `SUCCESS` 只表示预先声明的全部验收门通过。

## 5. Provenance 与数据留痕

`provenance/git.json`：

- commit、branch、dirty 状态；
- dirty 时保存完整 `git diff --binary` 的路径和哈希；
- 子模块版本（如有）。

`provenance/environment.json`：

- OS、WSL kernel、CPU、逻辑线程数；
- Python、NumPy、SciPy、Optuna 和编译库版本；
- BLAS 后端、线程环境变量；
- C++/Fortran 动态库绝对路径、文件大小、mtime 和 SHA-256；
- locale、timezone 和关键环境变量；不得记录密码、token 或私钥。

`provenance/command.json`：

- 原始 argv 数组，不只保存拼接字符串；
- 工作目录、解释器、worker 数；
- 开始与结束时间、退出码；
- systemd unit 名称及完整 `ExecStart`。

`MANIFEST.json`：

- 列出所有交付文件的相对路径、类型、字节数和 SHA-256；
- 标明 `raw`、`derived`、`log`、`validation`；
- 记录生成者和生成时间；
- manifest 自身不包含自己的哈希。

## 6. 严格验收顺序

必须按顺序执行。前一层失败后停止，不得继续科学解释。

### Gate 0：身份与不可变性

- task ID、run ID、commit 和 spec hash 一致；
- formal 工作树干净；
- 输入、配置、脚本和动态库哈希匹配；
- 没有复用或覆盖旧目录。

失败：`FAIL_INFRA` 或 `FAIL_STRUCTURE`。

### Gate 1：运行完整性

- systemd 状态与 `STATUS.json` 一致；
- 有开始、结束时间和退出码；
- stdout、stderr、事件日志齐全；
- 没有 OOM、被回收、磁盘满、SSH 中断导致的假完成；
- 预期输出全部存在。

失败：`FAIL_INFRA`。

### Gate 2：结构与数据完整性

- 文件数量、CSV/JSON schema、列名、类型和行数符合规格；
- 样本、seed、模式、谐波和参数组合无缺失、无意外重复；
- 所有 manifest 哈希可复算；
- raw 与 derived 的来源关系明确。

失败：`FAIL_STRUCTURE`。

### Gate 3：数值有效性

- 必须字段均为有限值；
- 求解器状态、收敛标志和失败计数满足固定阈值；
- 边界命中、异常步数、积分警告和重试次数完整报告；
- 不允许静默删除失败样本；
- 与 smoke 或参考实现的数值一致性满足预设阈值。

失败：`FAIL_NUMERICAL`。

### Gate 4：科学门

- 只使用 `TASK_SPEC.yaml` 中预先声明的指标和阈值；
- 报告全部 seed、重复和负面结果；
- 同时给出效应量、离散度和失败比例；
- 不得事后改变阈值或只选择有利子集；
- 未达到门槛时保留结果并标记 `FAIL_SCIENTIFIC`。

通过 Gate 0–4 才允许 `SUCCESS`。

## 7. DeepSeek 交付格式

DeepSeek 最终回复只提供：

```text
run_id:
status:
git_commit:
spec_sha256:
output_dir:
manifest_sha256:
validation_file:
failed_gate:
one_line_summary:
next_action:
```

禁止在回复中粘贴大段日志或自行扩展科学结论。详细证据必须写入运行目录。

`HANDOFF.md` 控制在 120 行以内，只包含：

1. 本次任务问题；
2. 实际执行的 commit、命令和配置；
3. 终态及失败门；
4. 关键输出路径；
5. 与任务规格的偏差；
6. 尚未验证的事项；
7. 下一 Agent 应执行的唯一下一步。

## 8. Codex 接续顺序

为减少用量，Codex 后续只按以下顺序读取：

1. `HANDOFF.md`
2. `STATUS.json`
3. `validation/validation.json`
4. `MANIFEST.json`
5. `TASK_SPEC.yaml`
6. 仅在失败或冲突时读取相关日志和原始数据

Codex 必须独立复算：

- spec、输入、动态库和输出哈希；
- schema、行数、唯一组合和有限值；
- 至少一个固定样本或一个汇总指标；
- 科学门使用的指标，不接受 DeepSeek 的文字判断代替。

Codex 不重复完整计算，除非哈希不一致、抽查失败或任务规格要求独立复算。

## 9. 拒收条件

出现任一项立即拒收：

- 没有 `TASK_SPEC.yaml`、`STATUS.json`、`MANIFEST.json` 或 `HANDOFF.md`；
- commit、spec hash、输入哈希或动态库哈希缺失/不一致；
- formal 使用 dirty 工作树且任务未明确允许；
- 修改阈值、种子、参数边界或过滤规则但未建立新 run；
- 输出目录被覆盖，无法区分多次运行；
- 只有截图、终端摘要或手写表格，没有原始数据；
- `SUCCESS` 与 systemd、退出码、日志或 validation 冲突；
- 缺失失败样本，或失败样本被静默排除；
- smoke 证据与 formal 的 commit/spec hash 不匹配；
- 结果无法在 Mac 归档中定位。

拒收不是删除。所有失败证据必须保留，用于定位根因。

## 10. 压力测试

执行协议前，用以下场景检查实现：

| 场景 | 必须结果 |
|---|---|
| SSH 断开但 systemd 继续运行 | 状态保持 `RUNNING`，断连不记计算失败 |
| WSL/进程被回收 | 最终为 `INTERRUPTED` 或 `FAIL_INFRA` |
| 求解器部分样本失败 | 保留全部样本，最终为 `FAIL_NUMERICAL` |
| 计算退出码为 0但缺文件 | `FAIL_STRUCTURE`，不得 `SUCCESS` |
| 哈希不一致 | 停止科学验收并拒收 |
| smoke 与 formal 配置不一致 | formal 不得启动 |
| 同一任务重跑 | 新建 run ID，不覆盖旧结果 |
| validation 阈值被修改 | 新 spec hash 和新 run ID |
| DeepSeek 声称通过但复算失败 | 以独立验收为准，保留冲突证据 |
| Mac 同名归档已存在 | 拒绝覆盖 |

## 11. 首次落地要求

在下一次 DeepSeek 计算前完成：

1. 为任务生成冻结的 `TASK_SPEC.yaml`。
2. 用一个最小 smoke 验证目录、状态、manifest 和哈希生成。
3. 人为制造一次退出码 2、一次缺文件和一次哈希不符。
4. 确认三种失败分别被正确分类，且不会启动 formal。
5. Codex 验收 smoke 后，才允许 DeepSeek 执行正式任务。
