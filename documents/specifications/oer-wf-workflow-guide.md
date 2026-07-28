# oer-wf 可复用计算工作流 — 使用指南

> 版本：0.6.5 | 57 个工作流测试通过 | 冻结验收契约与A6科学门 | 2026-07-29

## 1. 这是什么

`oer-wf` 是 OER-FTAcV 项目的轻量级 Python CLI（位于 `config/oer-wf/`），把重复的工程步骤封装为结构化命令。每个命令输出 JSON（`status` + `next_action`），Agent 可直接 parse 推进，不再手工拼 SSH 命令。

**核心原则**：工程步骤可复用，科学判断不自动化。

---

## 2. 环境要求

### Mac 端
- Python ≥ 3.11，项目 venv：`/Users/liushiyu/OER-FTAcV/.venv`
- SSH：`~/.ssh/config` 含 `Host legion`，经 ForceCommand + Shim 直达 WSL bash
- 归档目录：`~/OER-FTAcV-archive/results/`

### Legion 远程
- WSL2 Debian Bookworm，systemd PID 1，`linger=yes`
- `user@1000.service` 开机自启（`multi-user.target.wants/` symlink）
- `WSL-Keeper` 计划任务保活 VM（`wsl sleep 86400`）
- `vmIdleTimeout=-1`
- 项目主仓库：`/home/lsy/OER-FTAcV`，虚拟环境：`.venv`
- rsync 3.2.7，oer-wf 已安装到项目 venv
- SSH 详情：`config/oer-wf/docs/ssh_setup.md`

### SSH 连通性验证
```bash
ssh legion "whoami && uname -a"
# 预期：lsy / Linux ... WSL2 / /bin/bash
```

---

## 3. 安装

```bash
cd /Users/liushiyu/OER-FTAcV/config/oer-wf
pip install -e ".[dev]" --trusted-host pypi.org --trusted-host files.pythonhosted.org --no-build-isolation
```

验证：
```bash
wf --version   # 0.6.5
pytest -q      # 49 passed
```

远程 Legion 端（`wf run/smoke` 依赖）：
```bash
rsync -avz --exclude '__pycache__' config/oer-wf/ legion:/home/lsy/oer-wf/
ssh legion "/home/lsy/OER-FTAcV/.venv/bin/pip install -e /home/lsy/oer-wf --trusted-host pypi.org --trusted-host files.pythonhosted.org"
```

---

## 4. 全局配置

