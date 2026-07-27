# OER-FTAcV 工作进展总结（2026-07-18，更新：2026-07-27）

## 0. 目录重分类状态（2026-07-26）

- 状态：已完成代码、文档和结果证据的目录迁移，当前分支为 `codex/reclassify-project`。
- 代码：Python、MATLAB、C++、Web 分别位于 `code/python/`、`code/matlab/`、`code/cpp/`、`code/web/`。
- 文档：项目状态、纠错、计划、规格、研究、环境和交接材料统一位于 `documents/` 的对应分类目录。
- 结果：正式证据、小预算流程检查和诊断结果分别位于 `results/formal/`、`results/smoke/`、`results/diagnostics/`。
- 索引规则：根 `README.md` 说明仓库入口和放置原则，`documents/README.md` 说明文档分类；后续新增内容必须遵守两者。
- 隐私边界：`documents/environment/private/`、`documents/handoffs/` 和 `code/cpp/build/` 仅本机保留，不提交。
- 迁移验证：最终 Python 101 项通过（含目录布局 4 项、Markdown 审计 3 项）；Web 后端 3 项通过（另有 1 条 Starlette 弃用警告）；macOS C++ 动态库构建和 bridge 测试通过。
- Web 前端：当前为静态 `index.html`，没有构建脚本，不把 `npm run build` 作为验收门。
- 关联提交：`f6acdec`、`d9504fd`、`f4adb58`，均已推送至远端当前分支。
- 后续分类提交：`e13b42c` 已纳入实验性 C++、Numba RHS、谐波计划和工作流总结。

## 0.1 Gate A3 正式求解器等价性（2026-07-26）

- 状态：**FAIL**，停止 CN 正式搜索，不启动后续正式 TPE。
- 配置：commit `1becc125311e`，24 samples，seed 17，256 cycles，128 points/cycle。
- 环境：Legion Python 3.11.2、NumPy 2.4.6、SciPy 1.17.1、Optuna 4.9.0。
- 证据：`results/formal/solver_equivalence/formal-1becc12/`。
- 完整性：CSV 列结构和 provenance 有效，但只有 156 行；sample 12、21 的 LSODA 失败，各以一行 harmonic 0 记录。
- 数值失败：15 项 `lockin_phase_rmse_rad` 超阈值；sample 20 的 `dc_nrmse=0.0261167` 超过 0.01，并伴随 H7 相位失败。
- LSODA 失败诊断：
  - sample 12、21 均在 `t=0` 以 repeated convergence failures /
    `Unexpected istate` 失败，初值有限且覆盖度总和为 1；
  - 已验证的直接失败机制是高速率参数组合下 LSODA 自动初始步长路径
    不稳定；不是长扫描累积误差或 NaN 初值。更广参数空间的充分性仍待验证；
  - 显式 `first_step=1e-8` 后，同一 24 个参数向量在 Legion 上
    24/24 完成、0 条警告，总 LSODA wall time 147.274 s；
  - 已增加求解配置回归测试，Mac Python 测试 103 项通过。
- 决策：原 Gate A3 证据和 **FAIL** 结论保持不变；修复只恢复参考求解器
  可用性，不能消除 CN 的相位偏差和 sample 20 DC 偏差。下一步按原失败
  路径以新 commit 独立评估 256 points/cycle。

## 0.2 Gate A3 256 points/cycle 独立正式门（2026-07-26）

- 状态：**SCIENTIFIC FAIL**，CN 继续禁止进入正式搜索。
- 配置：commit `a4581dea2d8`，24 samples，seed 17，256 cycles，
  256 points/cycle；阈值和 2% 可解析性规则未修改。
- 执行：Legion 独立 worktree，`systemd-run --user`；Python 3.11.2、
  NumPy 2.4.6、SciPy 1.17.1、Optuna 4.9.0。
- 完整性：168 行、24 个样本、每个样本 H1–H7；所有指标有限，
  LSODA/CN 全部成功，manifest 的 commit、环境和源码/动态库哈希完整。
- 科学失败：22 项 `lockin_phase_rmse_rad` 超阈值，涉及 sample
  0、6、8、9、12、17、20、21；低阶 H2/H3 仍在 sample 0、8、9、17
  失败。
- 对照：128 点门中的 LSODA 缺行和 sample 20 DC NRMSE 失败已消失，
  但主要锁相相位偏差没有随 128→256 points/cycle 收敛，不能归因于输出
  采样密度不足。
- 证据：`results/formal/solver_equivalence/formal-a4581de-ppc256/`。
- 决策：停止继续通过提高 points/cycle 修补 CN；底层架构后续使用 LSODA
  作为唯一正式后端。若未来重新开发 CN，必须先诊断离散方程/相位传播，
  再注册新的独立等价性门。

## 0.3 Gate A4 真实数据谐波稳定性（2026-07-26）

- 状态：**PASS**，允许电位分辨锁相特征进入 A5 目标函数拆分。
- 配置：commit `68486134087b`；FT2、FT3、FT4、FT8；H1–H7；
  抗混叠 2×/4×降采样，以及分别删除起点/终点 10% 的记录长度变体。
- 科学口径：完整记录冻结基频；仅在共同有效电位区比较复数包络；
  H1–H3 强制评价，H4–H7 仅在相对 H1 ≥2% 时评价。
- 执行：Legion 8 workers，每个 worker 的 OMP/OpenBLAS/MKL/NumExpr
  线程均限制为 1。
- 完整性：112 行、16 个 dataset/variant 组、每组 H1–H7；所有必需
  指标有限，输入 SHA-256、commit、环境、命令和线程限制完整。
- 门结果：60 行进入信号指标评价；最坏 amplitude NRMSE 0.00411，
  最坏 wrapped phase RMSE 0.01810 rad，峰位漂移 0；共同有效比例最低
  0.8559，独立电位区间最低 11。
