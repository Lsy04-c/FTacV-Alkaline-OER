# OER-FTAcV 工作流总结（2026-07-26）

## 完成阶段

### Phase 0：32pt 同构基线重算 ✅

**问题**：旧 CSV 缺少 `points_per_cycle` 采样字段，12pt/32pt 证据矛盾。

**修复**：
- 在 Legion 上重算三项正式 CSV（feature 30行、reconstruction 24行、residual 8行）
- 全部记录 `points_per_cycle=32`、`simulation_n_points`、`fit_harmonics`、`fixed_params`
- 更新 `run_manifest.json` 含 SHA-256、commit、配置
- 更新 `WORK_STATUS.md` Section 17

**Gate 0 PASS**：74 tests，CSV 与 manifest 一致，已推送 `4d5035b`。

### Phase 1：锁相信号验证 ✅

**实现**：`code/python/src/oer_aem/signal.py::lockin_harmonics()`
- 软件锁相放大器：signal × sin/cos → lowpass → I/Q → A(t), φ(t)
- 自适应低通截止：`fc = min(0.8*f0, scan_rate/resolution)`
- 返回 `valid_mask`、`edge_trim_samples`、`n_effective`、`effective_resolution_v`

**合成测试**（4/4 通过）：
- 稳态幅值/相位恢复（H1-H2，误差 < 5%/0.06rad）
- 缓变包络跟踪（corr > 0.90）
- Nyquist 检测 + 非法输入拒绝

**真实数据诊断**（`code/python/scripts/validate_potential_resolved_harmonics.py`）：

| 数据集 | f0 | 有效分辨率 | n_eff | H1 幅值 |
|--------|-----|-----------|-------|---------|
| FT2 | 5Hz | 19mV | 51 | 6.1e-4 |
| FT3 | 5Hz | 25mV | 79 | 7.9e-4 |
| FT4 | 1Hz | 25mV | 79 | 9.1e-4 |
| FT8 | 5Hz | 25mV | 71 | 1.3e-3 |

**关键发现**：FT4（1Hz）的低扫速（0.004 V/s）补偿了低基频，分辨率 25mV 可用。不应排除。

**Gate 1 PASS**。已推送 `b619ab0`。

### C++ Crank-Nicolson 求解器 ✅

**文件**：`code/cpp/src/oer_cn_solver.cpp`，`code/python/src/oer_aem/cpp_bridge.py`

**方法**：
- Crank-Nicolson 时间积分 + 阻尼 Newton 迭代
- 数值 Jacobian（中心差分，h=1e-6）——避免手写解析 Jacobian 的符号错误
- 6 状态系统（5 覆盖度 + φ）

**调试过程**：
1. 初版：解析 Jacobian 有 3 处符号错误（φ 行对覆盖度的偏导多了负号）
2. `solve6` LU 行交换写成了列交换——在条件数 5.6e8 的矩阵下导致完全错误的结果
3. 修复后 O(dt²) 收敛确认

**性能**（Mac M1，8000 点，50s 模拟）：

| ppc | 耗时 | NRMSE (vs LSODA) | 加速比 |
|-----|------|------------------|--------|
| 32 | 0.027s | 0.86% | 245× |
| 64 | 0.044s | 0.27% | 148× |
| 128 | 0.074s | 0.07% | 88× |
| 256 | 0.128s | 0.02% | 51× |

**集成**：`forward_current()` 自动检测 `liboercn.so/dylib`，可用时优先使用 C++ 求解器，不可用时回退 scipy LSODA。

已推送 `bef7bb2`。

### Phase 2：网格收敛 ✅

**改动**：
- `feature_grid_size: Optional[int] = None`（None = 自动全量，int = 显式）
- 新增 `resolved_feature_grid_size` 只读属性
- DC/谐波损失 `np.sum` → `np.mean`（消除点数尺度效应）

**收敛测试**（`code/python/scripts/compare_feature_grids.py`）：

| 网格 | G_OH 偏移 | log10(k0_1) 偏移 |
|------|-----------|-----------------|
| 64 vs full | 7.0% | 1.36 |
| 128 vs full | 0.0% | 0.00 |
| 256 vs full | 0.0% | 0.00 |

**Gate 2 PASS**：最小收敛网格 = 128。已推送 `7a82dc1`。

### Phase 3：带符号敏感性 ✅

**新增函数**（`code/python/src/oer_aem/identifiability.py`）：
- `signed_sensitivity_table()`：每对 (feature, parameter) 的带符号敏感度
- `coupling_direction()`：每参数的耦合对列表，标注 compensating/distinguishable

**输出文件**：
- `signed_sensitivity.csv`：特征×参数带符号矩阵
- `coupling_direction.csv`：参数对相关方向

**Gate 3 PASS**：符号从中心差分保留，低敏感度条目不参与耦合解释。已推送 `d318bce`。

### Phase 4：lockin_only 模式 ✅