`oer_wf/config.py`，均可环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SSH_HOST` | `legion` | SSH 别名 |
| `SSH_USER` | `lsy` | SSH 用户 |
| `WSL_MAIN_REPO` | `/home/lsy/OER-FTAcV` | WSL 主仓库 |
| `MAC_ARCHIVE_ROOT` | `~/OER-FTAcV-archive` | Mac 归档根目录 |

---

## 5. 通用 JSON 响应结构

每个命令 stdout 只输出 JSON：
```json
{
  "status": "pass | fail | warning | running",
  "fail_type": "environment | transport | structure | numerical | scientific | null",
  "checks": [{"name": "...", "passed": true, "detail": "..."}],
  "data": {},
  "next_action": "下一步操作",
  "message": "人类可读摘要"
}
```

Agent 只解析 JSON，根据 `status` 和 `next_action` 推进。

---

## 6. 命令参考

### 6.1 `wf doctor` — 只读环境检查
检查 SSH、时钟偏差、主仓库、Git、Python、rsync、systemd。
```bash
wf doctor
```
`pass` → 继续 | `warning` → 可继续 | `fail` → 先修复

### 6.2 `wf prepare <spec>` — 准备工作树
创建 commit 专属 git worktree + `.wf_lock`。三态：create / reuse / conflict。
```bash
wf prepare examples/solver_equiv_01.yaml
```

### 6.3 `wf smoke <spec>` — 小规模测试
从 task_spec 派生安全 overrides，执行小规模运行 + 结构验收。
```bash
wf smoke examples/solver_equiv_01.yaml
```

### 6.4 `wf run <spec> [--force|--resume-timestamp]` — 正式计算
启动 systemd 用户服务。active 时默认拒绝，`--force` 新时间戳目录。
只有声明 `supports_resume: true` 的任务可以恢复指定历史目录：
```bash
wf run examples/solver_equiv_01.yaml
wf run examples/solver_equiv_01.yaml --force
wf run examples/a6_recovery_reduced.yaml --resume-timestamp 20260729_010203
```
输出：`<output_dir>/<YYYYMMDD_HHMMSS>/`

续跑不会创建新目录。runner 必须验证原计划指纹和每个 job 的输入哈希；缺少计划、
配置或 commit 不一致、结果损坏时均拒绝。`--force` 与
`--resume-timestamp` 不能同时使用。

### 6.5 `wf status <task_id>` — 查询状态
systemd ∩ STATUS.json 双通道。冲突 → `inconsistent`。
```bash
wf status 1becc12/solver_equiv_01
```

| systemd | STATUS | 综合判定 |
|---------|--------|----------|
| active | RUNNING | `running` |
| inactive | SUCCESS | `pass` → `wf sync` |
| inactive | FAIL_* | `fail` |
| active | 终态 | `inconsistent` |

### 6.6 `wf sync <task_id>` — 结果同步
rsync 拉取最新正式结果到 Mac 归档。目标已存在 → 拒绝覆盖。
```bash
wf sync 1becc12/solver_equiv_01
```
归档结构：
```
~/OER-FTAcV-archive/results/<commit_short>/<task_name>/<YYYYMMDD_HHMMSS>/
```

### 6.7 `wf verify <task_id>` — 通用验收
只读本地归档。验收契约来自同目录 `task_spec.snapshot.yaml`，该文件由
`wf run` / `wf smoke` 在计算启动前写入。没有 snapshot 的旧归档必须显式
提供全部 `--expected-file` 和 `--validator`；否则以
`verification contract unavailable` 判为 structure FAIL，不再默认套用 CSV。
任务可声明 `recovery_gate` 等专用验收器，科学门失败时
`fail_type=scientific`。
```bash
wf verify 1becc12/solver_equiv_01
```

### 6.8 `wf git-check` — 交付检查
变更范围 + pytest + commit 草稿。**不自动 commit。**
```bash
wf git-check
wf git-check --no-tests
```

### 6.9 `wf clean <task_id> [--force] [--keep-results]` — 清理
| 模式 | 行为 |
|------|------|
| 默认 | 停止 unit + 删 lock + `_smoke_*` 临时文件 |
| `--force` | 同时删除 worktree |
| `--keep-results` | 保留结果目录 |

```bash
wf clean 1becc12/solver_equiv_01 --force
```

---

## 7. 典型工作流

```bash
wf doctor                                         # 1. 环境检查
wf prepare examples/solver_equiv_01.yaml           # 2. 准备工作树
wf smoke examples/solver_equiv_01.yaml             # 3. 小规模测试
wf run examples/solver_equiv_01.yaml               # 4. 启动正式计算
wf status 1becc12/solver_equiv_01                  # 5. 轮询直到终态
wf sync 1becc12/solver_equiv_01                    # 6. 同步结果到 Mac
wf verify 1becc12/solver_equiv_01                  # 7. 验收
wf git-check                                       # 8. 交付检查
git commit -m "..." && git push                    # 9. 人工确认提交
```

---

## 8. task_spec.yaml 格式

```yaml
task_name: "solver_equiv_01"          # 唯一任务名
commit: "1becc125311e008cd00831875c7be195891f6554"
description: "求解器等价性验证"

python:
  source: "main_repo"                 # main_repo | worktree
  path: ".venv/bin/python"

worktree_root: "worktrees"

env:
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"

build:
  required: false
  source: "code/cpp"
  command: "cmake --build code/cpp/build --config Release"
  expected_artifact: "liboercn"

script: "scripts/run_solver_equiv.py"
supports_resume: false
args:
  - "--config"
  - "configs/solver_equiv.yaml"
workers: 4
output_dir: "results/solver_equiv_01"