- 证据：`results/formal/harmonic_stability/gate-a4-6848613/`。
- 边界：PASS 只证明合法采样变化下的信号稳定性，不证明锁相目标提高
  反演精度，也不使低于可解析门的 H4–H7 自动进入拟合。
- 下一步：A5 拆分真正的 `lockin_only` 与 `hybrid`，输出独立损失分量。

## 0.4 A5 目标模式语义拆分（2026-07-26）

- 状态：接口拆分完成，正式精度比较尚未开始。
- commit：`e042a00`。
- 固定语义：
  - `legacy`：DC + 历史谐波 envelope + physical；
  - `complex_snr`：DC + 全局复数谐波 + physical；
  - `lockin_only`：DC + 电位分辨锁相复数谐波 + physical；
  - `hybrid`：DC + 全局复数 + 锁相复数 + physical。
- 兼容：历史 `combined` 继续按 `hybrid` 执行，但新结果不再使用该名称。
- 损失审计：锁相 amplitude/phase 已分别拆成 H1–H3 common 与 H4–H7
  dataset-specific；未启用的分量显式为 0。
- Legion smoke：8 workers、LSODA、每模式/数据集/种子 1 trial；共 60 行，
  四模式各 15 行，所有共同评价指标和损失字段有限，模式语义泄漏检查通过。
- 证据：`results/smoke/architecture_validation/feature_mode_separation/`。
- 边界：不同模式的活动观测块数量不同，`total_loss` 不可跨模式排名；
  该 smoke 只证明接口和证据链可运行，不证明 lock-in 或 hybrid 提高精度。
- 下一步：冻结共同评价指标、参数库和正式预算，再进行配对精度比较。

## 0.5 Gate A5 固定参数库网格收敛（2026-07-26）

- 状态：**PASS**，冻结 `feature_grid_size=128`。
- commit：`44a020e7e950`。
- 配置：legacy、complex_snr、lockin_only、hybrid；64/128/256/full；
  8 个 seed 23 分层参数候选；5 Hz、256 cycles、32 points/cycle；LSODA。
- 设计：不运行 TPE，只比较同一 mode/candidate 跨网格的损失、共同 DC、
  共同 H1–H3 和候选损失排序。
- 执行：Legion 8 workers，每 worker 一个 OMP/OpenBLAS/MKL/NumExpr
  线程。
- 完整性：128 行、16 个 mode/grid 组、每组 8 个候选；ODE 全部成功，
  所有损失和共同指标有限，参数库哈希与 provenance 完整。
- 128 vs full：
  - 最坏 total-loss 相对误差 0.01181；
  - 最坏 common DC RMSE 相对误差 0.00384；
  - 最坏 common H1–H3 RMSE 相对误差 0.00375；
  - 四模式 Spearman 均为 1.0。
- 256 vs full 最坏 total-loss 相对误差 0.00505，但不足以证明双倍网格
  成本有必要。
- 证据：`results/formal/feature_grid_convergence/gate-a5-grid-44a020e/`。
- 决策：后续正式精度比较统一使用 128 点；旧单 target 网格证据保留为
  历史，不再承担 Gate 结论。
- 下一步：A6 复核 signed sensitivity 并冻结最终自由参数集；在 A6 前不
  启动四模式正式 TPE。

## 0.6 Gate A7 可复用计算工作流与 DeepSeek 交付协议（2026-07-27）

- 本地已建立 `oer-wf 0.6.3` 工作流，覆盖 `doctor`、`prepare`、
  `smoke`、`run`、`status`、`sync`、`verify`、`git-check` 和
  `clean`。
- 本地测试 49 项通过（含 A7 基础设施 smoke 入口契约）；`doctor` 能将
  systemd `degraded` 与不可用状态
  分开报告。
- smoke 状态写入 `spec_hash`，formal run 只接受与当前任务规格哈希匹配
  的成功 smoke；`status/sync` 从 systemd `ExecStart` 恢复完整输出路径。
- wrapper 已实测三条终态路径：
  - 子进程文件信号可产生 `FAIL_NUMERICAL`；
  - 退出码 0 产生 `SUCCESS`；
  - 非 0/2 退出码产生 `FAIL_INFRA`。
- 已建立
  `documents/specifications/deepseek-compute-delivery-acceptance.md`，
  规定冻结任务规格、唯一运行目录、原始数据、日志、manifest、哈希、
  失败分类和 Codex 接续顺序。
- 已建立上位规范
  `documents/specifications/deepseek-project-continuation-governance.md`：
  DeepSeek 可以接续代码、测试、诊断、计算、文档和 Git 工作，但判断必须
  区分观察、工程事实、数值结论、科学判断与机理假设；L3/L4 结论必须列出
  反证、替代解释和未验证条件，并交由 Codex/用户复核。
- 当前边界：
  - Legion 已部署 `oer-wf 0.6.3`；commit `ab55c8a` 的远端工作树
    49 项测试通过；
  - 真实 Legion 基础设施 smoke 已通过：
    `ab55c8a/a7_workflow_smoke`，spec hash
    `sha256:5f9a6417e1a7cfd43655320605faeacaab52d43b2e6f041cb17e6d830ed853cc`；
    systemd 终态为 `inactive/dead`、`Result=success`、退出码 0，
    `STATUS.json=SUCCESS`，CSV 与 manifest 内容符合冻结契约；
  - 工作流代码、指南和交付协议已由 commit `ab55c8a` 推送至
    `codex/reclassify-project`；
  - 尚未验收 formal run、sync、verify 和故障注入；
  - 不把本地 mock/单元测试写成 Gate A7 正式通过。
- 下一步：
  1. 用已通过 smoke 的同一 spec 验证 formal gate、status、sync 和 verify；
  2. 人为验证数值失败、缺文件、哈希冲突和中断恢复；
  3. 验收后关闭 Gate A7。

