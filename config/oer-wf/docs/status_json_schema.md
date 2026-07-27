# STATUS.json 契约

> 由通用任务包装器（`oer_wf.runtime.wrapper`）负责写入。
> 计算脚本本身**不需要**手写 try/finally。

---

## 1. 设计目标

- 进程被 OOM / 段错误杀死时，仍尽量留下最终状态（atexit + 信号钩子）
- 原子写入，避免半截 JSON
- 与 systemd 状态正交：两者冲突时报告 **不一致**，不猜测成功
- 完整 provenance：时间、commit、命令、PID、退出码、错误摘要

---

## 2. 状态枚举

| status | 含义 | 谁写入 |
|--------|------|--------|
| `STARTING` | 包装器已启动，即将 exec 用户脚本 | 包装器（启动时） |
| `RUNNING` | 用户脚本正在执行 | 包装器（启动后立即） |
| `SUCCESS` | 正常结束，exit_code == 0 | 包装器（退出钩子） |
| `FAIL_NUMERICAL` | 脚本主动报告数值/求解失败 | 脚本调用 `mark_fail_numerical()` 或包装器根据约定退出码 |
| `FAIL_INFRA` | 环境/IO/未捕获异常/信号杀死 | 包装器 |
| `INCONSISTENT` | 仅由 `wf status` 合成，表示 systemd 与 STATUS 冲突 | `wf status`（不写入文件） |

---

## 3. 字段规范

```json
{
  "status": "RUNNING",
  "exit_code": null,
  "pid": 12345,
  "started_at": "2026-07-27T09:00:00Z",
  "finished_at": null,
  "commit": "3f9aad1",
  "task_id": "3f9aad1/solver_equiv_01",
  "command": ["/path/to/python", "scripts/run.py", "--config", "cfg.yaml", "--output", "...", "--workers", "4"],
  "output_dir": "/home/lsy/.../results/solver_equiv_01/20260727_090000",
  "error_msg": null,
  "extra": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 见上表 |
| `exit_code` | int \| null | 进程退出码；运行中为 null |
| `pid` | int | 包装器进程 PID |
| `started_at` | string | ISO-8601 UTC |
| `finished_at` | string \| null | ISO-8601 UTC；运行中为 null |
| `commit` | string | 短或完整 SHA |
| `task_id` | string | `commit_short/task_name` |
| `command` | list[str] | 完整 argv |
| `output_dir` | string | 绝对路径 |
| `error_msg` | string \| null | 失败时的摘要 |
| `extra` | object | 脚本可写入的扩展字段 |

---

## 4. 原子写入规则

1. 先写临时文件 `STATUS.json.tmp.<pid>`
2. `fsync` 后 `os.replace` 到 `STATUS.json`
3. 任何时刻读者看到的要么是完整旧文件，要么是完整新文件

---

## 5. 包装器与脚本的职责边界

| 职责 | 包装器 | 计算脚本 |
|------|--------|----------|
| 写 STARTING / RUNNING | ✅ | — |
| 捕获未处理异常 → FAIL_INFRA | ✅ | — |
| 信号 / atexit 收尾 | ✅ | — |
| 数值失败标记 | 可选约定退出码 | 可调用 `mark_fail_numerical(msg)` |
| 科学逻辑 | — | ✅ |

脚本如需主动声明数值失败：

```python
from oer_wf.runtime.wrapper import mark_fail_numerical
mark_fail_numerical("LSODA failed with too many steps")
sys.exit(2)   # 约定：2 = numerical fail（可配置）
```

---

## 6. 与 systemd 的组合判定（`wf status`）

| systemd | STATUS.json | 报告 |
|---------|-------------|------|
| active | RUNNING | `running` |
| inactive + exit 0 | SUCCESS | `pass` |
| inactive + exit ≠ 0 | FAIL_* | `fail` + 对应 fail_type |
| active | SUCCESS / FAIL_* | **inconsistent**（优先报告） |
| inactive | RUNNING / 缺失 | **inconsistent** 或 `fail` (infra) |
| failed | 任意 | 以 STATUS 为准，并附 systemd 详情 |

**原则：冲突时绝不猜测成功。**