smoke:
  enabled: true
  overrides:
    n_samples: 2
    max_steps: 50
  expected_files:
    - "summary.csv"
    - "manifest.json"

expected_files:
  - "summary.csv"
  - "manifest.json"
  - "STATUS.json"
validators:
  - schema_check
  - finite_check
  - provenance
  - manifest_hash
```

**强制规则**：
- 所有路径为相对路径（worktree root 下）
- `--output` 和 `--workers` 由 wf 注入，args 不可含
- `task_id = <commit_short>/<task_name>` 自动推导
- `python.source=main_repo` → 用主仓库 venv；`worktree` → 用 worktree 内 venv

---

## 9. 工程规则与安全门

### 五个安全门（v0.6.5）

| # | 安全门 | 说明 |
|---|--------|------|
| 1 | **clean 保护结果** | `--force --keep-results` 先将 `results/` 迁移到 `<主仓库>/_wf_preserved_results/`，迁移成功后才删 worktree；迁移失败 → 拒绝删除 |
| 2 | **smoke gate + spec_hash** | `wf run` 默认要求存在 `_smoke_*/STATUS.json`，`status=SUCCESS` **且 `spec_hash` 与当前 spec 一致**；仅 `--skip-smoke` 可显式绕过。spec_hash 由 `wf smoke/run` 通过环境变量 `OER_WF_SPEC_HASH` 注入 systemd unit，wrapper 写入 STATUS.json |
| 3 | **路径校验** | `script` / `output_dir` / `worktree_root` / `python.path` 拒绝绝对路径、`..` 和 `~` |
| 4 | **smoke override 白名单** | 默认拒绝未知 override key；仅允许 `n_samples` / `max_steps` / `max_iter` / `timeout` / `debug`；`solver_backend` / `points_per_cycle` 等科学参数一律拦截 |
| 5 | **显式断点续跑** | 仅 `supports_resume: true` 可使用 `--resume-timestamp`；精确复用历史目录，runner 校验 commit、dirty状态、科学配置、job集合、输入哈希及JSONL完整性 |

### 通用工程规则

1. **幂等** — prepare 可重复运行；run 默认不重复
2. **历史保护** — `--force` 只建新目录，不覆盖
3. **失败分类** — infrastructure ≠ scientific
4. **双通道** — systemd + STATUS.json，不猜成功
5. **smoke gate** — 未通过 smoke 不允许 run
6. **不自动 commit** — git-check 只生成草稿
7. **续跑不混证据** — workers可调整；科学配置、源码或job输入变化立即拒绝

---

## 10. 已知注意事项

- **`.resolve()` bug（已修复）**：`runtime/command.py` 中 `.resolve()` 会在 macOS 上把 `/home` 解析为 `/System/Volumes/Data/home`。当前版本所有远程路径不使用 `.resolve()`。
- **JSON 双引号（已修复）**：`prepare.py` 中 `.wf_lock` 经 SSH→PowerShell 会丢失双引号。已改用 base64 编码传输。
- **openrsync**：Mac 自带 rsync 不支持 `--info=progress2`。`transport.py` 已移除。
- **`doctor` systemd degraded（v0.6.1 修复）**：`running` 和 `degraded` 均视为可用；degraded 仅记 warning。
- **spec_hash 端到端闭环（v0.6.3 修复）**：`wf smoke/run` 通过 `OER_WF_SPEC_HASH` 环境变量注入 systemd unit，wrapper 写入 STATUS.json，smoke gate 读取并比对。旧版 STATUS.json 缺 spec_hash 会导致 run 被拒绝。
- **sync 路径层级（v0.6.3 修复）**：ExecStart 提取的完整时间戳路径直接用作远程结果目录，不再被误当作 `output_base` 二次查找子目录。
- **A6 job级续跑（v0.6.4）**：父进程每完成一个job后按计划顺序原子替换 `results.jsonl`；恢复时只运行缺失job。旧版结果缺少指纹和 `job_input_hash`，不能直接恢复。
- **sudo**：Legion 端未配免密 sudo。需 root 操作时用 `wsl.exe -u root`。