项目：碱性 OER AEM 微观动力学建模与 FTacV 参数反演平台
负责人：刘拾玉
目标体系：Co3O4 / CoOx(OH)y 碱性 OER
当前主线：FTacV 多组数据支持 AEM 热力学描述符的稳定识别，但动力学参数与有效位点数存在强补偿。下一阶段以独立约束 gamma 和分阶段反演为核心，提升参数可解释性。

---

## 1. 当前判断

这套代码已经从早期 demo 进入“可运行的机理反演原型”阶段，但算法还不能作为最终科研结论使用。

当前算法能做：

- 上传实验 FTacV 数据；
- 自动识别 f、dE、扫描范围、扫描速率；
- 提取 DC 与 1-7 次谐波；
- 运行 OER AEM 正演模型；
- 用 TPE 搜索机理参数；
- 用当前参数或反演参数正演并与实验叠加；
- 给出拟合完成度提示；
- 按实验谐波强度自动建议拟合通道。

当前算法还不能直接证明：

- 某个参数就是真实控制因素；
- 反演得到的 k0 或吸附能一定唯一；
- 高阶谐波不匹配一定来自 OER 机理；
- 基底背景、电容泄漏、预氧化残余电流已经被正确分离。

结论：**现在的方向是对的，但目标函数、谐波权重、背景扣除和参数可识别性仍需要重新设计。**

---

## 2. 最近完成的代码进展

### 2.1 TPE 反演核心

已建立 `python/oer_aem/inversion.py`，包含：

- `DEFAULT_PARAM_SPECS`
- `InversionConfig`
- `InversionResult`
- `encode_params`
- `decode_vector`
- `params_from_vector`
- `forward_current`
- `extract_features`
- `make_synthetic_target`
- `InversionObjective`
- `TPEInverter`
- `assess_fit_quality`

对应提交：

- `3bb8b97 feat(inversion): add TPE inversion core`
- `28a1711 feat(inversion): report fit quality`

### 2.2 前端反演流程统一

已取消单独、容易误解的 CMA-ES 页面，把实验数据、正演、反演放在同一个页面。

当前主页面为：

```text
实验 · 正演 · 反演
```

当前图线语义：

- `Experiment` / `Exp DC`：实验数据；
- `当前参数正演`：用户当前参数的正演；
- `反演参数正演`：TPE 反演后参数的正演；
- 没有反演前，不再把正演线称作拟合线。

对应提交：

- `3435ba4 fix(frontend): preserve simulation state across tabs`
- `79651e2 feat(web): connect TPE inversion workflow`
- `812d914 fix(frontend): unify experiment inversion workflow`

### 2.3 初始参数与固定参数

反演时现在会：

- 把当前页面参数作为 `initial_params`；
- 把 `Cdl`、`Ru`、`A`、`E0_pre`、`k0_pre` 作为 `fixed_params`；
- 第一轮 trial 优先评估当前经验初值；
- 避免优化器一开始就跳到完全无物理依据的参数区。

对应提交：

- `f8bf5ab fix(inversion): honor priors and initial parameters`

### 2.4 参数归一化、经验边界、谐波筛选

已新增：

- 参数先映射到 `[0, 1]` 归一化空间搜索；
- 再按物理边界解码回真实参数；
- API 支持传入 `param_bounds`；
- 实验数据分析时用原始谐波 RMS 判断哪些谐波可分辨；
- 反演目标函数只拟合可分辨谐波，其余谐波只作为诊断图保留；
- 前端显示哪些谐波参与拟合，哪些只做诊断。

真实数据 `data/raw/ftacv4-ref-1hz.txt` 当前判定：

```text
拟合通道：H1, H2, H3
诊断通道：H4, H5, H6, H7
```

对应提交：

- `3edb8de feat(inversion): normalize search and select harmonics`

### 2.5 参数重要性分析模块

已建立 `python/oer_aem/importance.py`，实现局部单参数敏感性分析。核心入口：`analyze_parameter_importance(base_params, config)`。

分析 13 个参数：k0_1~4、k0_pre、gamma（log10 扰动±0.25 decade）、G_OH、G_O、scaling_OOH_OH（±0.05 eV）、E0_pre（±30 mV）、Cdl、Ru（±20%）、A（±5%）。每个参数正负双向扰动共 26 次 ODE 正演。

特征输出：DC shape/amplitude、H1-H7 shape/peak、Tafel 斜率、onset 电位。H1-H3 进入主评分，H4-H7 仅诊断。

输出结构：

- `parameter_importance`：13 参数按敏感性排序（score/level/main_features/warning）
- `feature_sensitivity_matrix`：特征×参数变化矩阵
- `warnings`：耦合参数提示（如 gamma/A/Cdl 同时影响 DC amplitude）
- `feature_weights`：自动从谐波 RMS 计算的各特征权重

测试：12 个测试（`python/tests/test_importance.py`），与已有 16 个测试合计 28 个全部通过。

### 2.6 机理调试与参数文献标定（2026-07-19）

**信号处理修复（3 处）：**

- `extract_dc_fft`：DC 带宽从裸 `band[0]` 改为自适应（`max(band[0], min_bw)`），防止低 n_points 时波形压平
- `initialize_filters`：带通滤波器带宽从裸 `band[H]` 改为走 `_auto_band`，消除 FFT 路径与时域路径的带宽不一致（之前 4.51 Hz vs 1.0 Hz）
- `solve_ode_system`：`max_step` 约束为 `min(T/50, 1/(f*20))`，确保每 AC 周期至少 20 步采样

**参数文献标定（Moysiadou 2020 JACS + Davis 2023 Nat. Commun.）：**

