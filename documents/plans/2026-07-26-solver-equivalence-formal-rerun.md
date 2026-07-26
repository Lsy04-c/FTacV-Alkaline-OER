# Gate A3 Solver Equivalence Formal Rerun Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Legion 上重新生成可追溯的 CN–LSODA 正式等价性证据，并按预注册门控关闭或拒绝 Gate A3。

**Architecture:** Mac 负责计划、验收、文档和 Git；Legion
`/home/lsy/OER-FTAcV` 固定在科学提交 `1becc125311e008cd00831875c7be195891f6554`
执行。远端使用 `setsid` 脱离 SSH，会话状态由日志、PID、退出码和
provenance 文件共同判定，不再把 tmux 会话存在作为成功条件。

**Tech Stack:** Python 3.11、NumPy、SciPy、C++ CN 动态库、CSV/JSON、Git、SSH/WSL2。

---

## 固定验收配置

| 项目 | 固定值 |
|---|---|
| 科学提交 | `1becc125311e008cd00831875c7be195891f6554` |
| 样本数 | 24 |
| 随机种子 | 17 |
| 周期数 | 256 |
| 每周期点数 | 128 |
| 谐波 | H1–H7 |
| 可解析性阈值 | 最强参考通道的 2% |
| 远端输出 | `/home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12/` |
| Mac 正式结果 | `results/formal/solver_equivalence/formal-1becc12/` |

不得调整阈值。Gate FAIL 时停止正式 TPE；只有明确的基础设施失败才允许按同一配置重跑。

### Task 1: 冻结远端环境与科学输入

**Files:**
- Read: `/home/lsy/OER-FTAcV/scripts/validate_solver_equivalence.py`
- Read: `/home/lsy/OER-FTAcV/python/oer_aem/inversion.py`
- Read: `/home/lsy/OER-FTAcV/cpp/liboercn.so`
- Create remotely: `/home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12/run_manifest.json`

- [ ] **Step 1: 验证工作树**

Run on Legion:

```bash
git -C /home/lsy/OER-FTAcV rev-parse HEAD
git -C /home/lsy/OER-FTAcV diff --exit-code -- \
  python/oer_aem/inversion.py scripts/validate_solver_equivalence.py
```

Expected: commit 精确等于固定值，科学文件无差异。

- [ ] **Step 2: 验证解释器和动态库**

Run on Legion:

```bash
cd /home/lsy/OER-FTAcV
.venv/bin/python --version
.venv/bin/python -c \
  'import numpy, scipy, optuna; print(numpy.__version__, scipy.__version__, optuna.__version__)'
file cpp/liboercn.so
sha256sum cpp/liboercn.so scripts/validate_solver_equivalence.py
```

Expected: Python 和依赖可导入，动态库为 Linux x86-64 ELF。实际版本必须原样写入 manifest，不安装或切换 NumPy。

- [ ] **Step 3: 写入 provenance**

`run_manifest.json` 必须包含：

```json
{
  "source_commit": "1becc125311e008cd00831875c7be195891f6554",
  "samples": 24,
  "seed": 17,
  "cycles": 256,
  "points_per_cycle": 128,
  "resolvability_fraction": 0.02,
  "python_version": "3.11.2",
  "numpy_version": "2.4.6",
  "scipy_version": "1.17.1",
  "optuna_version": "4.9.0",
  "library_sha256": "b40172f8a2f8f4a202a04e82d92f6da8e633b159de2c0d0b54831284cd644bef",
  "script_sha256": "5c8622e0d23e0c10b830bc999350ff6881d0ee54599ab3742f46a8acc16a34b1",
  "started_at_cst": "${STARTED_AT_CST}",
  "command": ".venv/bin/python scripts/validate_solver_equivalence.py --samples 24 --seed 17 --cycles 256 --points-per-cycle 128 --output-dir results/solver_equivalence/formal-1becc12"
}
```

### Task 2: 验证入口与断连持久性

**Files:**
- Temporary remote output: `/tmp/oer-solver-equivalence-smoke/`
- Temporary remote marker: `/tmp/oer-setsid-marker`

- [ ] **Step 1: 运行单样本 smoke**

```bash
cd /home/lsy/OER-FTAcV
.venv/bin/python scripts/validate_solver_equivalence.py \
  --samples 1 --seed 17 --cycles 8 --points-per-cycle 128 \
  --output-dir /tmp/oer-solver-equivalence-smoke
```

Expected: 7 个谐波行，summary 和 CSV 可读取。该结果不得进入 formal。

- [ ] **Step 2: 验证 SSH 断连后的进程存活**

```bash
rm -f /tmp/oer-setsid-marker
setsid -f bash -lc \
  'sleep 5; date +%Y-%m-%dT%H:%M:%S%z > /tmp/oer-setsid-marker'
```

断开并重新 SSH 后检查：

```bash
test -s /tmp/oer-setsid-marker
```

Expected: marker 存在。该 smoke 只证明 SSH 断连存活，不证明 Windows 重启后存活。

