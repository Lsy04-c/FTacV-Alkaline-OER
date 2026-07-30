# oer-wf 冻结环境验收设计

状态：待项目负责人确认
版本目标：`oer-wf 0.7.0`
范围：修复 `wf verify` 的提交、平台、环境和验收留痕；不修改科学阈值。

## 1. 问题

当前 `wf verify` 在 Mac 当前仓库执行所有 validator。正式计算却来自 Legion
冻结 worktree。由此产生四类错误：

1. 当前 HEAD 与计算 commit 不同，provenance 门误报结构失败；
2. ARM64 Mac 与 x86-64 Legion 的浮点末位不同，精确重建产生假阴性；
3. 手工回到 Legion 验证时容易漏掉 OMP/OpenBLAS/MKL/NumExpr 环境；
4. validator 若在原归档写 acceptance，会覆盖历史证据。

V4.1 已复现全部问题：Mac 矩阵重建相差约 `1e-14`；Legion 未恢复线程
环境时 baseline 最大相对漂移约 `4.55e-5`；恢复冻结环境后 8/8 复算通过。

## 2. 方案比较

### A. 在 Mac 放宽浮点容差

工程量小，但不能解决 commit、平台、线程和刚性 ODE 路径差异。拒绝。

### B. 所有 validator 都在 Legion 运行

实现简单，但会放弃 Mac 对同步后文件的独立传输检查。拒绝。

### C. 本地完整性 + 远端科学复算

Mac 只验证同步归档的文件、schema、有限值、provenance 和哈希；TaskSpec
指定的科学 validator 在原 Legion、冻结 worktree 和冻结环境中运行。
采用此方案。

## 3. 冻结契约

TaskSpec 的 `validator_config.<name>` 增加编排字段：

```yaml
validator_config:
  v4_experiment_design_gate:
    execution: remote_worktree
    timeout_sec: 1800
    project_root: "."
    task_spec: "config/experiment-design/v4-computational-design.json"
    rerun_selected_smoke: false
    rerun_selected_formal: true
```

- `execution` 只允许 `local` 或 `remote_worktree`，默认 `local`；
- `timeout_sec` 为 1–3600 秒，默认 600；
- 编排层移除 `execution` 和 `timeout_sec` 后，才把其余配置交给 validator；
- snapshot 新增 `env`、`python` 和 `worktree_root`，用于恢复验证环境；
- snapshot 必须保存完整 commit，不允许只保存短哈希；
- TaskSpec 环境键不得包含 `TOKEN`、`PASSWORD`、`SECRET`、`PRIVATE_KEY`
  等秘密名称；秘密继续由系统凭据管理，不进入任务规格或归档。

缺少上述字段的旧 snapshot 继续按原本地模式处理，不猜测远端环境，也不
修改历史归档。旧正式结果需要远端复核时，沿用已有人工 acceptance，不把
当前可变 TaskSpec 注入旧归档。

## 4. 验证流程

```text
Mac immutable archive
  │
  ├─ 本地：expected files / schema / finite / provenance / hashes
  │
  └─ 远端科学 validator
       ├─ 从本地 STATUS.output_dir 恢复远端正式目录
       ├─ 校验目录位于冻结 worktree 内且时间戳一致
       ├─ 校验远端 HEAD 等于 snapshot commit
       ├─ 拒绝 tracked source diff 和非运行时脏文件
       ├─ 恢复 snapshot env
       ├─ 从冻结 worktree 加载科学脚本与配置
       └─ 只向 stdout 返回结构化 JSON
```

远端命令使用 base64 JSON 载荷和安全参数引用，不拼接未经校验的路径。
科学 validator 不写远端或 Mac 计算归档。

## 5. 结果与留痕

`wf verify` 返回统一 JSON，并在计算归档之外原子写入追加式 receipt：

```text
~/OER-FTAcV-archive/verifications/
  <commit_short>/<task_name>/<result_timestamp>/
  <UTC>-<receipt_hash>.json
```

receipt 至少包含：

- oer-wf 版本；
- task ID、完整 commit、snapshot hash；
- 本地归档路径和 expected-file tree hash；
- 远端 host 别名、worktree、结果目录；
- 环境键名与环境内容哈希，不保存秘密正文；
- validator 名称、执行位置、耗时、checks 和最终 fail type。

同一输入可重复验证，但不得覆盖旧 receipt。计算归档保持不可变。

## 6. 失败分类

| 失败 | 分类 |
|---|---|
| SSH、超时、远端目录不存在 | `transport` |
| 冻结 worktree/解释器/环境不可用 | `environment` |
| commit、路径、snapshot、schema、文件集合不一致 | `structure` |
| ODE、非有限值、复算数值不一致 | `numerical` |
| 结构与数值均有效但预注册科学门未通过 | `scientific` |

项目 validator 必须按返回 gate 生成对应 check 前缀，不能把
`FAIL_NUMERICAL` 包装为 `structure:*`。

## 7. 安全与退出条件

- 远端路径必须位于
  `<WSL_MAIN_REPO>/<worktree_root>/<commit_short>/<task_name>/`；
- 远端正式目录 basename 必须等于本地归档时间戳；
- commit 或环境契约不一致时停止，不自动 checkout、安装依赖或改阈值；
- SSH 超时后不猜测科学状态；
- 远端验证失败不删除计算结果，不自动重跑正式计算；
- receipt 写入失败时返回 `transport`，不得声称验收完成。

## 8. 测试与完成标准

先写失败测试，再实现：

1. snapshot 冻结并校验 env、python、worktree 和远端执行配置；
2. 本地 validator 不触发 SSH；
3. 远端 validator 恢复 env、完整 commit 和正确结果目录；
4. commit、路径越界、tracked diff、超时、无效 JSON 分别正确失败；
5. `FAIL_NUMERICAL` 与 `scientific` 分类不混淆；
6. verify 前后计算归档 tree hash 不变；
7. receipt 追加且不覆盖；
8. 既有本地 TaskSpec 和 101 项工作流测试保持兼容；
9. Mac 全量测试通过；
10. Legion 部署后运行一次新 commit V4 smoke，完成
    `run/sync/verify`，证明冻结远端 validator 和 receipt 闭环。

完成本规格不代表任何科学 Gate 自动通过。