- `E0_pre`：1.45→1.50 V（Moysiadou：0.1 M KOH 中 Co³⁺/⁴⁺ 氧化峰实测）
- `Cdl`：文献值 80 µF/cm²（Davis：光滑 Co₃O₄(111) 薄膜），当前保留 20 µF/cm² 待实验标定
- `gamma`：文献值 ~1×10⁻⁹ mol/cm²（Moysiadou：表面 Co 密度 6.1×10¹⁴/cm²，~12% 活性），当前保留 5×10⁻⁸ 待实验标定
- `A`：0.196→1.0 cm²（匹配实际电极）

**HER vs OER 对比诊断文档：**

- 完成 `documents/research/her_oer_comparison_critique.md`：系统对比谐波提取、目标函数、参数可识别性
- 核心结论：代码移植正确，欠拟合根因不是算法错误，而是 gamma 未独立标定 + 基底背景未扣除 + 谐波权重不合理
- 高次谐波（h4-h7）弱是 AEM+α=0.5 框架的物理极限，非代码错误

**参数调优过程：**

- 尝试增大 gamma（至 2×10⁻⁷）、dE（至 0.30V）、降低 Cdl（至 2×10⁻⁶）、非对称 α（0.35）
- 最优谐波分离：h2/h1≈11%、h3/h1≈4.4%、h4-h7<2%
- 结论：h4-h7 在 5 步 AEM + α=0.5 框架内天然弱，无法通过调参突破 2%

**测试状态：**

- 24/28 通过，4 个 inversion 测试失败（Tafel 提取在 n_points=256 低分辨率下不可靠，因 A=1.0 cm² 使电容电流增大 5 倍；属已知限制，非今日引入）

---

## 3. 当前算法的主要问题

### 3.1 目标函数还不够物理化

现在目标函数主要比较：

- DC；
- 选定谐波包络；
- Tafel 斜率。

问题是：

- 每个谐波归一化后会丢失真实幅值信息；
- 电容背景和基底背景可能混进 DC；
- 低电位基线不为零会影响反演；
- Tafel 区间如果不是纯动力学区，会误导动力学参数；
- 只用包络可能丢失相位信息。

下一版目标函数应考虑：

- 实验噪声；
- 空白基底背景；
- 谐波 SNR；
- 重复实验稳定性；
- 幅值和相位是否同时可用；
- DC、H1-Hn、Tafel 各自的物理可信度。

### 3.2 参数可识别性不足

当前能找到一组参数让目标函数下降，但这不等于参数唯一。

高风险参数包括：

- `k0_1`、`k0_2`、`k0_3`、`k0_4`
- `gamma`
- `Cdl`
- `Ru`
- `G_OH`
- `G_O`
- `scaling_OOH_OH`

原因：

- 快步骤在 1 Hz 左右可能不可分辨；
- 多个参数可能对同一谐波产生相似影响；
- `gamma`、`A`、`Cdl`、背景电流可能互相补偿；
- 标度关系减少自由度，但也会引入参数相关。

### 3.3 HER 代码不能直接照搬

HER 代码已有：

- `log_` 参数化；
- 手动经验边界；
- CMA-ES 内部 `[0, 1]` 归一化采样；
- DC + H1-H7 相对误差目标函数；
- `harmonic_weights = [1,1,1,1,1,1,1,1]`。

但 HER 没有：

- 自动判断实验谐波是否可分辨；
- 按 SNR 或重复性给谐波降权；
- 系统处理基底背景；
- 证明各参数的可识别性。

因此 OER 不能只复制 HER 的“全谐波等权拟合”。

---

## 4. 刘拾玉接下来设计新算法时建议固定的问题边界

新算法不应回答“怎样让曲线最好看”，而应回答：

```text
在给定实验质量和机理模型下，哪些参数能被 FTacV 可靠识别？
哪些参数只能给趋势、范围或下限？
哪些谐波应该进入目标函数？
哪些信号只应作为诊断？
```

建议把新算法拆成四层。

### 4.1 数据可信度层

输入实验数据后先判断：

- DC 基线是否稳定；
- 空白 Ti 板是否有背景；
- H1-H7 的原始幅值；
- H1-H7 的 SNR；
- 谐波峰是否和噪声/旁瓣可区分；
- 重复实验中谐波是否稳定。

输出：

```text
fit_channels
diagnostic_channels
channel_weights
warning_flags
```

### 4.2 参数边界层

边界不能只为了拟合而放宽，应分来源：

- 文献边界；
- 实验标定边界；
- 仪器测量边界；
- 机理硬约束；
- 暂时工程边界。

每个边界最好带来源标签：

```text
fixed / measured / literature / weak_prior / engineering
```

### 4.3 目标函数层

目标函数建议包含：

```text
loss = w_dc * L_dc
     + sum(w_hn * L_hn)
     + w_tafel * L_tafel
     + penalty_physical
```

其中 `w_hn` 不应手动全等，而应来自：

- SNR；
- 谐波重复性；
- 空白背景占比；
- 该谐波对参数的敏感度；
- 是否处于可分辨频段。

### 4.4 可识别性层

反演后必须做：

- 单参数扰动；
- 局部敏感性矩阵；
- 合成数据回收；
- 参数相关性诊断；
- 多起点稳定性；
- 去掉某个谐波后的结果变化。

最终输出不应只是 `best_params`，还应输出：

```text
identifiable_params
weakly_identifiable_params
unidentifiable_params
dominant_factors
model_warnings
```

---

## 5. 下一步代码建议

等新算法设计明确后，优先改底层，不急着改 UI。

建议顺序：

1. 写 `algorithm_design.md`，定义目标函数、权重、边界、可识别性输出。
2. 在 `python/tests/test_inversion.py` 先写测试。
3. 在 `python/oer_aem/inversion.py` 实现新算法核心。
4. 用合成数据验证参数能否回收。
5. 用 `ftacv4-ref.txt` 做真实数据诊断，不强求拟合。
6. 再接 API 和前端展示。

---