### Task 3: 启动正式计算

**Files:**
- Create remotely: `formal_run.log`
- Create remotely: `formal_run.pid`
- Create remotely after termination: `formal_run.exit_code`

- [ ] **Step 1: 排除重复进程和旧完成标记**

```bash
pgrep -af 'validate_solver_equivalence.py.*formal-1becc12' || true
test ! -e results/solver_equivalence/formal-1becc12/formal_run.exit_code
```

Expected: 无同配置运行进程、无旧退出码。若存在，先只读核实，不并发启动。

- [ ] **Step 2: 用 `setsid` 启动**

启动包装命令必须：

1. 记录 shell PID；
2. 执行固定正式命令；
3. 无论 PASS、FAIL 或 Python 异常，都写入真实退出码；
4. stdout/stderr 全部进入 `formal_run.log`。

- [ ] **Step 3: 启动后复验**

重新 SSH 后检查：

```bash
cat results/solver_equivalence/formal-1becc12/formal_run.pid
pgrep -af 'validate_solver_equivalence.py.*formal-1becc12'
tail -n 20 results/solver_equivalence/formal-1becc12/formal_run.log
```

Expected: 进程存在，日志出现 `sample 1/24` 或后续样本。

### Task 4: 每 20 分钟监控但不干预

- [ ] **Step 1: 读取北京时间**

检查前必须读取北京时间；距上次真实远端检查不足 20 分钟时不访问远端。

- [ ] **Step 2: 检查四种状态**

| 状态 | 判定 |
|---|---|
| RUNNING | PID/进程存在，日志继续增加，无退出码 |
| PASS candidate | 退出码 0，summary `passed=true` |
| SCIENTIFIC FAIL | 退出码 2，summary `passed=false` |
| INFRASTRUCTURE FAIL | 其他退出码，或进程消失且无退出码/完整结果 |

不得以 tmux 会话是否存在判定计算状态。

### Task 5: 验收正式证据

**Files:**
- Read remotely: `solver_equivalence.csv`
- Read remotely: `solver_equivalence_summary.json`
- Read remotely: `run_manifest.json`

- [ ] **Step 1: 验收结构**

必须满足：

- CSV 恰好 168 行（24 samples × 7 harmonics）；
- 24 个唯一样本，每个样本 H1–H7 各一行；
- 列集合与脚本 `CSV_FIELDS` 完全一致；
- 所有要求评价的指标均为有限值；
- `lsoda_success` 和 `cn_success` 全为真；
- summary 的 `n_rows=168`；
- summary 配置与固定验收配置一致；
- manifest 的 commit、环境、脚本和动态库哈希存在。

- [ ] **Step 2: 应用预注册门**

PASS 仅由脚本既定 `assess_gate()` 决定，不删除失败行、不调整阈值、不事后改变可解析性规则。

- [ ] **Step 3: 分支决策**

- PASS：允许 CN 进入候选搜索，但所有入选参数仍由 LSODA 复算。
- SCIENTIFIC FAIL：Gate A3 关闭为 FAIL，停止正式 TPE。
- INFRASTRUCTURE FAIL：保留日志和 provenance，修复基础设施后按原配置重跑。

### Task 6: 同步、文档、测试与 Git

**Files:**
- Create: `results/formal/solver_equivalence/formal-1becc12/`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`

- [ ] **Step 1: 同步结果到 Mac**

只同步本阶段 summary、CSV、manifest 和日志，不同步临时 smoke。

- [ ] **Step 2: 更新项目状态**

记录北京时间、配置、环境版本、commit、门结果、失败项和下一步决策。不得把基础设施失败写成科学 FAIL。

- [ ] **Step 3: 验证**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python -m pytest code/web/tests/backend -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

- [ ] **Step 4: 提交并推送**

只提交 Gate A3 正式证据与对应文档；不得提交 `/tmp` smoke、动态库、秘密环境信息或其他阶段结果。

## 压力测试结论

1. **环境漂移：** 当前 Legion 实测 NumPy/SciPy 与旧文档不同。允许使用已有环境，但必须记录；不允许无记录地宣称复现旧环境。
2. **持久化：** tmux 已发生会话与输出同时消失，不能再作为唯一证据。`setsid` 已通过一次断连 marker smoke；仍无法抵抗 Windows 重启，因此日志和无退出码状态必须区分为基础设施失败。
3. **路径迁移：** 科学运行固定在旧目录结构的 `1becc12`；结果回传后映射到 Mac 新目录 `results/formal/`。不得在远端运行迁移后的分类提交冒充固定科学提交。
4. **可追溯性：** 原脚本 summary 不记录依赖、动态库和源码哈希，必须用独立 manifest 补齐。
5. **重复启动：** 正式命令串行且耗时；启动前用进程与退出码双重检查，避免两个相同作业写同一目录。
6. **判定边界：** 退出码 2 是科学 FAIL；进程无退出码消失是基础设施 FAIL。两者必须分开。
