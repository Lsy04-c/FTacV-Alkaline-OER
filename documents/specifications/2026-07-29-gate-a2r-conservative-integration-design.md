# Gate A2-R 守恒积分与显式后端回退设计

## 1. 目标

Gate A2-R 只修复 Gate A2 已确认的数值问题：

1. 逐分量边界投影破坏覆盖度守恒；
2. 标量绝对容差不能约束接近零的覆盖度；
3. `thermo-edge` 在 LSODA 中首步收敛失败。

本阶段不修改五步反应、热力学关系、参数范围、扫描条件或 Gate A2 阈值，
也不评价实验拟合。

## 2. 已确认的根因边界

### 2.1 覆盖度守恒

连续 RHS 使用 `dtheta/dt = S @ rates`，且 `ones.T @ S = 0`。当前代码随后
把边界处的负导数逐分量置零；修改后的导数不再等于 `S @ rates`，因此不再
保证和为零。

只读复现中，移除投影后：

- 12 个案例的覆盖度和误差保持在约 `1e-12`；
- 使用原标量 `atol=1e-8` 时，个别覆盖度仍低于 `-1e-8`；
- 把五个覆盖度的绝对容差设为 `3e-11` 后，11 个 LSODA 案例满足冻结
  覆盖度范围。

因此投影是守恒漂移的直接原因，标量绝对容差是剩余边界误差的独立原因。

### 2.2 `thermo-edge`

`thermo-edge` 的平衡电位为：

```text
E01=1.8, E02=0.4, E03=3.2, E04=-0.48 V
```

稳态检查通过，但 LSODA 即使移除投影、减小绝对容差和首步，仍出现 repeated
convergence failures。BDF 和 Radau 在同一 RHS、网格、相对容差和分量绝对
容差下均完成。

该证据只支持“LSODA 对该瞬态不稳定”；尚不支持删除案例、修改机理或缩小
参数域。

## 3. 方案比较

### 方案 A：放宽覆盖度阈值

拒绝。它保留破坏守恒的投影，也不能解决 LSODA 失败。

### 方案 B：删除投影并强制所有案例使用 BDF

可通过当前诊断，但会无条件增加常规计算成本，并绕过已验证可用的快速
LSODA 路径。

### 方案 C：删除投影、分量容差、LSODA 主后端与显式 BDF 回退

采用。常规案例继续使用 LSODA；只有 LSODA 返回失败时才从同一初值重启
BDF。结果必须记录每次尝试、失败消息和最终后端。

## 4. RHS 与容差

删除 `_oer_model_rhs` 中逐分量边界投影。RHS 始终返回：

```text
[S @ rates, dphi_s/dt]
```

正式动态求解固定：

```python
atol = [3e-11, 3e-11, 3e-11, 3e-11, 3e-11, 1e-8]
rtol = 1e-6
max_step = min(total_time / 50, 1 / (f * 20))
```

覆盖度不做裁剪、重归一化或输出后修正。正式门继续检查原始轨迹。

稳态 Radau 配置本阶段不变；稳态成功与动态求解成功继续分开记录。

## 5. 后端策略

新增结构化动态求解接口，返回：

- `t, y, E_actual, i_total`；
- `backend_used`；
- `attempts`：后端、成功状态、消息和求解统计；
- `fallback_used`。

策略固定为：

1. 从冻结初值运行 LSODA，显式 `first_step=1e-8`；
2. LSODA 成功且返回完整网格时结束；
3. LSODA 失败或返回不完整网格时，从原始初值运行 BDF；
4. BDF 也失败时，结构化接口抛出异常；
5. 兼容接口可以保留历史 NaN 返回语义，但不得把失败写成成功。

BDF 不是 LSODA 结果的续跑，也不能使用 LSODA 的末状态。

## 6. 回退可信度

`thermo-edge` 没有成功的 LSODA 参考，因此以独立隐式后端 Radau 交叉验证
BDF。冻结门：

- BDF 与 Radau 均成功且返回完整网格；
- 覆盖度最大绝对差 `<=1e-5`；
- 表面电位最大绝对差 `<=1e-4 V`；
- 电流 NRMSE `<=1e-5`；
- 电流最大误差除以参考动态范围 `<=1e-4`。

只读预检值分别约为 `2.21e-6`、`1.60e-5 V`、`9.57e-7` 和
`2.74e-5`。正式阈值在新运行前冻结，不根据正式结果修改。

## 7. Gate A2-R 案例与阈值

沿用 Gate A2 的 12 个案例、32 cycles、128 points/cycle 和全部物理阈值。
新增：

- RHS 投影逻辑不存在；
- 11 个常规案例必须使用 LSODA，`fallback_used=false`；
- `thermo-edge` 允许且预期使用 BDF，必须保存 LSODA 失败消息；
- BDF–Radau 交叉验证通过；
- 全部原始覆盖度、覆盖度和、电流闭合、稳态、热力学、基线和 M0 回退通过。

如果其他案例触发回退，Gate 为 `FAIL_NUMERICAL`。如果 `thermo-edge` 不再
触发回退但 LSODA 完整通过，不因此失败，但仍需运行 BDF–Radau 交叉验证。

## 8. 证据与独立验收

新 runner 输出：

```text
physics_contract.json
trajectory_metrics.jsonl
backend_attempts.jsonl
implicit_crosscheck.json
baseline_comparison.json
gate_a2r_summary.json
run_manifest.json
```

独立 validator 不导入 runner 或物理核心。它重新检查：

- 文件哈希、案例集合、固定阈值和容差；
- 化学计量矩阵列和；
- 后端尝试顺序、完整网格和回退原因；
- 全部数值门；
- runner summary 是否与独立重算一致。

## 9. 失败出口

- `FAIL_STRUCTURE`：只修复证据链，不改变科学运行。
- `FAIL_NUMERICAL`：保留原始轨迹与后端尝试，停止 A2 依赖步骤。
- `FAIL_PHYSICS`：停止；不在本阶段改变机理。
- `PASS`：关闭 A2-R，但 A1 的 `FAIL_METADATA` 仍继续禁止真实数据正式反演。

Gate A2 的 `gate-a2-6486d69` 失败归档永久保留，禁止覆盖或回写。

## 10. 设计自审

- 没有改变反应机理、热力学或 Gate A2 阈值。
- 投影和容差作为两个变量分别诊断。
- 回退是显式、可追踪的完整重启，不是静默续跑。
- `thermo-edge` 由两个独立隐式后端交叉验证。
- 常规案例意外回退会失败，防止 BDF 扩散成默认慢路径。
- 没有未决占位符。