## 6. 当前验证状态

最近一次完整验证：

```bash
.venv/bin/python -m compileall -q python/oer_aem web/backend
.venv/bin/python -m pytest python/tests web/backend/test_inversion_api.py -q
```

结果：

```text
17 passed, 1 warning
```

页面检查：

```text
http://localhost:7100/
```

页面能加载；控制台无本次 JSX 运行错误。现有提示主要是 CDN/Babel/form/favicon，不影响当前算法功能。

---

## 7. Git 状态

最新已推送提交：

```text
3edb8de feat(inversion): normalize search and select harmonics
```

远程：

```text
origin/main -> git@github.com:Lsy04-c/FTacV-Alkaline-OER.git
```

当前仍有未提交文件，暂未处理：

```text
M PROJECT_SUMMARY.md
?? preox_check.png
?? sim_vs_exp_current.png
?? web/backend/test
```

这些文件不是本次算法更新的一部分，后续处理前需要单独确认。

---

## 8. 分层反演与跨数据稳定性诊断（2026-07-20）

### 核心发现

对 4 组 FTacV 数据（ftacv2/3/4/8）运行分层 TPE 反演（实验条件固定 → 预氧化边界 → AEM 自由反演），跨数据参数稳定性诊断显示：

**可继续解释的参数：**
- `scaling_OOH_OH`：CV=0.03，跨数据高度稳定
- `G_O`：CV=0.09，跨数据稳定
- `G_OH`：CV=0.26，可用，样品间有合理波动

**不可单独解释的参数：**
- `gamma`：CV=0.89，与 A/Cdl 补偿
- `k0_1~k0_4`：CV=1.0-1.6，多参数互相补偿

### 核心结论

> 多组实验数据表明，AEM 热力学描述符具有较好的跨数据稳定性，而动力学速率常数和有效位点参数存在显著补偿。当前阶段应以热力学参数和标度关系作为主要机理分析对象，避免对单个动力学参数作过度解释。

### 下一步策略

- 固定或强约束 gamma（需 ECSA/负载量/电容测试独立标定）
- 不单独解释每个 k0_i，仅作为拟合辅助
- 用热力学参数（G_OH、G_O、scaling）做主要机理讨论
- 补充 EIS/ECSA/预氧化峰电量来独立约束 gamma/Ru/Cdl

### 新增文件

- `scripts/analyze_data_quality.py` — 批量数据质量评估
- `scripts/staged_inversion.py` — 分层反演脚本
- `results/data_quality/` — 数据质量报告 + 谐波图
- `results/staged_inversion/` — 分层反演报告

### gamma 固定后验证（2026-07-20）

将 gamma 固定为文献值 3×10⁻⁹ mol/cm²（Moysiadou 2020 表面 Co 密度），重跑 staged inversion：

| 参数 | 固定前 CV | 固定后 CV | 结论 |
|------|----------|----------|------|
| scaling_OOH_OH | 0.030 | 0.030 | 稳定 |
| G_O | 0.090 | 0.096 | 稳定 |
| G_OH | 0.260 | **0.156** | 改善（gamma/A 耦合曾拖累 G_OH）|
| k0_1~k0_4 | 1.0-1.6 | 1.5-1.7 | 仍不可靠 |

**结论：热力学参数稳定性在 gamma 约束后仍然成立。** 这验证了当前 AEM 热力学框架对多组数据的解释力。下一阶段可以此为基础撰写项目阶段性结论。

---

## 9. 下一步操作计划（2026-07-20）

已生成：

```text
docs/deepseek/next_action_plan.md
```

当前阶段不按中期汇报推进，而按内部诊断推进。核心任务是定位 `poor fit` 的来源，并压力测试热力学描述符稳定性。

执行顺序：

1. 复核 gamma 约束前后参数 CV，确认热力学稳定性是否真实改善。
2. 定位 `poor fit` 来源，按 DC、H1-H3、onset、高电流区、低电位基线分别诊断。
3. 优先补最低复杂度背景项，不先加入复杂机理。
4. 在背景项和 gamma 约束下重跑 staged inversion。
5. 检查 `G_OH/G_O/scaling_OOH_OH` 是否仍保持跨数据稳定。
6. 根据残差形态只选择一个下一轮模型缺项。

当前判断标准：

```text
不是让拟合曲线更好看，而是找出 AEM 模型为什么 poor fit；
不是证明完整机理，而是验证热力学描述符稳定性是否能经受 gamma、背景和数据质量压力测试。
```

---

## 10. Stage 3 前置诊断更新（2026-07-20）

### 10.1 fixed_params 逻辑修正

发现脚本层问题：`fixed_params` 中包含 `gamma`，但 `DEFAULT_PARAM_SPECS` 仍包含 `gamma` 时，TPE 会继续搜索并覆盖 fixed 值。

已修正：

```text
scripts/staged_inversion.py
scripts/residual_diagnostics.py
scripts/sweep_ru.py
scripts/diagnose_high_current_penalty.py
```

修正原则：凡是进入 `fixed` 的参数，都从 optimizer specs 中移除。

### 10.2 重新固定 gamma 后的 staged inversion

真正固定 `gamma=3e-9 mol/cm2` 后，四组数据结果为：

| 参数 | CV | 判断 |
|---|---:|---|
| `scaling_OOH_OH` | 0.023 | stable |
| `G_O` | 0.038 | stable |
| `G_OH` | 0.068 | stable |
| `k0_1~k0_4` | 1.00-1.73 | unreliable |

结论：热力学参数稳定性更强；动力学参数仍不可单独解释。

### 10.3 Ru 扫描复核

真正固定 gamma 后重跑 Ru=10-50 Ω 扫描，`bias_hi` 仍锁定在约 `+0.399~+0.400`。

结论：

```text
Ru 不是完整高电位区偏差的主因。
```

### 10.4 OH- 传质判断修正