**新增 feature_mode**：`lockin_only`
- 使用锁相放大器的电位分辨 A(E) 和 φ(E)
- 与 legacy、complex_snr 并列三种模式
- 目标函数：DC + 全局 complex SNR + lockin 振幅 + lockin 相位
- 已集成到 `compare_feature_objectives.py`（MODES = 3）

**Smoke test**：45 行（3 modes × 5 targets × 3 seeds）全部有效。

已推送 `d174110`。

### Phase 5：正式比较 🔄

**状态**：暂停启动
- 工作树已同步到 `d174110`，环境已确认
- C++ 求解器已在 Legion 编译（`code/cpp/build/liboercn.so`）
- 已配置 GitHub SSH 代理
- 因 tmux 随 SSH 断开会话丢失，需改用 nohup 后台运行

原待执行命令保留为历史记录，不得直接运行：
```bash
nohup /home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python \
  /home/lsy/OER-FTAcV-run-3e08bdd/code/python/scripts/compare_feature_objectives.py \
  --trials 50 --workers 8 \
  > /home/lsy/OER-FTAcV-run-3e08bdd/results/architecture_validation/formal_run.log 2>&1 &
```

### Phase 1R：锁相信号层纠错（本机验证完成，Gate 待关闭）

**已修复**：

- 真实相位圆均值丢失虚部；
- `complex` 与 `phase` 的 I/Q 约定不一致；
- 实验和模拟未统一参考应用电位相位；
- 对环绕相位直接线性插值；
- objective 未使用锁相有效区域；
- 实验 target 用时间轴插值电位网格。

**验证证据**：

- 5 个新增回归测试完成 RED→GREEN；
- 全量 `79 passed`；
- H1–H7 在 32/64 points-per-cycle 和 24/40 周期下：
  - 最大幅值相对误差：0.29%；
  - 最大相位误差：0.0029 rad；
- FT2、FT3、FT4、FT8 重新诊断无 warning，H1–H7 相位均为有限值。

**尚未完成**：

- 真实数据重采样或记录长度变化时的峰位漂移；
- smoke CSV 尚未独立记录 `lockin_amplitude` 和 `lockin_phase` loss；
- C++ CN 尚未通过跨参数空间的下游特征等价性门。

因此 Phase 5 继续暂停，不能将本节结果解释为反演精度已经提高。

## 代码架构（当前状态）

```
OER-FTAcV/
├── code/cpp/
│   ├── src/oer_cn_solver.cpp              # Crank-Nicolson 求解器
│   ├── src/experimental/                  # 早期实验实现
│   └── build/liboercn.dylib / .so         # 本机构建产物
├── code/python/src/oer_aem/
│   ├── signal.py                 # +lockin_harmonics()
│   ├── inversion.py              # +feature_mode lockin_only, +C++ bridge
│   ├── identifiability.py        # +signed_sensitivity_table, coupling_direction
│   └── cpp_bridge.py             # ctypes wrapper (liboercn)
├── code/python/experimental/
│   └── rhs_jit.py                # 未通过正式等价性门的 Numba JIT RHS
├── code/python/scripts/
│   ├── validate_potential_resolved_harmonics.py  # Phase 1.5 诊断
│   ├── compare_feature_grids.py                  # Phase 2.3 收敛
│   └── compare_feature_objectives.py             # +lockin_only mode
├── results/
│   ├── formal/                       # 正式证据
│   ├── smoke/                        # 小预算流程检查
│   └── diagnostics/                  # 诊断证据
└── documents/
    ├── plans/                        # 可执行计划
    └── project/                      # 项目目标、状态和工作流
```

## 关键经验

1. **LU 行交换 bug**：column-major 存储下 `A[jj + col*N]` 是同一行不同列，不是同一列不同行。正确写法是 `A[c*N + col] ↔ A[c*N + best]`。
2. **解析 Jacobian 符号**：多次反复才找全所有符号错误。数值 Jacobian（中心差分）虽然多 12 次 RHS 求值/迭代，但保证了正确性。
3. **阻尼 Newton**：无阻尼时 φ 爆炸到 5e8V，阻尼 0.5 时停滞不收敛。最终方案：数值 Jacobian + 自适应阻尼（max_dy > 0.5 时 scale）。
4. **Legion tmux 不持久**：SSH 断开会话后 tmux server 随之死亡。长时间任务应使用 `nohup &`。
5. **FT4 不应排除**：低扫速（0.004 V/s）补偿了低基频（1Hz），分辨率 25mV 可用。

## 推送记录

| 提交 | 阶段 | 说明 |
|------|------|------|
| `4d5035b` | Phase 0 | 32pt 同构基线 |
| `173b7c3` | — | lock-in 代码合并 |
| `b619ab0` | Phase 1 | 锁相诊断完成 |
| `bef7bb2` | C++ | CN 求解器 245× 加速 |
| `7a82dc1` | Phase 2 | 网格收敛（128pt） |
| `d318bce` | Phase 3 | 带符号敏感性 |
| `d174110` | Phase 4 | lockin_only 模式 |
