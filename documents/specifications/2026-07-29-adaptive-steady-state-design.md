# V2 自适应稳态初始化设计

## 1. 问题

V2 首轮 4×8 LSODA smoke 有 5/32 个任务在动态扫描前失败。失败候选的
`calculate_steady_state` 均完成固定 5 s Radau 积分，但最终 RHS 无穷范数
为 `1.10e-7` 至 `1.92e-3`，高于冻结门 `1e-8`。

只读复算将同一状态继续积分后，三个代表失败案例分别在累计 50、500 或
5000 s 达到原门；额外墙钟为 0.04–0.10 s。由此确认当前直接问题是固定
5 s 松弛时间不足，不是这些候选已经证明物理不可解。

## 2. 方案选择

采用分段自适应 Radau 松弛，累计检查点固定为：

```text
5, 50, 500, 5000, 50000 s
```

每段从上一段终态继续。求解器成功且 RHS 无穷范数不高于 `1e-8` 时立即
返回。达到 50000 s 后仍不满足原门则明确失败。

不采用以下方案：

- 非线性根求解：覆盖度约束、多根和初值分支需要新的科学验证；
- `use_steady_state=false`：改变实验初始条件语义，违反既有 A2 契约；
- 放宽 RHS 门或删除失败候选：掩盖数值失败并改变冻结门。

## 3. 接口

新增两个不可变记录：

```python
@dataclass(frozen=True)
class SteadyStateAttempt:
    elapsed_s: float
    rhs_norm: float
    success: bool
    message: str
    nfev: int


@dataclass(frozen=True)
class SteadyStateSolution:
    state: np.ndarray
    elapsed_s: float
    rhs_norm: float
    attempts: tuple[SteadyStateAttempt, ...]
```

`calculate_steady_state_detailed(params)` 返回完整记录。
`calculate_steady_state(params)` 保持原返回类型，只返回 `.state`。
`solve_ode_system_detailed` 将稳态累计时间、最终 RHS 和各阶段记录写入
`ODESolution`。关闭稳态时这些字段为 `None` 或空元组。

V2 runner 将下列字段写入每个成功或动态求解失败记录：

```text
steady_state_elapsed_s
steady_state_rhs_norm
steady_state_attempts
```

稳态初始化失败继续使用 `failure_kind=ODE_INITIALIZATION`，并在错误消息中
写明最终累计时间和 RHS。

## 4. 数值规则

- 每段仍使用 Radau、`rtol=1e-4`、`atol=1e-6`；
- 第一段保持原 5 s 配置和 `max_step=0.1 s`，使既有快速收敛案例不变；
- 后续段的 `max_step=(segment_end-segment_start)/50`；
- 每段检查 solver success、状态形状、有限值、覆盖度范围和守恒；
- RHS 门保持 `1e-8`；
- 任一 Radau 阶段显式失败后立即停止，不切换求解器；
- 不裁剪、不归一化覆盖度，不以投影制造稳态。

## 5. 压力测试

实现必须通过：

1. 默认参数在第一段返回，状态与旧单段 5 s 结果一致；
2. V2 失败候选 FT2-2、FT2-5、FT4-2 达到 `RHS≤1e-8`；
3. 自适应终态与独立严格长时 Radau 参考的覆盖度和表面电位一致；
4. 人工不收敛案例遍历全部五段后失败，错误包含 50000 s 和最终 RHS；
5. 4×8 LSODA smoke 完整，ODE 成功率至少 95%；
6. 独立 validator 重算通过，smoke 科学分类仍为 null；
7. 全量 Python、Web 和布局测试通过。

## 6. 失败退出

若慢候选仍低于 95% 成功率，停止正式 V2 并保留新证据。不得继续增加上限
或修改门槛；下一轮必须重新比较根求解或参数库数值域。

若成功率达到 95%，该结果只关闭初始化阻断点。正式 512 候选仍需先补齐
validator 的 stress 全量重算、`--rerun-best` 和 oer-wf 集成。