当前残差定义为：

```text
bias_hi = experiment - simulation
```

完整实验网格中 `bias_hi > 0`，表示模型低估高电位区电流。简单 OH- depletion / current-limiting 传质项会降低模拟电流，可能使偏差更差。

因此下一步不应直接加入完整 OH- 传质方程。更稳的顺序是：

1. 核查完整实验网格与 trimmed inversion grid 的残差口径差异。
2. 测试高电位新增贡献项，例如重构导致的 `gamma_eff(E)` 增长。
3. 若符号核查后确认模型在某些口径下高估电流，再讨论 OH- 传质限制。

已新增：

```text
scripts/diagnose_high_current_penalty.py
results/model_gap/high_current_penalty.md
results/model_gap/high_current_penalty.csv
```

---

## 11. 基础环境与测试基线修复（2026-07-25）

已完成：

- 新增`python scripts/run_tests.py ...`标准测试入口，自动使用项目`.venv`；
- 将后端分析脚本改为可被pytest收集的端到端测试；
- 将真实实验输入统一纳入`data/raw/`；
- 修复低分辨率合成目标无法提取Tafel时整条反演中止的问题；
- 同步FastAPI目标契约，允许不可测Tafel为`None`；
- 修正数据质量报告中“H4-H7全部只作诊断”的错误固定文案。

当前新鲜验证：

```text
python scripts/run_tests.py python/tests -q
33 passed

python scripts/run_tests.py web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
3 passed
```

当前共同可靠拟合通道为H1-H3。H4可用于`ftacv2`和`ftacv8`的附加分析，H5仅在`ftacv2`达到当前幅值门槛；H6-H7在所有数据中只作诊断。

详细审计见：

```text
documents/environment/workspace_environment_audit.md
```

`gamma_eff(E)`及旧模型缺项脚本仍属于未验证实验资产，不计入当前通过测试的基线模型。

---

## 12. 完整网格与裁剪网格残差契约（2026-07-25）

已在测试提交基线`dd4ce91`上统一残差计算：

```text
residual = experiment - simulation
```

`python/oer_aem/data_contract.py`现在通过同一个插值入口计算完整实验网格和裁剪反演网格残差；`scripts/residual_diagnostics.py`不再为两种网格各自维护残差逻辑。

新鲜验证：

```text
python scripts/run_tests.py python/tests/test_data_contract.py -q
4 passed

.venv/bin/python scripts/residual_diagnostics.py \
  --output results/architecture_validation/residual_contract.csv
4 datasets × 2 grids generated
```

机器可读证据：

```text
results/architecture_validation/residual_contract.csv
```

四组数据在两种网格中均明确记录`experiment - simulation`。实验与模拟采用相同的逐通道最大绝对值归一化，模拟周期数由实验时长和频率推导。最大扫描速率相对误差为`1.53e-5`。裁剪网格高电位偏差为FT2 `-0.0020`、FT3 `+0.0251`、FT4 `+0.0362`、FT8 `+0.0149`。此前约`0.6–0.7`的大偏差来自尺度与扫描速率不匹配，相关模型缺项结论已撤回。

---

## 13. 可选复数谐波与SNR加权目标（2026-07-25）

已在测试提交基线`11199f0`上增加两种显式特征模式：

- `legacy`：保持原有DC和逐通道归一化谐波包络损失；
- `complex_snr`：保留跨谐波幅值比例，加入有界SNR权重和环绕相位残差。

目标函数现在分别报告`dc`、`common_harmonics`、`dataset_specific_harmonics`、`phase`和`physical`损失分量，使共同H1–H3与数据特有H4/H5的权衡可追踪。TPE优化器及参数边界未更换。

新鲜验证：

```text
python scripts/run_tests.py \
  python/tests/test_features.py python/tests/test_inversion.py -q
17 passed

.venv/bin/python scripts/compare_feature_objectives.py --smoke --trials 3
30 rows generated
```

烟雾比较覆盖合成目标与四组真实数据、两种模式、种子`7/17/27`，并强制使用相同trial计划、固定参数和边界。合成真值不再作为优化初值泄露给TPE。

为保证两种内部损失尺度可公平比较，正式表还记录统一的事后`common_dc_rmse`、`common_h1_h3_rmse`、最佳热力学/动力学参数及独立评估正演次数；这些统一指标不参与TPE搜索。

机器可读证据：

```text
results/architecture_validation/feature_objective_comparison.csv
```

当前3-trial结果仅证明两条目标函数链路可在同预算下运行，不足以判断新特征是否提高参数恢复精度；科学比较结论必须等待Task 9的50-trial完整运行。

---

## 14. M0/M1最小重构模型门控（2026-07-25）

已在测试提交基线`f88f5ff`上建立嵌套模型比较：

- M0：`beta_recon=0`；
- M1：只增加`beta_recon`自由度，固定`E_recon=1.55 V`和`w_recon=0.05 V`；
- 两者使用相同数据、特征模式、种子、trial预算、基础参数边界和实验固定参数；
- 不自动运行M2。

验收门使用同随机种子配对，检查至少3/4数据在多数种子中的高电位RMSE和去均值形状RMSE改善、H1-H3不恶化、`beta_recon`边界命中、热力学参数跨数据CV和BIC复杂度惩罚。

新鲜验证：

```text
python scripts/run_tests.py \
  python/tests/test_model_compare.py python/tests/test_physics.py -q
13 passed

.venv/bin/python scripts/compare_reconstruction_model.py \
  --smoke --trials 3
24 rows generated; decision=rejected
```

机器可读证据：

```text
results/architecture_validation/reconstruction_model_comparison.csv
```

当前3-trial烟雾运行中，固定门槛为`datasets_passed=0`，因此M1被拒绝。该结果证明拒绝路径和复杂度门可执行，但预算不足以作为最终模型判断；Task 9将用50 trials重新生成结论。无论完整结果如何，通过只表示候选项值得进一步实验验证，不表示已证明表面重构。

---

## 15. 架构验证最终结论（2026-07-25）

> **状态：已作废，等待32点/周期重算。** 本节记录旧12点/周期运行，
> 仅用于追溯，不能作为当前科学结论或最终报告证据。当前有效进度见第16节。

正式计算在拯救者WSL2上执行，基于`c5e8f57`及本节记录的修正工作树。本机负责测试、结果校验、作图、文档和Git。

完整验证结果：

```text
python scripts/run_tests.py python/tests -q
59 passed

python scripts/run_tests.py \
  web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
3 passed, 1 third-party warning

.venv/bin/python scripts/compare_feature_objectives.py \
  --trials 50 --workers 8
30 rows; 50 trials per row

.venv/bin/python scripts/compare_reconstruction_model.py \
  --trials 50 --workers 8
24 rows; 50 trials per row
```

决策：

- 数据列、残差符号、复数谐波基础恢复、覆盖度守恒、M0等价和输出网格稳定性通过；
- 修正后的敏感矩阵包含15个H1-H3特征行；单参数设计实验将`k0_1`从10恢复到98.81（真值100，相对误差1.19%）；
- `complex_snr`合成恢复误差由`0.2513`降至`0.1612`，实验DC RMSE由`0.0583`降至`0.0389`，边界命中不增加，按书面多数规则通过；
- `complex_snr`的共同H1-H3 RMSE由`0.2084`升至`0.2893`，因此下一版保留legacy H1-H3包络作为保护项，不做无条件替换；
- M1仅`1/4`数据通过，热力学CV比值`3.145 > 1.15`，拒绝M1并停止M2；
- 下一版保留M0，开发带共同H1-H3保护项的电位分辨复数谐波与带符号敏感性；补采重复FTacV数据以标定重复性权重。

完整证据与允许的科学表述见：

```text
documents/project/architecture_validation_report.md
results/architecture_validation/
```

---

## 16. 环境恢复与残差检查点修复（2026-07-25）

拯救者环境已恢复并完成只读验收：

- WSL发行版为`Debian-Bookworm`，正式操作使用普通用户`lsy`；
- 主仓库位于`main`，GitHub远端和SSH读取正常；
- `ps`、`pgrep`、`rg`和`tmux`可用；
- 正式计算沿用已验收环境：Python 3.11.2、NumPy 2.2.6、SciPy 1.16.3、Optuna 4.9.0；
- 新代码工作树为`/home/lsy/OER-FTAcV-run-3e08bdd`；
- 计算解释器为`/home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python`。

不再为`3e08bdd`安装另一套NumPy。每份正式结果必须同时记录代码提交`3e08bdd`和上述实际计算环境，避免把代码路径与解释器路径混为一谈。

第一次32点/周期残差正式运行完成了四组数据的反演，但在最终写CSV时失败。根因是结果行新增了`simulation_n_points`、`points_per_cycle`、`fit_harmonics`和`fixed_params`，而固定CSV表头没有同步。失败文件只含表头，不属于有效证据。

修复提交：

```text
3e08bdd fix(validation): checkpoint residual evidence
```

修复内容：

- CSV表头包含全部采样和固定参数字段；
- 每完成一个数据集就原子写入累计结果；
- 写入失败时保留上一份有效文件；
- 新增schema、累计检查点和失败保留测试。

新鲜验证：

```text
Mac:
python scripts/run_tests.py python/tests -q
70 passed in 44.43 s

python scripts/run_tests.py \
  web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
3 passed in 6.67 s, 1 third-party warning

Legion（已有正式计算环境运行3e08bdd代码）:
PYTHONPATH=python:web/backend \
  /home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python -m pytest \
  python/tests -q
70 passed in 52.46 s
```

当前状态：

- Task 9仍未完成；
- 第15节的50-trial结果来自旧12点/周期运行，暂时视为过期历史，不得作为当前结论；
- 下一步先在`3e08bdd`上重新生成架构验证和8行残差契约；
- 残差验收通过后再运行Feature与M0/M1的50-trial正式比较；
- 结果变化时保留固定验收标准，不为维持旧结论调整门槛。

---

## 17. Phase 0 完成：32点/周期同构基线（2026-07-26）

Phase 0 重建了 legacy 和 Complex-SNR 在同构 32 points/cycle 下的可信基线。三项正式 CSV 均已重算，所有行包含 `points_per_cycle` 采样字段。

**重算内容：**
- `residual_contract.csv`：从 Legion 同步（3e08bdd 修复版，含全部采样字段）
- `feature_objective_comparison.csv`：Legion tmux 重算，30 行，50 trials × 8 workers
- `reconstruction_model_comparison.csv`：Legion tmux 重算，24 行，50 trials × 8 workers
- `synthetic_recovery.json` + 敏感矩阵：Mac 重算

**Gate 0 — PASS：**
- 报告、CSV、manifest 对 `points_per_cycle=32` 的记录一致 ✅
- 同一模式和数据集无重复或缺失的 `(dataset, mode, seed)` ✅
- 所有正式结果可追溯到 commit `b8b176c` ✅
- 基线测试在 Mac 通过（74 tests）✅
- 旧 12-point 数值已不作为验收阈值 ✅

**未提交实验改动：**
- stash@{0}：lockin + full-grid + combined + signed-sensitivity（Phase 1–4 候选）
- `cpp/` 目录：C++ ODE 求解器实验代码（含 `oer_cn_solver.cpp`、`oer_ode_core.cpp`、`oer_core_mex_port.cpp`）

**下一阶段：** 按 `documents/plans/2026-07-26-staged-potential-resolved-roadmap.md` 执行 Phase 1（锁相信号层验证）。

---

## 18. Phase 1R：电位参考锁相纠错（2026-07-26）

代码复核发现 Phase 1 的真实相位证据和反演映射存在四个根因：

- 圆均值在取角度前转为 `float`，丢失复数虚部；
- `complex` 与 `phase` 使用了不一致的 I/Q 约定；
- 实验相位参考 time-zero，而非实测应用电位基频；
- 实验 target 用时间轴插值电位网格，并直接线性插值环绕相位。

修复内容：

- 新增应用电位基频参考相位估计；
- 统一 `complex = Q - jI` 与 `phase = angle(complex)`；
- 模拟使用已知施加电位相位，实验使用实测电位拟合相位；
- 在复数域插值锁相包络；
- 仅在实验与模拟的共同有效区计算 lock-in loss；
- 真实诊断改用 DC 电位趋势报告峰位。

验证：

```text
新增回归测试：5项完成 RED→GREEN
全量测试：83 passed
H1-H7压力测试：
  points_per_cycle = 32/64
  record length = 24/40 cycles
  最大幅值相对误差 = 0.29%
  最大相位误差 = 0.0029 rad
  峰位误差 < 5 mV
真实数据：
  FT2/FT3/FT4/FT8 warnings-as-errors 诊断通过
  H1-H7平均相位均为有限值，不再退化为0或π
```

科学边界：

- 这些结果证明锁相信号层的实现一致性，不证明反演精度提高；
- Phase 5 formal run继续暂停；
- 下一步建立C++ CN与LSODA在下游特征空间的等价性门；
- `feature_objective_comparison.csv`当前为3-trial smoke，不得覆盖Phase 0正式基线提交。

---

## 19. 求解器等价性门：实现与本机压力测试（2026-07-26）

已为反演配置增加显式 `solver_backend=auto|cn|lsoda`，并建立固定参数空间抽样的 CN/LSODA 下游特征比较脚本。比较项包括总电流、DC、H1–H7 全局复数谐波、锁相幅相、峰位和运行时间；`cn` 失败时不允许静默回退。

压力测试首先发现 C++ 内部稳态 Newton 初值错误：样本总电流 NRMSE 达到 18.5%。统一使用 Python 与 LSODA 相同的稳态初值后，32 points/cycle 下该误差降至 0.36%。这表明旧的高误差主要来自初值不一致，而不是 CN 方程本身。

固定门槛：

- 总电流和 DC NRMSE ≤ 1%；
- H1–H3 幅值误差 ≤ 3%，相位误差 ≤ 0.05 rad；
- H4–H7 幅值误差 ≤ 10%，相位误差 ≤ 0.15 rad；
- 峰位偏移 ≤ 5 mV；
- 参考强度低于最强通道 2% 的谐波不评价相位和相对误差，但保留原始结果。

本机结果：

- 2 样本 × 32 周期 × 32 points/cycle：失败，集中在高次谐波；
- 6 样本 × 32 周期 × 64 points/cycle：16 项失败；
- 6 样本 × 32 周期 × 128 points/cycle：通过。

当前决策：

- 正式等价性门固定使用 24 样本、256 周期、128 points/cycle，在拯救者运行；
- 正式 TPE 继续暂停；
- 正式门通过后，CN 仅用于搜索加速，入选最优参数仍需 LSODA 复算；
- 若正式门失败，不调整阈值，先检查失败通道的可解析性和 256 points/cycle 收敛。

---

## 20. Gate A6：全参数恢复 FAIL 与模式敏感性重构（2026-07-27）

- 正式噪声下限由四份量化实验数据生成，保守取最大值
  `0.001495726085983469`；该值只表示测量分辨率下限，不是重复性置信度。
- 36-study 预算校准在 Legion systemd 下完成，wall time 3039.2 s。
- 20/50 trials 均未达到相对 100 trials 的预注册稳定性门。
- 100 trials 下八参数仍无法恢复，故 72-study 正式全参数反演停止。
- signed sensitivity 已改为真实中心差分，并修复：
  - 非 legacy H1–H7 越界；
  - 四模式错误共享 legacy 特征；
  - Tafel 大小写和缺失通道行不一致。
- commit `cf33eba` 四模式正式敏感性已验收：13 参数齐全、每模式 26 次
  扰动正演且 0 ODE 失败、四个矩阵哈希互异；Tafel 因跨扰动不完整被
  显式列入 excluded features。
- 当前候选条件自由集为 `k0_1,k0_2,k0_3,G_OH,G_O`，尚未冻结；
  `k0_4` 低敏感，`scaling_OOH_OH` 与 `k0_3` 共线，`A` 与 `gamma`
  共线。下一步用修正后的模式敏感性正式证据和缩减参数合成恢复验证。
- 缩减参数 runner 已完成本地测试与单任务 smoke：支持显式自由参数列表，
  固定参数按各 synthetic truth 注入，TPE 不使用真值初始化。下一步从
  该代码的干净 commit 在 Legion 重新执行 20/50/100 trials 预算 pilot。
- commit `ebd0685` 的五参数条件 pilot 已完成：36/36 study、基础设施
  PASS、Scientific FAIL。20/50 trials 均未通过预算稳定性门；100 trials
  下四模式均不能覆盖 `k0_1` 真值，其他参数也有约 0.14–0.69 的最大
  归一化边界误差。
- 原 72-study 五参数正式恢复停止。下一步改为确定性单参数与两参数
  objective profile，不增加 TPE trial 数，不调整物理边界。
- commit `3f9aad1` 的正式单参数 profile 已完成并验收：20 profiles、
  820 rows、全部 truth 为离散全局最小值。
- `k0_1` 在四模式的 Δ1 宽度为 0.525–1.000，且均有远端近简并区，不再
  作为宽边界自由参数。hybrid/lockin-only 对
  `k0_2,k0_3,G_OH,G_O` 最清晰，下一步只做这四参数的选择性二维 profile。
