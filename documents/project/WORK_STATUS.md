# OER-FTAcV 历史工作记录（2026-07-18 起）

> 本文件只保存按时间追加的历史执行记录，不是当前计划入口。当前架构、
> Gate、接口和未完成目标见 `PROJECT_SUMMARY.md`；当前行动见
> `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`。
> 除纠正事实错误外，不重写旧记录。旧记录引用的已完成计划或旧架构报告
> 可能已从当前目录删除，其结论已汇入总览，原文件可从 Git 历史恢复。

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
## 0.7 Gate A7 关闭：工作流正式验收与故障注入（2026-07-27）

- 状态：**PASS**（工程基础设施），全链路在真实 Legion 环境通过。
- 配置：commit `cbbcda5`，spec `a7_workflow_smoke`，确定性测试脚本
  `scripts/a7_gate_test.py`。
- 全链路：doctor→prepare→smoke→run→status→sync→verify 全部通过，
  systemd 与 STATUS.json 双通道一致，spec_hash 写入并验证。
- 故障注入（均按协议正确分类，不进入下一阶段）：
  | 故障 | 注入方式 | 分类 | Gate |
  |------|----------|------|------|
  | 数值失败 | exit 2 | FAIL_NUMERICAL | smoke gate 拒绝 |
  | 缺文件 | exit 0 但不写 csv | FAIL_STRUCTURE | smoke gate 拒绝 |
  | 哈希冲突 | manifest 占位符 | FAIL_TRANSPORT | verify gate 拒绝 |
- 边界：PASS 只证明工程基础设施可用，不证明科学门槛通过。
- 证据：`~/OER-FTAcV-archive/results/cbbcda5/a7_workflow_smoke/`；
  Legion `worktrees/cbbcda5/`。
- 下一步：A6 缩减参数合成恢复完成后，用 oer-wf 执行正式 TPE。



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

本节保留当时的内部诊断计划；原临时交接文件已在文档清理时移除。

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

## 21. Gate A6 二维耦合诊断：CN 加速 + 增量输出（2026-07-28）

- 状态：**正式 2D profile 完成**，12 profiles × 441 点，CN 后端 ~40 min。
- 配置：commit `1d6bf7a`，21×21 网格，CN backend，8 workers。
- runner 修复：
  - 增量 CSV 写入（每个 profile 完成即追加，不再死寂四小时）
  - Worker 5 分钟进度报告（`[wf:profile] hybrid__G_OH__G_O 328/441 (74%)`）
  - 主进程 profile 完成日志（`[wf:progress] 8/12 lockin_only__k0_2__G_O (441 points)`）
  - `--backend cn|lsoda`，默认 CN（~5-10× 加速）
- 二维耦合诊断结果：
  - **全部 12 profiles：truth = global minimum** ✅
  - **G_OH ↔ G_O 强补偿**（r=+0.999，对角谷）——hybrid 和 lockin_only 均确认
  - **k0_2, k0_3 与其他参数正交**（r≈0）——可独立约束
  - **Δ1 widths = 0**：损失面极陡，21 点网格无法解析近 truth 区域；需 41 点网格获取定量耦合值
- 证据：`~/OER-FTAcV-archive/results/1d6bf7a/a6_2d_profiles/20260728_044432/`；
  5292 行，12 summaries。
## 22. Gate A6 二维耦合诊断 41 点网格重算（2026-07-28）

- 状态：**完成**，CN + 41×41 grid，12 profiles，20172 rows，0 ODE failures。
- 配置：commit `1d6bf7a`，spec 注入 `--grid_points 41`，CN backend，8 workers。
- 结论（L1 工程事实）：
  - **全部 12 profiles：truth = global minimum** ✅
  - **G_OH↔G_O 补偿**（r=+0.999，对角谷）—两模式确认
  - **k0_3↔G_OH 补偿**（r=+1.000，对角谷）—**41 点 grid 新发现**，21 点未探测到此耦合
  - **k0_2 与其他全部独立**（r≈0，Δ1x=0.025）—可自由
  - **k0_3↔G_O 独立**（r≈0）—可同时自由
  - **Δ1 widths 仍集中于 k0_2**（0.025），其他对为 0——损失面极陡，41 点仍不足以完全解析
- 对 A6 自由参数集的影响：
  - **不能同时自由**：G_OH↔G_O（标度关系固定比例），k0_3↔G_OH（选择其一）
  - **可自由**：k0_2（独立），G_O（与 k0_2/k0_3 均不耦合）
  - **候选最小自由集**：k0_2 + G_O + 一个热力学自由度（固定 G_OH/G_O 比）
- 证据：`~/OER-FTAcV-archive/results/1d6bf7a/a6_2d_profiles/20260728_064133/`；
  20172 行。
- 下一步：
  1. 按新的耦合约束定义最终自由参数集
  2. 在缩减参数集上重跑合成恢复（synthetic recovery），完成 Gate A6
  3. 通过后冻结参数集，启动真实数据 TPE

## 23. A6 job级断点续跑与8 Workers（2026-07-29）

- recovery runner 增加显式 `--resume`；默认模式仍拒绝覆盖已有科学输出。
- 每个job完成后由父进程按计划顺序原子替换 `results.jsonl`，中断后只运行缺失job。
- 恢复严格校验源码commit、dirty状态、科学配置、完整job集合和
  `job_input_hash`；旧结果、损坏JSONL、重复或未知job均拒绝。
- `oer-wf 0.6.4` 增加 `--resume-timestamp`。只有spec声明
  `supports_resume: true` 才能复用精确历史目录；不能与 `--force` 混用。
- A6正式配置从4改为8 workers；smoke仍为1 job × 5 trials。
- 本机完整测试：255 passed。真实smoke首次运行成功，随后以不同workers恢复时
  复用1/1 job、执行0个新job。
- Legion commit `dc180db` smoke通过：1 job × 5 trials，四个必需文件和
  `STATUS=SUCCESS`；随后在同一目录恢复，`reused_jobs=1`、
  `executed_jobs=0`、`passed=true`。
- 当前旧commit正式计算不支持热更新或续跑；新功能只用于后续由
  `dc180db`及更新版本启动的任务。

## 24. Gate A6 三参数正式合成恢复（2026-07-29）

- commit：`a7bc9e4dd274013137b714c7d120bddf175565b1`
- 配置：`k0_2,k0_3,G_O`，4 modes × 3 truths × 2 noise levels ×
  3 seeds = 72 jobs；100 trials/job；LSODA；4 workers。
- wall time：13974.94 s（约3 h 52 min 55 s）。
- 基础设施PASS：systemd退出码0，`STATUS=SUCCESS`，72/72完成，
  72个唯一job，组合齐全，数值有限，commit匹配且`dirty=false`。
- optimizer执行成功不代表科学恢复成功。科学Gate FAIL：
  - `k0_2`真值覆盖19/24；
  - `k0_3`真值覆盖15/24；
  - `G_O`真值覆盖13/24；
  - 合计47/72，无噪声24/36，有噪声23/36。
- 最差组中位归一化边界误差为0.2988，最差单seed误差为0.6479。
- 决策：不冻结该三参数联合自由集，不启动真实数据正式TPE，不增加trials、
  不扩大边界、不调整阈值。下一步回到单参数/两参数恢复或实验信息量设计。
- 正式证据：
  `results/formal/identifiability/gate-a6-reduced-recovery-a7bc9e4/`。
- 独立基础设施缺陷：`wf verify`未加载该任务的expected files，错误使用
  `summary.csv/manifest.json`默认契约；不影响本次人工严格验收结论。

## 25. oer-wf 0.6.5 冻结验收契约与A6科学门（2026-07-29）

- 根因确认：旧 `wf verify` 没有 TaskSpec 上下文，硬编码
  `summary.csv/manifest.json/STATUS.json`，会把 A6 合法 JSON 结果误报为
  structure FAIL。
- `wf run` / `wf smoke` 现在在计算启动前原子写入
  `task_spec.snapshot.yaml`；写入失败即停止启动。snapshot 只包含白名单任务
  字段并随结果同步归档。
- `wf verify` 只读归档 snapshot 获取 expected files、validators 和专用配置；
  无 snapshot 的旧归档必须显式传完整 `--expected-file` 与 `--validator`，
  否则报告 `verification contract unavailable`，不再猜测默认契约。
- 新增 A6 `recovery_gate`，将结构错误、非有限数值和科学恢复失败分别归类为
  structure / numerical / scientific。
- A6 summary 拆分为 `execution_passed` 与
  `scientific_gate_passed=null`；`passed` 仅保留为前者的弃用别名。
- 验证：57 个 oer-wf 测试通过；项目联合测试共收集 259 项并全部通过；
  CLI help、Python 编译和 `git diff --check` 通过。尚未部署 Legion 或重验旧
  A6 归档；旧归档需显式契约，不能伪造 snapshot。

## 26. Gate A6 Stage 1 CN 单参数恢复（2026-07-29）

- 实现提交：`d0defa7`；配置冻结提交：`8d51342`。
- 本地验证：60 个工作流测试、210 个 Python 测试和真实 CN smoke 通过。
- Legion 验证：三个任务的 smoke 均通过。证据只保留在远端：
  - `/home/lsy/OER-FTAcV/worktrees/d0defa7/a6_recovery_cn_k0_2/results/a6_recovery_cn_k0_2/_smoke_20260728_210854`
  - `/home/lsy/OER-FTAcV/worktrees/d0defa7/a6_recovery_cn_k0_3/results/a6_recovery_cn_k0_3/_smoke_20260728_210905`
  - `/home/lsy/OER-FTAcV/worktrees/d0defa7/a6_recovery_cn_G_O/results/a6_recovery_cn_G_O/_smoke_20260728_210916`
  - smoke 未同步 Mac；下列 Mac 路径只对应正式结果。
- 正式结果：
  - `k0_2`：72.7169 s；真值覆盖 12/24；Tafel fail 63。
  - `k0_3`：71.8919 s；真值覆盖 21/24；Tafel fail 1492。
  - `G_O`：74.0703 s；真值覆盖 15/24；Tafel fail 491。
- 三项均有 5 个契约文件、`STATUS=SUCCESS`、72/72 个唯一 job、24 个
  group、完整 `4 modes × 3 truths × 2 noise × 3 seeds` 组合、
  `n_ode_fail=0`、boundary violations=0、`dirty=false`。
- 基础设施与当前数值门 PASS；三项都因真值覆盖不足而 scientific FAIL。
  Tafel fail 未纳入本轮冻结 gate，保留为独立证据，不改写为数值门失败。
- 按预注册剪枝规则，所有两参数组合均失去资格；不启动 Stage 2 CN、
  LSODA 复核或真实数据正式 TPE。
- Mac 归档：
  - `/Users/liushiyu/OER-FTAcV-archive/results/d0defa7/a6_recovery_cn_k0_2/20260728_210953`
  - `/Users/liushiyu/OER-FTAcV-archive/results/d0defa7/a6_recovery_cn_k0_3/20260728_211150`
  - `/Users/liushiyu/OER-FTAcV-archive/results/d0defa7/a6_recovery_cn_G_O/20260728_211332`

## 27. Gate A6 Recovery Gate v2 离线复核（2026-07-29）

- v1 的 `seed_min <= truth <= seed_max` 会把三个高精度但同侧的估计判为
  FAIL，也可能让跨真值但离散度很大的结果 PASS；四种 mode 捆绑判定还会
  使较差 mode 否决较好 mode。
- v1 的三项 Stage 1 scientific FAIL 保持不变。v2 使用独立版本，不回写
  或覆盖历史结论。
- v2 按 `(parameter set, feature_mode)` 独立检查六个 truth/noise group：
  每组中位归一化误差 `<=0.025`、最大误差 `<=0.05`、seed 归一化极差
  `<=0.05`、boundary hit rate `=0`、study 全成功。阈值来自既有 41 点
  profile 的 `1/40` 工程分辨率，不解释为置信区间。
- 测试驱动实现于
  `config/oer-wf/oer_wf/validators/recovery_gate.py`；未声明
  `gate_version` 时仍执行 v1。新增 5 项针对 v2 的回归测试。
- 本地验证：67 个 oer-wf 测试、210 个 Python 测试和 Markdown 链接审计
  通过。
- 三份 Stage 1 归档无需重算即可离线复核：
  - `k0_2`：`hybrid,lockin_only` 通过；选择 `hybrid`；
  - `k0_3`：`complex_snr,hybrid,lockin_only` 通过；单参数排序选择
    `complex_snr`；
  - `G_O`：`hybrid,lockin_only` 通过；选择 `hybrid`。
- 为避免引入尚未验证的参数专属复合目标，Stage 2 采用三个参数共同通过的
  `hybrid`。该决定只允许启动多参数 CN 筛选，不能把单参数结果表述为联合
  恢复 PASS；CN 候选仍必须由 LSODA 同配置确认。
- 设计与压力测试：
  `documents/specifications/2026-07-29-recovery-gate-v2-proposal.md`。

## 28. Gate A6 Stage 2 两参数 CN 配置冻结（2026-07-29）

- recovery runner 新增显式 `--feature-modes`，默认仍为四模式；Stage 2
  冻结为只运行 `hybrid`。选择进入 job plan、summary 和断点指纹，不能与
  其他 mode 的结果混用。
- runner 实现提交：`fdc955f`；v2 支持非 legacy-only 任务的修复提交：
  `732bf5d`。
- 三份 Stage 2 task spec 固定到 `732bf5d`：
  - `config/oer-wf/examples/a6_recovery_cn_k0_2_k0_3.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_k0_2_G_O.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_k0_3_G_O.yaml`
- 每项正式配置：`hybrid`、CN、3 truths × 2 noise × 3 seeds = 18 jobs、
  100 trials/job、8 workers；v2 阈值和完整组合均写入 snapshot 契约。
- Mac 真实 CN smoke：三个组合各 1 job × 5 trials，均
  `execution_passed=true`、`n_ode_fail=0`，`best_params` 与指定双参数
  完全一致。直接运行科研脚本只生成三个科学文件；远端 `wf smoke` 的
  `STATUS.json` 仍须由 wrapper 单独验收。
- 本地回归：71 个 oer-wf 测试、212 个 Python 测试和 Markdown 链接审计
  通过。
- 本机临时证据：
  `/tmp/oer-stage2-smoke.rarwRp/`。该路径不提交 Git，也不作为正式科学
  证据。
- 下一步：完成全量测试并提交 spec；随后按环境文档部署 Legion，只先跑
  三个 `wf smoke`。任一 smoke 基础设施失败则停止 formal。

## 29. Gate A6 Stage 2 两参数 CN 正式结果（2026-07-29）

- 远端 `oer-wf` 更新到 0.6.5，71 项远端测试通过；三个 worktree 均从
  `732bf5d` 创建，CN Linux 动态库可加载且工作树只显示允许的 `.wf_lock`。
- 三个 `wf smoke` 均通过：五个契约文件齐全、`STATUS=SUCCESS`、
  1 job × 5 trials、`n_ode_fail=0`。
- 为避免 24 workers 争用 16 线程，三项 formal 串行运行，每项 8 workers。
- 三项均执行与 provenance PASS，但 Recovery Gate v2 scientific FAIL：
  - `k0_2,k0_3`：21.94 s；最大误差 0.231369；最坏中位误差
    0.177096；seed 极差 0.251891。
  - `k0_2,G_O`：22.28 s；最大误差 0.180300；最坏中位误差
    0.026136；seed 极差 0.202199。
  - `k0_3,G_O`：21.76 s；最大误差 0.117248；最坏中位误差
    0.039060；seed 极差 0.147170。
- 三项均 18/18 jobs、`n_ode_fail=0`、boundary hit rate 0。所有组合停止，
  不启动三参数任务或 LSODA 复核，不增加 trials，不调整 v2 阈值。
- 离线 objective 归因：54/54 个 study 中真值 objective 均优于 TPE
  最优；无噪声真值 objective 为 0，而 TPE 仍有 0.10–0.86 的中位损失。
  当前主要失败原因是 100-trial TPE 未找到狭窄真值盆地，不能直接解释为
  参数结构不可识别。
- 下一步：固定 100 次 forward-evaluation 预算，比较至少一个全局—局部
  混合优化器与当前 TPE；算法必须不使用 synthetic truth 初始化。先跑
  代表性小规模基准，通过预注册门后才重做全部恢复。
- 完整验收、归档路径和 SHA-256：
  `results/formal/identifiability/gate-a6-stage2-cn-732bf5d/acceptance.md`。

## 30. Gate A6 固定预算优化器基准设计（2026-07-29）

- 冻结三种算法：现有 TPE、`sobol_pattern`、`de_fixed`。
- 每种算法每个 study 恰好 100 次 optimization objective call；额外 truth
  objective 只作 post-run diagnostic，不反馈给算法。
- `sobol_pattern` 固定为 64 点 scrambled Sobol + 36 次有界 pattern
  search；`de_fixed` 固定为 20 个体初始种群 + 4 代
  `DE/rand/1/bin`，当前版本只接受二维问题。
- 开发集固定为三个参数组合的 `center/no-noise/seed-7`，共 9 个 study。
  替代算法必须在三个组合的每个参数上均达到归一化误差 `<=0.05`，否则
  停止，不运行确认集。
- 候选冻结后只运行一次剩余 51-study 锁定确认集。该集合不是盲测，不报告
  为外部验证；完整结果仍按 Recovery Gate v2 判定。
- 设计文档：
  `documents/specifications/2026-07-29-a6-fixed-budget-optimizer-benchmark-design.md`。

## 31. Gate A6 固定预算优化器开发门（2026-07-29）

- 实现提交：`a5b93f55e540682cc8cddb1fabbe63a7e0e92326`；任务规格提交：
  `a235cd1`；spec hash：
  `sha256:94e1b53827390b5f8b9bac8018c871bb81d79b817edd7bc38d6b70cac38f870d`。
- Legion 正式任务 15 秒完成：9/9 job、900/900 optimization calls、
  9 次 post-run truth diagnostic、`n_ode_fail=0`、`STATUS=SUCCESS`。
- 独立 `wf verify` 重算结构和选择后 PASS，冻结唯一候选
  `sobol_pattern`：
  - 最坏参数误差 0.024110；
  - 中位参数误差 0.001296；
  - 最大 objective regret 0.484578。
- `de_fixed` 最坏误差 0.050948，超过 0.05 门；TPE 仅作为基线，不进入
  确认候选。
- 首次 smoke 因远端 `$变量` 转义使动态库复制路径退化为 `/code`，
  按协议 `FAIL_INFRA`；改用完整绝对路径后第二次 smoke 通过。失败结果未
  进入科学判断。
- 正式原始归档：
  `/Users/liushiyu/OER-FTAcV-archive/results/a5b93f5/a6_optimizer_development_cn/20260728_224911`。
- 完整验收与哈希：
  `results/formal/identifiability/gate-a6-optimizer-development/acceptance.md`。
- 下一步只编写并执行一次锁定的 51-study `sobol_pattern` CN 确认集；
  不直接启动 LSODA、三参数扩展或真实数据正式反演。

## 32. Gate A6 Sobol 锁定确认集（2026-07-29）

- 冻结实现 commit `1015a38364b514f597b2023478cb29659594669e`；
  task id `1015a38/a6_optimizer_confirmation_cn`；spec hash
  `sha256:7f69cd553677456be87eabd49621b751116721ad004dfa80e8c13206ad3a061e`。
- Legion 三参数对 smoke 通过：3 jobs、每组 100 calls、总计 300
  evaluations、`n_ode_fail=0`，科学门保持 `null`。
- 正式确认 54 秒完成：51/51 jobs、5100/5100 optimization calls、
  51 次 post-run truth diagnostic、`n_ode_fail=0`、
  `STATUS=SUCCESS`。
- 独立 validator 从 51 条确认证据与 3 条冻结开发证据重算结构和
  Recovery Gate v2。首次结构 FAIL 仅由失败标签排序不同造成；修复排序
  契约后原归档不变即通过结构门。
- 三参数对全部 scientific FAIL：
  - `k0_2,k0_3`：max 0.191743；median 0.001545；dispersion 0.192928；
  - `k0_2,G_O`：max 0.191191；median 0.014780；dispersion 0.192767；
  - `k0_3,G_O`：max 0.246298；median 0.036859；dispersion 0.270408。
- eligible pairs 为空。按预注册分支停止 Gate A6 多参数恢复；不启动
  LSODA、三参数扩展或真实数据正式反演，不增加预算或修改阈值。
- 完整验收与哈希：
  `results/formal/identifiability/gate-a6-sobol-confirmation/acceptance.md`。

## 33. Gate A1 实验数据与采样契约（2026-07-29）

- 严格解析器拒绝额外列、表头、非有限值、倒序和重复时间；不再静默排序、
  去重、裁剪或插值。
- 四份原始文件均为 65,536×3，哈希与冻结注册表一致；文件末行无换行，
  `wc -l` 的 65,535 不是数据点数。
- 初版诊断用 `median(dt)` 估计采样率，受十进制时间戳量化影响会把
  1280 Hz 误估为 1282.05 Hz。正式运行前增加量化时间戳回归测试，改为
  总时长名义网格；设计与计划同步修订。
- commit `a57d42f` 的正式本机审计：
  - 四文件结构 PASS；
  - 采样数值 PASS；
  - 独立 validator 重算一致；
  - 元数据 `FAIL_METADATA`，`eligible_for_inversion=false`。
- 四份数据均缺少三列单位、电位参考和仪器预处理的一手记录。旧代码中的
  V/A/s 只保留为 `legacy_assumption`，不能用于关闭 Gate。
- Gate A1 工程实现完成，但总 Gate 未关闭；真实数据正式反演继续禁止。
- 完整验收：
  `results/formal/data_contract/gate-a1-a57d42f/acceptance.md`。

## 34. Gate A2 物理不变量正式门（2026-07-29）

- 正式执行 commit `6486d6958ef1894301d5d4862cd65832b42a7cb7`；
  12 个冻结合成案例，LSODA，32 cycles，128 points/cycle。
- 独立 validator 重算结论：`FAIL_NUMERICAL`，禁止进入下一 Gate。
- 通过项：
  - 72 点冻结 RHS 基线最大相对误差 `1.66e-16`；
  - M0 回退状态和电流误差均为 0；
  - 12/12 稳态通过，热力学闭合误差均为 0；
  - 11 个完成轨迹的电流闭合误差均低于 `5.05e-16`。
- 失败项：
  - `thermo-edge` 瞬态 LSODA repeated convergence failures，最终
    `Unexpected istate`；
  - 其余 11 个轨迹的边界投影触发次数均非零，范围 68–1042；
  - 最坏覆盖度最小值 `-4.43e-7`，最坏覆盖度和误差 `1.43e-7`，
    均超过冻结 `1e-8` 门。
- 不调整案例、阈值或求解容差，不删除失败轨迹。下一步仅诊断边界投影破坏
  守恒和 `thermo-edge` 刚性来源；真实数据正式反演继续禁止。
- 完整验收：
  `results/formal/physics_invariants/gate-a2-6486d69/acceptance.md`。

## 35. Gate A2-R 守恒积分修复门（2026-07-29）

- 设计与实现提交：
  - `87ddd0f`：冻结 A2-R 设计与计划；
  - `f8b00b0`：删除破坏化学计量守恒的逐分量边界投影；
  - `20b7297`：加入分量绝对容差和显式 LSODA→BDF 回退；
  - `6e600dc`：加入正式 runner；
  - `496a701`：加入独立 validator。
- 正式结论：`PASS`；独立 validator 重算一致。
- 12/12 案例完成：
  - 11 个常规案例保持 LSODA，无回退；
  - `thermo-edge` 保存 LSODA `Unexpected istate` 后，从原始初值用 BDF
    完整重启。
- 最坏覆盖度最小值 `-5.70e-9`；最坏覆盖度和误差 `3.75e-12`；
  最坏电流闭合误差 `4.99e-16`。
- BDF–Radau 交叉验证通过：覆盖度最大差 `2.42e-6`、表面电位最大差
  `1.07e-5 V`、电流 NRMSE `8.93e-7`。
- 冻结 RHS 基线和 M0 回退均通过；旧 A2 FAIL 归档未修改。
- Gate A2 的数值修复路径据此关闭，可以继续下一底层架构 Gate；但 A1
  仍为 `FAIL_METADATA`，真实数据正式反演继续禁止。
- 完整验收：
  `results/formal/physics_invariants/gate-a2r-496a701/acceptance.md`。

## 36. Gate A5 特征通道契约正式门（2026-07-29）

- 实现提交：
  - `1f6f18b`：构建目标侧不可变通道契约；
  - `d5bce51`：候选按冻结通道评价，缺失值固定失败；
  - `86704e6`：加入四数据集 × 四模式正式 runner；
  - `13adcb1`：加入产物哈希和独立 validator。
- 正式执行 commit：
  `13adcb1ffa6f38feaee7b3951b0303489ac131ad`。
- runner 与不导入 runner/反演模块的独立 validator 均为 `PASS`。
- 16/16 个 `(dataset_id, feature_mode)` 记录完整；10 个唯一结构哈希。
  legacy 和 lock-in-only 跨数据集结构相同时允许共享哈希。
- 所有活动权重有限且严格正，所有非活动块具有合法排除原因，分母等于
  活动损失权重和。
- 16/16 个候选缺失注入均返回固定 `1e9` 惩罚，特征失败计数增加 1。
- FT4、FT8 的 complex H3 因低于冻结 SNR 门而明确排除；这不等于实验中
  不存在 H3。
- 本门未运行 TPE，只关闭候选不变的观测/损失契约。A1 仍为
  `FAIL_METADATA`，真实数据正式反演继续禁止。
- 完整验收：
  `results/formal/feature_channel_contract/gate-a5-13adcb1/acceptance.md`。

## 37. Gate A6 参数角色失败关闭（2026-07-29）

- 实现提交：
  - `48e4f51`：新增 13 参数登记表、独立 validator、篡改与口径测试；
  - `75e25ed`：修复 CLI 项目相对 registry 路径并增加回归测试。
- 正式关闭归档绑定干净 commit
  `75e25edab82dc9db980a77c381f6baf1961024eb`；生成和独立归档复验均
  `PASS`，专项测试 22 项通过。
- 科学状态保持 `FAIL_RECOVERY`：
  `eligible_for_real_inversion=false`、自由参数/窄先验/eligible pairs
  全部为空。
- 角色冻结为 8 个 `fixed` 和 5 个 `diagnostic_only`。前者只表示运行时
  固定，后者禁止报告可信点估计；两者均不支持“数学结构不可识别”的声明。
- 本阶段没有运行数值求解或优化。当前 Gate A6 路线关闭，真实数据正式
  反演继续禁止。
- 完整验收：
  `results/formal/identifiability/gate-a6-closure-75e25ed/acceptance.md`。

## 38. 项目总览与交接文档重构（2026-07-29）

- `PROJECT_SUMMARY.md` 重写为唯一总入口，集中保存项目目标、系统数据流、
  关键接口、Gate A1–A7、数据/参数口径、已完成能力、未完成目标和交接步骤。
- 新建唯一当前计划：
  `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`，分为
  休假期间 V1–V5 和恢复实验后 E1–E7。
- 19 份已完成、失败关闭或被替代的实施计划从当前目录删除；旧
  `architecture_validation_report.md` 的有效结论已合并进总览。原文件仍可
  从 Git 历史恢复。
- `WORK_STATUS.md` 保持历史记录职责，不再维护未来路线；根 README、
  文档 README 和 `PROJECT_WORKFLOW.md` 已指向新入口。
- 本次不修改代码、数据、配置和正式结果，不改变 A1 `FAIL_METADATA`、
  A3 `FAIL` 或 A6 `FAIL_RECOVERY`。

## 39. V1 用户声明元数据补录（2026-07-29）

- 实现提交：
  `7cf548f32c07652b4bc1c8339bfc926f963c8fd7`。
- FT2、FT3、FT4、FT8 均登记为电位、电流、时间三列，单位和标尺为
  `V vs RHE`、`A`、`s`；来源等级为 `externally_declared`。
- 来源说明明确负责人不是原实验执行者；配套 CHI CV 文件头只作为
  `V` 和 `A` 的辅助一致性证据。
- `instrument_preprocessing.value=null` 且
  `source_kind=unresolved`；未把“除 RHE 校正外未报告处理”改写成
  “确认无预处理”。
- 四个原始文件 SHA-256 均未变化；专项测试 11 项、全量测试 374 项通过。
- 正式 runner 与独立 validator 均给出：
  - 结构 PASS；
  - 采样数值 PASS；
  - 唯一缺失字段为 `instrument_preprocessing`；
  - Gate A1 `FAIL_METADATA`；
  - `eligible_for_inversion=false`。
- 完整验收：
  `results/formal/data_contract/gate-a1-7cf548f/acceptance.md`。
- 下一步：V2 条件模型可达性；不启动正式真实数据反演。

## 40. V2 条件模型可达性首轮工程 smoke（2026-07-29）

- 新增 V2 设计与实施计划，冻结 5 个 `diagnostic_only` 参数、seed 29
  scrambled Sobol 512 候选、四数据集分别评价、LSODA、hybrid H1–H3、
  128 points/cycle、128 点特征网格及 16 个固定输入 OAT 场景。
- 实验分析已从 FastAPI 提取到核心包，Web API schema 保持不变；新增
  Sobol、掩码、相位包裹、最坏分量评分、分类优先级和机器任务契约测试。
- runner 的 job hash 绑定 task spec、参数库、source commit 和脏文件内容
  指纹；父进程原子写 JSONL，smoke 明确跳过 stress 且科学分类为 null。
- 首轮真实 LSODA smoke：4 数据集 × 前 8 个 Sobol 候选，2 workers，
  wall time 197.09 s；32 个 job 完整，27 成功、5 个
  `ODE_INITIALIZATION`，各数据集成功数为 FT2=6、FT3=7、FT4=7、FT8=7。
- 独立 validator 对 7 个 runner 文件、原始数据哈希、512 行参数库、
  Sobol 覆盖、32 个唯一 job/hash 和所有成功行评分重算给出 `PASS`。
  本机证据：
  `results/smoke/conditional_reachability/v2-dirty-6b134cd906f9/`。
- 数值门未满足：总体成功率 84.4% < 95%。失败均发生在动态扫描前的
  `calculate_steady_state`；固定 5 s 松弛对低速率候选不足，RHS 范数为
  `1.10e-7` 至 `1.92e-3`，冻结门为 `1e-8`。
- 决策：停止正式 512 候选；先开发并独立验证自适应稳态初始化，不调整
  RHS/ODE 成功率阈值，不删除失败候选，不把 smoke 最近候选解释为参数。
- 未完成：正式 stress job 的独立全量校验、validator `--rerun-best`、
  oer-wf 集成、Legion 正式运行和 V2 科学分类。

## 41. V2 自适应稳态初始化与复验（2026-07-29）

- 根因验证：首轮失败候选继续 Radau 松弛后，分别在累计 50、500 或
  5000 s 达到原 RHS `1e-8` 门；额外单候选墙钟约 0.04–0.10 s。固定
  5 s 预热不足，不支持“候选物理不可解”的结论。
- 修复：`calculate_steady_state_detailed` 使用累计
  5/50/500/5000/50000 s 分段松弛，每段续接前一终态；达到原门即返回，
  达到上限仍失败则停止。未放宽 RHS、覆盖度或守恒门。
- 可追溯性：`ODESolution` 和 V2 JSONL 记录稳态累计时间、最终 RHS 与
  每段 elapsed/RHS/nfev；独立 validator 强制检查合法端点、前缀和最终门。
- 参考验证：默认参数仍在首个 5 s 阶段返回并匹配旧单段结果；冻结慢候选
  与严格 50000 s Radau 参考状态在 `1e-7` 绝对容差内一致。
- 新 smoke：4 数据集 × 8 Sobol 候选，LSODA，8 workers；32/32 成功，
  0 次 BDF 回退，wall time 100.44 s。稳态阶段分布为
  5 s×27、50 s×3、500 s×1、5000 s×1。
- 独立 validator 为 `PASS`，四数据集科学分类均保持 null。证据：
  `results/smoke/conditional_reachability/v2-adaptive-steady-state-smoke/`。
- 验证：专项 53 项、全量 Python 405 项、Web 3 项、布局和 diff 审计通过。
- 决策：初始化数值门关闭；正式 V2 继续等待 validator 的正式 stress
  全量重算、`--rerun-best` 与 oer-wf 集成，不启动真实参数反演。

## 42. V2 oer-wf 本机集成验收（2026-07-29）

- 新增 `conditional_reachability_gate`。该门从归档 snapshot 读取配置，
  调用独立 validator；smoke 不复算最近候选，formal 强制四组
  `rerun-best` LSODA 复算并要求四条证据。
- 新增 `v2_conditional_reachability_lsoda.yaml`：LSODA、8 workers、
  每 worker 单 BLAS 线程、显式 resume、7 个 runner 文件及 STATUS。
  commit 暂为 `UNFROZEN`，禁止直接用于远程正式任务。
- 首次本机 wrapper smoke 在计算前失败：runner 把工作流预写的
  `task_spec.snapshot.yaml` 和 `STATUS.json` 误判为未知输出。新增回归测试
  后，runner 只允许这两个文件和临时状态信号，其他未知文件仍被拒绝。
- 第二次 smoke 完成计算，但手工模拟命令把 7 位 task ID 写错；严格续跑
  又因工作树指纹变化拒绝混合证据。两份失败目录保留，不作验收证据。
- 第三次 smoke 由 TaskSpec 自动生成 task ID。结果为 32/32 job 成功、
  0 次 BDF 回退、98.45 s，FT2/FT3/FT4/FT8 分类均为 null。
- snapshot 驱动的真实 `run_verify` 执行 schema、finite、provenance 和
  独立 V2 gate，共 13 项检查全部通过。验收证据：
  `results/smoke/conditional_reachability/v2-oer-wf-local-smoke-3/`。
- 决策：本机工作流集成门关闭。下一步先完成全量回归，再冻结干净 commit；
  此前不部署 Legion，不启动正式 512+stress 计算。
- 全量回归：oer-wf 92 项、Python 408 项、Web 3 项通过；Web 仅保留既有
  Starlette 弃用警告，Markdown/布局审计和 `git diff --check` 通过。

## 43. V2 正式计算前冻结压力测试（2026-07-30）

- 本轮工作流版本升至 `oer-wf 0.6.6`，用于区分旧 0.6.5 与新增的 V2
  validator、恢复文件契约和正式清洁门。
- 发现 resume 接口不一致：V2 有严格 JSONL 续跑，但 oer-wf 对所有任务
  硬编码要求 `job_plan.json`，因此会在调用 runner 前拒绝恢复。
- 修复：TaskSpec 新增 `resume_required_files`。默认仍为
  `job_plan.json`，保持 A6 行为；V2 显式要求 `task_spec.json`、
  `targets.json` 和 `parameter_library.csv`。
- 发现 formal 清洁门不可达：oer-wf 必然预写未跟踪的 `.wf_lock`、
  STATUS、snapshot 和结果目录，旧 provenance 会把这些运行时文件判脏。
- 修复：只忽略状态为 `??` 的 `.wf_lock` 和 `results/`；已跟踪文件变化、
  删除、重命名及其他未跟踪路径仍判脏，并记录忽略路径。
- 正式预算：2048 base + 512 stress，共 2560 job；8 workers、单 BLAS
  线程。按 32-job smoke 投影约 2.2 小时，保守预算 2–4 小时。
- 当前退出条件：冻结 commit 前不部署；远端 smoke 失败不启动 formal；
  formal 基础设施失败停止验收；合法的不可达或 solver-limited 分类按科学
  结果报告，不改阈值。
- 回归：oer-wf 93 项、Python 408 项、Web 3 项通过；Web 仅有既有
  Starlette 弃用警告，Markdown/布局审计和 `git diff --check` 通过。
- compute commit：`fbda4cff248f498b29e1c054aaab2fcaab24e40f`；V2
  TaskSpec 已绑定该提交，下一步为推送、Legion 部署和远端 smoke。

## 44. V2 远端 smoke、正式启动与工作流状态修复（2026-07-30）

- Legion 远端 smoke 完成 32/32 job，独立 validator 与四组
  `rerun-best` 均通过；provenance 为干净工作树。两个候选在 LSODA
  明确失败后回退 BDF，符合冻结契约。
- 已启动正式 V2：2048 base + 512 stress，共 2560 job；输出目录为
  `results/conditional_reachability/v2/20260729_163222`。本阶段不创建
  自动定时检查，不停止或重启运行中的任务。
- 启动后发现工程状态误判：长时间 `Type=oneshot` 服务执行时 systemd
  为 `activating/start`，旧版只把 `active` 视为运行中；同步
  `systemctl start` 还会让 `wf run` 等待整个任务。
- `oer-wf 0.6.7` 将 `active` 与 `activating` 均视为运行中，并为正式
  启动加入 `--no-block`。两项回归测试先失败后通过，全量工作流测试
  Mac 与 Legion 均为 94 项通过。
- 0.6.7 已同步到 Legion `/home/lsy/oer-wf`。对既有正式 unit 的真实
  查询返回 `running (pid=13191)`，同时保留
  `active=activating`、`sub=start` 和 `STATUS=RUNNING` 原始证据，
  证明修复的是状态解释而非计算进程。
- 当前边界：该修复只改变编排器启动和状态解释，不改变 V2 科学代码、
  solver、阈值、输入或已经运行的正式进程。下一步等待正式结果完成，
  再按冻结 validator 验收；不创建自动定时检查。

## 45. V2 正式结果与条件可达性结论（2026-07-30）

- 正式任务正常结束：systemd `inactive/dead`、Result success、退出码 0，
  STATUS `SUCCESS`；运行 7548.53 s。
- 产物完整：2048 base、512 stress、512 参数库行和四组 target；schema、
  有限值、hash、job 集合、评分与分类独立重建通过。
- 同一冻结 commit、Legion Python 环境和 TaskSpec 单线程变量下，四组最近
  候选 LSODA `rerun-best` 全部通过，正式 validator 为 `PASS`。
- FT2/FT3/FT4/FT8 均为 `NOT_REACHED_WITHIN_LIBRARY`；最近分数为
  15.5203/10.4393/5.2607/6.4683，扩库改进为
  6.484%/2.418%/0%/0%，全部 stress 场景仍未达到门。
- 科学边界：该结论不证明 M0 在连续空间全局不可达，不产生真实参数估计；
  下一科学阶段为 V3 残差归因，而不是继续盲目扩大同一反演。
- 验收可移植性：Mac 及未恢复单线程变量的 Legion 复算会出现最高约
  `1e-5` 指标漂移，不能满足 `1e-8` 逐指标等值门；正式单线程 Legion
  环境通过。未修改阈值，问题登记为 verifier 环境冻结缺口。
- 正式证据：
  `results/formal/conditional_reachability/v2-fbda4cf/`。

## 46. V3 残差归因设计与本机 smoke（2026-07-30）

- 冻结设计：
  `documents/specifications/2026-07-30-v3-residual-attribution-design.md`。
  当前实验待补项推迟到恢复实验后，不作为 V3 阻断项。
- 每组从 V2 得分前 64 个成功候选中，固定选择最近候选和 11 个参数空间
  maximin 候选；正式规模 48 job，不新增 TPE 或大参数库。
- 新增纯残差模块、可续跑 runner、独立 validator、V3 JSON 任务契约和
  `oer-wf 0.6.8` 专用门。DC、幅值和圆周相位分开保存，统一符号为
  `实验 - 模拟`。
- 首次 smoke 的 ODE 均成功，但 lock-in low 区没有有效点，被旧汇总错误
  升级为 job FAIL。修复为 `n_points=0/not-observable`，不填充伪残差。
- 最终任务哈希下本机 smoke 为 4/4 成功；独立 validator 与 oer-wf gate
  均 PASS。专项科学测试 17 项、oer-wf 97 项、全量 Python 425 项通过。
- 下一步：冻结 compute commit，更新 V3 TaskSpec commit 指针，部署
  Legion 后运行真实 workflow smoke；PASS 后启动正式 48-job 任务。

## 47. V3 正式残差归因与验收（2026-07-30）

- compute commit 为 `f82d3918647b`，部署提交为 `ea07033`；TaskSpec
  哈希为 `d98bd972dcdf`。Legion `oer-wf 0.6.8` 全测 97 项通过。
- `doctor` 仅报告已知的远端主仓库脏和 systemd degraded；正式任务使用
  独立干净 worktree，未读取或覆盖主仓库历史结果。
- 远端 smoke 完成 4/4 job，结构检查和冻结工作树独立 validator 均
  `PASS`。
- 正式任务完成 48/48 job，四组各 12 个候选；wall time 127.60 s。
  LSODA 完成 44 个任务，4 个任务按冻结契约回退 BDF。
- 冻结 Legion validator 重建输入哈希、选择、全部残差和标量证据，并
  以 LSODA 复算 FT2/FT3/FT4/FT8 最近候选；正式门为 `PASS`。
- FT2/FT3/FT4/FT8 分别有 11/11/5/7 个通道区段达到至少 9/12 候选
  残差同号。总体得分最强条件关联分别为 `G_OH`、`G_OH`、`k0_1`、
  `k0_1`；不得解释为因果或真实参数。
- Mac 冻结 worktree 重建的候选 ID 和顺序完全一致，但 5 个派生距离相差
  1 ULP（`1.11e-16`）。validator 对完整 JSON 做精确比较，故本机
  `wf verify` 报 `selection mismatch`。该结果属于验证器可移植性
  假阴性，不覆盖冻结 Legion PASS，也没有触发阈值修改。
- `wf verify` 还会重写归档中的 `acceptance.md`，与“只读验收”文档冲突。
  Mac FAIL 副本已保留在本机归档，Legion PASS 文件已从远端恢复；两项
  缺陷均进入项目纠错。
- 正式证据：
  `results/formal/residual_attribution/v3-f82d391/`。
- 下一步进入 V4 实验信息设计。预处理一手记录、独立固定参数和新增实验
  条件继续标为 deferred；休假期间不伪造或补推实验事实。

## 48. V4 实验信息设计实现、smoke 与正式启动（2026-07-30）

- 冻结设计与实施计划：
  `documents/specifications/2026-07-30-v4-computational-experiment-design.md`
  和
  `documents/plans/2026-07-30-v4-computational-experiment-design-implementation.md`。
- V4 只比较未来采集协议在冻结 M0 和 8 个 V3 条件参数点下的局部可分离度；
  不估计真实参数。预处理、面积、负载量、独立 `Ru/Cdl/gamma` 和新增实验
  观测保持 deferred，不阻断本阶段。
- 计算提交为 `6c2084a2acfc8ea2f52956f924a9193366fbf4e6`，工作流部署提交为
  `c084641`。runner 支持 792 个主任务、可选 80 个半步长任务、8 workers、
  job 级原子续跑和严格输入哈希；正式后端为 LSODA/BDF。
- 独立 validator 重建条件、任务、27 块特征、敏感矩阵、两阶段排序、
  半步长方向和推荐次序，并验证全部产物哈希。推荐两项时 formal 要求
  8 条基线复算；`NO_ROBUST_RECOMMENDATION` 是允许的科学退出。
- 本地回归：Python 461 项、oer-wf 101 项、Web 3 项通过。Web 仅有既有
  Starlette 弃用警告。
- 本地 smoke：22/22 正演成功，2 个敏感矩阵，独立 validator `PASS`。
  smoke 的 `NO_ROBUST_RECOMMENDATION` 由 1 个参数点不足正式 6/8 门产生，
  不作为科学结论。
- Legion 已同步 oer-wf 0.6.9，远端 101 项测试通过。固定 worktree：
  `/home/lsy/OER-FTAcV/worktrees/6c2084a/v4_experiment_design_lsoda`。
- Legion smoke 输出：
  `results/experiment_design/v4/_smoke_20260730_101218`；工作流结构门和
  独立 validator 均为 `PASS`。
- 正式任务 `6c2084a/v4_experiment_design_lsoda` 已由 systemd 启动，
  输出目录：
  `results/experiment_design/v4/20260730_101301`。启动后状态为
  `RUNNING`，PID 14126；本项目未创建自动定时检查。
- 待完成：正式任务终态、结果同步、独立 formal 验收、项目科学结论和
  正式证据归档。验收前不得发布唯一协议优先级。

## 49. V4 首轮失败、V4.1 修复与正式验收（2026-07-30）

- 首轮计算提交 `6c2084a2acfc8ea2f52956f924a9193366fbf4e6` 完成
  792 个主任务，其中 782 成功、10 失败。失败全部集中于
  `FT8 / candidate 505 / rank 1 / existing_ft2`。
- 失败 baseline 在累计 50000 s 后 RHS 为 `3.24787198706e-7`，高于
  冻结 `1e-8` 门；独立复算得到 `3.24787198707e-7`，排除并发偶发故障。
- 工程失败同时包含两层根因：
  1. 稳态 `RuntimeError` 被误标为 `FAIL_INFRA`；
  2. 聚合器在失败行前比较空特征名并崩溃。
  旧 job hash 还只绑定配置、未绑定 source commit。
- 稳态诊断证明不是“无稳态”：直接松弛和从 FT8 起始电位跳转在
  500000 s 均达到约 `7.1e-13`，并收敛到相同覆盖度和表面电位。该
  500000 s 是模型数值松弛上限，不代表实验预处理时长。
- V4.1 计算提交
  `fbbba8df521292776e080606a0cc27963466cfb6` 增加 500000 s 端点，
  保持 RHS `1e-8` 门不变；同时修复失败分类、聚合器和绑定 source
  commit/dirty hash 的 run/job hash。部署提交为 `d2fe81e`。
- V4.1 TaskSpec hash：
  `sha256:da9e7e59995c77feb59a94965361d4411b9b54d306a5929bf614b6bf1a8de80b`。
  Legion smoke 为 22/22 成功，工作流与独立 validator 均 `PASS`。
- 正式任务 `fbbba8d/v4_experiment_design_lsoda` 于
  `2026-07-30T11:07:14Z` 至 `11:44:32Z` 运行，8 workers；792 个
  主任务、80 个半步长任务共 872/872 成功，72 个敏感矩阵完整。
- 推荐状态为 `RECOMMEND_TWO`：
  `candidate_5hz_amp_008` 排第一，随后为
  `candidate_10hz_matched_scan`。
- 首次 Mac `wf verify` 因当前部署提交与计算提交不同被 provenance 门
  拒绝；冻结 Mac worktree 又因跨平台线性代数产生约 `1e-14` 的派生
  矩阵末位差异。未恢复正式单线程变量的 Legion 复算也产生最大相对
  `4.55e-5` 漂移。没有调整容差。
- 在冻结提交、Legion 数值环境及
  `OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS=1` 下重跑正式 validator：
  结构、哈希和排序重建通过，8 条独立 LSODA baseline 复算 8/8 通过，
  最终 Gate 为 `PASS`。
- 正式证据：`results/formal/experiment_design/v4-fbbba8d/`。
- 结论边界：V4 PASS 只发布条件模型下的采集协议优先级，不估计真实参数，
  不改变 A1 `FAIL_METADATA`、A3 `FAIL`、A6 `FAIL_RECOVERY`。下一步
  在恢复实验后按该协议补数据和独立约束，再重开 A6-v2。

## 50. oer-wf 0.7.0 冻结远端验收闭环（2026-07-30）

- 修复提交为 `b41aeaa`，真实 Git 状态解析回归修复为 `4492648`；均已
  推送至 `codex/oer-wf-remote-verify`。
- Mac 负责同步归档的文件、schema、有限值、provenance 和哈希检查；
  V2/V3/V4 科学 validator 回到 snapshot 指定的 Legion 冻结 worktree，
  恢复完整 commit、Python 和线程环境后执行。
- 计算归档保持只读；每次完成的验证在
  `~/OER-FTAcV-archive/verifications/` 外置追加 receipt，不覆盖历史结论。
- 本地验证：oer-wf 133 项、项目 Python 466 项、Web 3 项通过；Web 仅有
  既有 Starlette 弃用警告。Legion 部署 `oer-wf 0.7.0`，133 项通过。
- 新 V4 smoke
  `_smoke_20260730_124405` 为 `SUCCESS`；Mac 本地完整性检查和 Legion
  `fbbba8d` 冻结科学门共同 `PASS`，环境键恢复证据完整。
- receipt：
  `~/OER-FTAcV-archive/verifications/fbbba8d/v4_experiment_design_lsoda/_smoke_20260730_124405/20260730T124710.829867Z-24af0876ed738efaaa220eda146e530b8cf95de88508c4927241b5db0f7a82ed.json`。
- smoke 计算归档验证前后内容哈希均为
  `df961e77bc49f25e044dc0456da5a91eb8cb1aae313363b9abad325ab0661e8a`。
  本阶段未修改任何科学阈值或既有 Gate 结论。

## 51. Bonke/Zhang 文献约束并入补实验路线（2026-08-01）

- 决定不新增 Bonke 风格三参数模型；其有效参数不能映射为五步 AEM 的
  微观参数，现阶段新增模型不会解除 A1 或 A6 阻断。
- Bonke 2016 与 Zhang 2018 仅用于冻结补实验要求：独立约束电活性位点
  量，保存完整原始时间序列，加入空白基底和负载量对照，并按既有门评价
  H4–H7。
- V4 推荐保持不变：先采集 5 Hz/0.08 V，再增加 10 Hz/0.16 V 匹配扫描；
  文献不构成事后调整排序或强制纳入高次谐波的依据。
- 已核对 Zhang 论文 DOI 为 `10.1016/j.coelec.2018.04.016`；
  `10.1016/j.coelec.2017.12.001` 对应 Vitamin B12 综述，不得误引。
- 本阶段只更新项目总览和唯一执行路线，未修改代码、参数角色、科学阈值
  或既有结果。

## 52. G1有效电极标度参数第一切片（2026-08-02）

- 依据网络与方程审计，将总电流M0中的精确尺度组合登记为
  `CdlA=A*Cdl`和`GammaA=A*gamma`；本阶段不修改冻结A6-v2参数空间。
- 新增`electrode_scale.py`：旧`A/Cdl/gamma`、canonical
  `CdlA/GammaA`和显式冗余输入经过同一入口校验；电流密度口径显式拒绝，
  不做静默单位转换。
- 回归测试发现旧流程会在首次初始化后修改`gamma`并再次初始化。为区分派生
  缓存和用户显式冲突，参数字典记录内部权威来源；旧来源重新计算组合量，
  canonical来源重新展开旧字段，首次显式双表示不一致仍失败。
- Python物理核心内部用`CdlA/GammaA`计算`invRC`和`gammaF_Cdl`，同时保留
  旧字段供C++桥和冻结流程兼容。canonical-only与旧参数的状态轨迹、外加电位、
  总电流、DC及H1-H3通过`1e-12`绝对等价门。
- 新增`m0-total-current-effective-v1.json`，状态为`development_only`，记录
  电流来源、单位、参数角色、旧参数映射、未解决预处理和禁止结论；旧A6角色表
  保持不变。
- 验证：组合API与物理目标测试53项通过；schema测试4项通过；全量Python
  回归521项通过。未运行远程计算，未修改求解器、优化器、科学阈值或正式结果。
- G1尚未完成：下一切片诊断五覆盖度中的守恒零方向和RHS隐藏归一化，再决定
  四独立状态或五状态显式守恒路线。

## 53. G1覆盖度守恒坐标诊断（2026-08-02）

- 新增开发态四坐标API：保留`theta_ox/theta_OH/theta_O/theta_OOH`，用
  `theta_star=1-sum(independent)`重建第五覆盖度；超界、非有限或离开守恒
  流形时失败，不截断也不归一化。
- `elementary_rates` 新增显式`strict`策略，可拒绝旧路径会静默归一化的
  离流形状态；默认仍为`legacy_normalize`，因此未改正式求解行为。
- 内部物理初值的四/五状态短轨迹均求解成功；最大覆盖度差
  `2.5364e-9`、表面电位差`5.0882e-10 V`、总电流差`5.0882e-11 A`。
- 压力测试发现：从`theta_star=1`的正式边界初值开始时，LSODA内部试探步
  出现约`-9.26e-8`临时覆盖度，严格四坐标按设计拒绝。未用截断或放宽阈值
  掩盖该问题，故本阶段不切换正式求解路径。
- 目标测试50项通过；全量Python回归531项通过。未运行远程计算，未修改
  C++桥、求解器、优化器、Gate阈值或正式结果。
- 下一切片只比较边界积分策略：优先评估“四坐标严格守恒+输出点边界验收”；
  正值变换需证明不改动力学和边界初值，否则不采用。

## 54. G1边界积分分层验收（2026-08-02）

- 新增无截断的`reconstruct_conserved_coverages()`：只接受四个有限内部坐标，
  精确重建`theta_star`，使每个LSODA试探点总和为1。
- 新增`validate_reduced_trajectory()`：只对接受的输出点执行原`1e-8`边界与守恒门；
  内部试探和输出验收不再混为一个函数。
- 从`theta_star=1`、其他覆盖度为0的边界初值出发，四/五状态LSODA均成功；
  四状态输出最小覆盖度为0，总和最大误差`2.22e-16`。
- 四/五状态最大覆盖度差`2.30e-13`、表面电位差`9.29e-10 V`、总电流差
  `9.29e-11 A`，均通过预先冻结的`1e-7`门。
- 目标测试52项、全量Python测试533项通过。未修改正式五状态求解入口、C++桥、
  优化器、Gate阈值或正式结果。
- 下一步进行更长FTacV协议与参数扰动下的四/五状态输出和灵敏度方向对照；
  通过前仍不切换正式路径。

## 55. 无量纲多锚点活跃方向核心（2026-08-02）

- `identifiability.py`新增对角标准差/完整协方差白化、多锚点权重归一化、
  白化敏感性Gramian和降序特征方向；特征向量符号确定性固定，便于跨运行对照。
- 结果类不含`effective_dimension`；禁止用累计解释方差或特征值断层自动宣布有效维数。
- 现有importance报告可作为多锚点输入，但必须显式提供每列到`[0,1]`无量纲
  坐标的尺度；尺度缺失、非正、非有限或特征/参数契约漂移均失败。
- 开发schema已为有历史来源的动力学/热力学参数登记旧开发边界及来源；
  `CdlA/GammaA`的总量边界缺乏校准/先验，显式记为`bounds=null`/`unresolved`。
- 旧hybrid敏感性矩阵烟测为`9097×13`且有限。未归一化时第一方向几乎完全由
  `Cdl`控制；映射到无量纲坐标后改为`Ru`主导。该差异证明旧列的单位混用
  会污染方向；烟测没有可靠噪声协方差且仍含精确冗余参数，不作正式物理结论。
- 相关目标测试20项通过；全量Python回归544项通过。未启动真实反演，未改优化器、
  Gate阈值或正式结果。
- 下一步：生成不含精确尺度冗余的合成多锚点敏感性，冻结代理噪声尺度并分离
  训练/选维/留出锚点；此后才有资格比较DIRECT/多起点最小二乘、TuRBO和CMA-ES。

## 56. 量化噪声白化与有效维数开发门（2026-08-02）

- 冻结7个无量纲候选参数、scrambled Sobol seed 17和`3 train / 2 selection /
  1 holdout`；复用v2的84次LSODA敏感性正演，原始报告SHA-256为
  `5d547b1329b05ed2af2a4398182730ef9703b80e932dfe3292ffd720c4c32c94`。
- v6先去除`onset/Tafel`、重复raw DC和DC幅值，仅保留DC shape、complex
  H1-H3及lock-in H1-H3；该版仍使用块平衡代理，不能选维。
- v7首次传播量化噪声时失败：96个lock-in窗外点由无效掩码写成固定0，方差
  和所有锚点敏感性均严格为0。失败证据保留在
  `results/smoke/effective_dimension/dev-20260802-seed17-v7/failure.json`；未用
  数值下限制造无限权重。
- v8按采集/lock-in有效掩码冻结可观测行，排除96个结构无效点，保留134个
  特征。使用现有量化分辨率下限`0.001495726085983469`，以同标准差均匀误差
  在每个锚点传播；只估对角稳定性尺度，明确不等同重复实验协方差。
- selection-only门采用丢弃子空间的最坏白化算子范数`<=1`；12、24、48个
  固定seed均要求完整7维。48-seed v9中r6仍为`712.16`，远高于1，故当前
  不存在可信线性降维资格。holdout的r6最坏偏差为`0.244σ`，只作验证，禁止
  反向覆盖selection结果。
- 最终开发证据：
  `results/smoke/effective_dimension/dev-20260802-seed17-v9/summary.json`；
  稳定性明细SHA-256为
  `f3a52ba4db5be3c65e0b11d0d33c8bd102a365c8946025065a4397b08477586d`。
- 相关测试38项通过；全量Python回归`579 passed in 148.58s`。未启动远程
  正式计算，未切换求解器或优化器，未修改A6-v2阈值。
- 决策：G3当前为“全空间保留”，因此不进入低维DIRECT/CMA-ES/TuRBO基准。
  后续优先检查selection方向跨锚点弯曲、固定输入传播和新增协议能否旋转敏感
  方向；没有新信息前，换优化器不能解决参数补偿。

## 57. 扩展锚点与局部子空间弯曲诊断（2026-08-02）

- seed17最小集的主角诊断显示：training前2维内部稳定，但selection前2维
  最大主角接近`89.47°`；局部有效秩从2到6变化。该结果提示全局线性方向
  失效，而非所有区域都需要同一组7个独立方向。
- 按预注册扩展设计运行scrambled Sobol seed 23：12 training、4 selection、
  2 holdout；其余参数、特征、量化噪声、48 seeds和LSODA配置不变。
- 18个锚点报告全部成功，共270次敏感性正演，0次ODE失败。输出：
  `results/smoke/effective_dimension/dev-partitioned-seed23-v1/summary.json`；
  原报告SHA-256为
  `14c4f3e070665c4ad3c1c4ad91983549547a07eb8bf3fe5560ada0fb0f0176eb`。
- training局部有效秩分布为`2,3,4,5,6`，多数锚点为4–6；前1–6维相对全局
  基的最坏主角约`54.67°–86.50°`。selection局部秩为3–4，主角同样最高
  `88.34°`。这不支持一个跨参数域固定的低维线性坐标。
- 全局selection门继续要求7维；r6最坏白化丢弃算子范数为`52063.81`。
  两个holdout在r6仍有`20.76σ`最坏偏差，故扩展集同时否决“由holdout偶然
  支持r6”的解释。
- 物理诊断（小样本，待验证）：低秩点多接近仅有电容背景的电流平台；反应
  电流增强时更多动力学/热力学方向被激活。training中局部秩与`log10`峰电流
  的相关约`0.71`，与`G_OH`约`-0.58`，只能作为分区假设，不能当参数规律。
- 决策：终止“单一全局active subspace降维”作为当前默认路线。分区局部
  子空间仅保留为候选，因为尚无仅用training冻结且由selection通过的分区规则。
  后续在完整7维无量纲空间建立固定预算Sobol多盆地+局部精修基线；它必须以
  合成恢复而非最低loss竞争TPE，且不改变A1/A3/A6结论。

## 58. 完整7维固定预算优化器最小恢复（2026-08-02）

- 新增两个开发态、truth-agnostic的256调用适配器：
  `sobol_multibasin_pattern`（64 Sobol + 4盆地坐标精修）和
  `sobol_multibasin_hybrid`（64 Sobol + 2 pattern + 2 Powell）。另保留唯一
  后续诊断`192 TPE + 64 Powell`；所有输入均限制在无量纲`[0,1]^7`并保存
  逐调用phase、坐标、loss和错误。
- 解析5-seed压力测试中，多盆地候选在sphere/Rastrigin上优于TPE，但在旋转
  各向异性二次谷底上更差，证明坐标pattern不能因简单基准好看就成为默认。
- LSODA最小恢复冻结`mixed_a`、零噪声、seed 23、hybrid DC/H1-H3、每算法
  256调用。原始对照证据：
  `results/smoke/fullspace_optimizer/dev-mixed-a-seed23-v1/summary.json`
  （SHA-256 `7e2729407aa6a6df2545b71f1e465624a63b5c4a476f2ac33ece47534c304aa7`）。
- TPE：loss `2.8505`，最大/中位无量纲误差`0.4266/0.1672`，1次ODE失败；
  纯多盆地与混合多盆地均停在loss `8.0090`、最大误差`0.6000`并命中边界，
  未进入TPE更好盆地，按预注册门淘汰。
- 唯一追加的TPE+Powell同预算结果：loss降至`0.1481`，但最大误差仍为
  `0.4266`，中位误差反而变为`0.1782`；证据：
  `results/smoke/fullspace_optimizer/dev-mixed-a-seed23-v2-tpe-powell/summary.json`
  （SHA-256 `fbb8dd035a873c1ebdc0ecc7e3d03aca22ee42b63890980cdb77c645ab398512`）。
- 科学结论：本轮没有算法获得默认资格，也没有证明7参数可恢复。局部精修可
  显著降低loss却不改善参数恢复，说明当前目标存在补偿谷或参数信息不足；
  不能再以更低loss或追加预算推进算法名单。
- 下一步仅做同一`mixed_a`真值点的噪声白化局部秩和objective profile；若
  局部秩不足或profile不闭合，回到参数组合/固定输入/新协议，而非换优化器。

## 59. `mixed_a`真值点局部秩与条件切片（2026-08-02）

- 使用与七参数恢复相同的`mixed_a`、LSODA 256点、hybrid DC/H1-H3、
  134个结构可观测特征、量化噪声下限和48个固定seed。
- 局部白化奇异值为`63394.9, 22380.5, 14056.7, 929.35, 147.60,
  2.647, 0.1245`，一标准差局部有效秩为6。第7方向的`k0_4`载荷为
  `0.99999`，其余载荷均小于`0.004`。
- 逐参数条件objective切片固定其他参数为真值；`k0_4`在真值±0.05/0.10
  无量纲坐标处loss均为0。`k0_2/k0_3/scaling`较弱但非零；`k0_1/G_OH/G_O`
  对局部偏移响应较强。
- 证据：`results/smoke/truth_identifiability/dev-mixed-a-v1/summary.json`
  （SHA-256 `a606b680d18ec32089c50a7b242db1222ac21b306c1e36dd21a9b4adaacb14bb`）。
- 结论：当前协议下七个单参数点恢复资格失败；这与优化器降低loss却不能改善
  最大误差一致。条件切片不是profile likelihood，不能给置信区间。
- 下一步只验证将`k0_4`固定为模型既有默认值`5000 s^-1`是否与目标等价；
  禁止固定为合成真值。等价门通过后才允许六参数同预算恢复；失败则不减参。

## 60. `k0_4`固定输入收敛门与六参数恢复（2026-08-02）

- 首次直接在`rtol=1e-6`检查默认`k0_4=5000 s^-1`时，truth objective为
  `2.57e-9`，但原始电流最大差`2.76e-7 A`超过预注册`1e-8 A`门，优化按设计
  未启动。证据：`results/smoke/fullspace_optimizer/dev-mixed-a-six-param-seed23-v1/summary.json`
  （SHA-256 `9a196cfab36f717845d8b3d2bab609b8e76843bc1faa085f7433d03d7e8a4e65`）。
- 固定输入全范围传播一度把被真值覆盖后的字典误标为“模型默认值”；v2保留为
  失败证据。修正为独立默认快照后，默认值正确坐标为`0.74433`，真值坐标为
  `0.60000`。v3证据SHA-256为
  `b428b533a39046689da1cf2b3f65ae258aec139d02c2777c1b7a1b5d3a262da3`。
- LSODA收敛检查显示：`rtol=1e-6`下真值/默认电流差`5.22e-7 A`，而各自相对
  `rtol=1e-8`参考的数值漂移为`2.77e-7/2.45e-7 A`；收紧到`1e-8`后两者差
  收敛为`5.47e-9 A`。因此原阈值不变，等价验收使用`rtol=1e-8`，优化仍用
  冻结`rtol=1e-6`。证据：
  `results/smoke/truth_identifiability/dev-mixed-a-k04-solver-convergence-v2/summary.json`
  （SHA-256 `9db6d1e2f24987972711f166072c1ff6556da8766fdd3399a1fb7a971dc30d00`）。
- 六参数门随后通过：电流差`5.43e-9 A`，truth objective`4.39e-13`。同一
  256调用预算下，TPE最大/中位误差为`0.4076/0.2564`；TPE+Powell为
  `0.4041/0.2063`。两者均未达到恢复资格，且各有1次ODE失败。
- 成功运行证据：
  `results/smoke/fullspace_optimizer/dev-mixed-a-six-param-seed23-v2/summary.json`
  （SHA-256 `cb3677cfa22e5fa41ad66abf179a7b8341c9c30bb1e2372a1fb0fc164b5948f7`）。
- 决策：固定`k0_4`不足以消除剩余补偿谷；停止追加优化器和预算。下一步做
  真正的profile likelihood与固定输入传播，不把最低loss解释为参数可恢复。

## 61. 六参数补参数重优化 profile（2026-08-02）

- 新增开发态补参数重优化 runner：每个被profile参数固定在真值±0.05/0.10
  无量纲坐标，其余5个自由参数从合成真值起步作有界Powell。该初始化对可辨识
  判断是乐观诊断，不是可用于真实反演的truth初始化。
- CN用每点192调用寻找具体补偿候选；不要求Powell声明收敛。随后将每个候选
  原坐标不变地送入LSODA单次确认。因这只证明“存在低loss补偿解”，不需要
  证明profile全局最小；真正最小只可能更低。
- LSODA确认结果：`G_OH`在`z=0.25/0.30/0.40`的loss为
  `0.00723/0.07294/0.02240`；`G_O`在`0.55/0.60/0.70`为
  `0.00727/0.00568/0.00585`；`scaling_OOH_OH`在真值±0.10内均为
  `0.00614–0.02949`。三项热力学参数均存在宽`Δloss<1`补偿区。
- `k0_2`和`k0_3`在真值±0.10内的LSODA确认loss分别不超过`0.07742`和
  `0.02683`，同样不支持单参数点估计。`k0_1`呈非对称：真值以上+0.05/+0.10
  可补偿到`0.02734/0.04285`，以下-0.05/-0.10仍为`3.99/8.04`；这只支持
  单侧约束假设，尚不支持闭合区间或点值。
- 六个LSODA确认summary SHA-256依次为：`k0_1` `587d0b79...`、`k0_2`
  `2d29a2c4...`、`k0_3` `bd2fbb86...`、`G_OH` `59551e84...`、`G_O`
  `4b696b45...`、`scaling` `83369e9f...`；完整哈希保存在各summary及Git状态。
- 结论：当前单协议、DC/H1-H3目标下，六参数单点恢复整体失败。后续算法对象
  应改为可恢复组合或单侧界，并由新频率/振幅/扫速协议旋转敏感方向；继续在
  原协议增加全局优化预算没有科学收益。
- 本轮新增与既有Python测试全量回归`605 passed in 150.31s`，`git diff --check`
  通过；未提交、未推送、未启动远程正式计算。

## 62. 低-loss补偿流形与候选组合（2026-08-02）

- 汇总六个profile中经LSODA确认且`loss<=1`的非真值候选；用绝对偏移`<=0.05`
  的11个候选拟合补偿位移SVD，用偏移`>0.05`的9个候选只作selection验证。
- 六个训练奇异值为`0.58294, 0.35575, 0.14249, 0.12051, 0.02465,
  0.001249`。最小运动方向的主要载荷为
  `0.858*z(G_OH)-0.514*z(log10(k0_1))`；其训练最大运动`7.27e-4`，selection
  最大运动`3.90e-3`，明显小于其余五个方向。
- 按开发schema边界换回物理坐标并去掉无关常数，该方向等价于候选组合
  `G_OH - 0.1132*log10(k0_1)`（eV）。在`a=0.5, T=298.15 K`下，冻结M0
  正向BV尺度`RT ln(10)/((1-a)F)=0.1183 eV/dec`，与候选系数相差约`4.3%`。
  由于`a=0.5`时旧写法`RT ln(10)/(aF)`数值相同，本阶段尚未区分BV分支。
  这是物理一致性线索，不是已证明机理关系；系数仍依赖当前schema边界、
  单真值和单协议。
- 证据：`results/smoke/truth_identifiability/dev-mixed-a-compensation-geometry-v1/summary.json`
  （SHA-256 `5e49dc08103e86688f2a4251dc5318eed9945ae3db8be93036a67788abe59617`）。
- 决策：将该组合升级为首个组合profile候选；必须在组合坐标上重新优化正交
  补参数，并由独立锚点/协议验证。未通过前不报告`G_OH`或`k0_1`点值，也不
  把经验系数写成反应定律。

## 63. 组合profile、跨真值门与局部性结论（2026-08-02）

- `mixed_a`组合经固定256调用TPE+Powell压力测试，偏移
  `-0.10/-0.05/+0.05/+0.10`的LSODA loss为`1.80/3.24/14.58/8.25`，
  未发现`loss<1`旁路，获得开发态局部组合资格。
- 固定输入跨真值收敛门显示：`center`固定默认`k0_4`的`rtol=1e-8`电流差
  `7.09e-9 A`通过；`mixed_b`为`5.24e-7 A`失败。因此`k0_4`不能全局固定。
- 同一组合迁移到`center`后，LSODA确认偏移`-0.10/-0.05/+0.05`仍可补偿
  到loss `0.345/0.064/0.742`，跨真值门失败。
- `center`自身低-loss位移SVD的最小训练奇异值为`0.0198`，最小方向主要由
  `G_O/k0_3/scaling/G_OH`组成，selection最大运动`0.149`；不同于`mixed_a`
  的`G_OH/k0_1`方向且不具留出稳定性。
- 结论：当前不存在跨参数区统一线性组合；有效坐标和是否可固定`k0_4`均为
  局部性质。禁止把单锚点物理一致性解释升级为全局降维或材料定律。

## 64. V4.1推荐协议联合六参数恢复（2026-08-02）

- 联合目标使用基线`5 Hz/0.16 V`、`5 Hz/0.08 V`和`10 Hz/0.16 V`匹配
  扫描；10 Hz条件点数加倍以保持扫描速率。CN执行256调用TPE+Powell搜索，
  最优候选由三个LSODA目标原坐标确认。
- `mixed_a`的LSODA联合loss为`0.1710`，最大/中位无量纲误差
  `0.2999/0.1150`；相对单协议最大误差约`0.404`有改善，但未过恢复门。
- `center`的LSODA联合loss为`1.7693`，最大/中位误差`0.3726/0.2131`；
  同一协议组合不能跨真值稳定恢复六参数。
- LSODA确认SHA-256：`mixed_a`
  `494d74212a8f3591802c64b8e7c839592ae7aca8d8910d927a65693d739afb58`；
  `center` `455f37e1a6a434a4e0dddebe94353dfd9c673dd361036b19c87c4d79c86985aa`。
- 决策：V4.1推荐继续作为未来采集优先级，但两条新增协议不足以授权六参数
  点估计。休假期间停止追加优化器预算，转向分区条件结论和实验验收接口。

## 65. `mixed_a`局部组合的跨协议与转移系数压力测试（2026-08-02）

- 在固定`mixed_a`下分别用baseline `5 Hz/0.16 V`、lowamp `5 Hz/0.08 V`
  和highfreq matched `10 Hz/0.16 V`独立重做六参数profile、LSODA确认及
  补偿几何。三组最弱方向始终由`G_OH/k0_1`主导；相对baseline的方向夹角为
  `1.25°/6.82°`，物理系数为`0.11324/0.11689/0.10917 eV/dec`，selection
  最大运动为`0.00390/0.00584/0.01055`。因此该组合获得跨这三种协议的
  局部稳定证据，但`center`反例仍禁止全局升级。
- 改变转移系数前先复核默认`k0_4`固定输入。`a=0.4`的`rtol=1e-8`电流差
  `7.00e-9 A`通过；`a=0.6`为`1.78e-8 A`失败，证明固定输入资格也依赖
  物理区域。后续机制隔离实验统一使用合成真值`k0_4`，只作乐观诊断。
- 首轮runner把`a/T`只传给候选、未传给合成目标，导致`a!=0.5`的真值CN
  loss非零；这些v1输出保留但禁用。修复为目标与候选共享`fixed_params`后，
  三组18个CN profile的真值loss均为0，LSODA确认无ODE/特征失败。
- 方程审计确认第一步正向BV项为`exp[(1-a)F*eta/(RT)]`，因此对应预测是
  `RT ln(10)/((1-a)F)`；旧式`RT ln(10)/(aF)`只在`a=0.5`时偶然相同。
  `a=0.4/0.5/0.6`经验系数相对修正理论偏差为`6.79%/4.29%/1.88%`，但该
  修正发生在查看结果后，未作为独立验证。
- 预注册holdout `a=0.35/0.65`沿用载荷平方和`>=0.95`、selection运动
  `<=0.02`和理论偏差`<=10%`门。`a=0.65`偏差`5.49%`通过；`a=0.35`
  经验/理论为`0.07483/0.09101 eV/dec`，偏差`17.79%`，整体门失败。
- 结论：`G_OH-log10(k0_1)`只保留为`mixed_a`附近、有限协议范围内的局部
  经验补偿坐标；部分转移系数下与正向BV尺度一致，但未获得跨`a`机制标度
  资格。按预注册退出条件取消温度扰动，不再围绕该公式追加优化预算。
- 关键holdout几何SHA-256：`a=0.35`
  `f7489545502e668ecffba362e5730b139dcda117df802203c7620cd0d6d94f4e`；
  `a=0.65` `a038afeb30fa8bd39da4f7ad2d1606d7f3d49aff829fbe4fe68449775c67eafc`。

## 66. 局部组合机器可读登记（2026-08-02）

- 新增`run_local_combination_registry.py`，从已冻结几何summary独立重算最弱
  方向、schema物理系数、方向夹角、局部几何门和修正BV holdout门；不运行
  新ODE、不插值参数区域、不自动选择分区。
- v1登记固定`claim_level=LOCAL_ONLY`。重算结果：lowamp/highfreq相对baseline
  夹角`1.25°/6.82°`且局部几何门通过；`center`夹角`82.47°`且局部几何门
  失败；`a=0.35/0.65`理论相对误差`17.79%/5.49%`，机制门整体失败；
  `temperature_perturbation_allowed=false`。
- 登记显式禁止全局有效坐标、全局降维、`G_OH/k0_1`单参数点估计、已验证BV
  定律、置信区间和真实数据可辨识声明。6个来源及parameter schema均绑定
  SHA-256，便于后续Agent追加新锚点而不重解释旧证据。
- 证据：`results/smoke/scaling_validation/dev-local-combination-registry-v1/summary.json`
  （SHA-256 `ee3d09dbfe8147e9cc332d442a034ea90229e6af23b9da1379f17b2c9d9b593d`）。

## 67. 恢复实验接入契约（2026-08-02）

- 新建Gate A1前的独立接入层，不修改旧
  `config/data-contracts/gate-a1-datasets.json`。冻结三个角色：baseline为
  `training`、lowamp为`selection`、highfreq为`holdout`。
- 纯标准库validator只输出`WAITING_FOR_DATA/FAIL_STRUCTURE/FAIL_METADATA/
  READY_FOR_A1_AUDIT`；检查角色、身份、项目相对路径、文件大小与SHA-256、
  方法文件一一关联、批次元数据、预处理布尔声明和独立输入资格。
- 只有`READY_FOR_A1_AUDIT`才写`UNVALIDATED_SEED`；该seed明确要求新批次A1
  validator，不复用旧A1阈值，也不授权A6-v2、真实反演或参数点估计。
- 空模板固定验收为`WAITING_FOR_DATA`，三个条件均缺失，结构/元数据错误为空，
  且不存在`a1_seed.json`。证据位于
  `results/smoke/experiment_intake/template-v1/`。
- 模板SHA-256为
  `1a891c8283498b09eaa57f698e66e8e7e3ded9a0acb815b063889ab4f3805521`；
  summary为`3ea383e4f1975a2bfb1215d08a6ebab75f005dda432a537b542cc8f8d0ce00de`，
  acceptance为`cf731f8ef31b1459adb91b51096fec8d6e12d3849d4afa053809c9ee78dcc748`。
- 接入与旧A1目标回归`45 passed in 3.31s`；全量Python回归
  `642 passed in 146.80s`。未运行ODE、未启动反演、未修改模型/求解器/
  优化器/Web，未提交、未推送。

## 68. pre-experiment A6-v2 S1 正式验收（2026-08-02）

- 状态：**S1 完成并独立验收**。结构/完整性 PASS，科学门 FAIL。
- 执行：Legion 冻结 worktree，commit `21284b53`，LSODA，8 workers，
  81 jobs × 100 trials × 3 真值 × 3 seed，N0=0.0 无噪声。
  起止 2026-08-01T14:07:40Z → 2026-08-02T03:01:38Z，约 12.9 h。
  0 ODE fail，n_tafel_fail=1804（不阻塞 recovery）。
- 独立 validator（`validate_pre_experiment_recovery.py`）重建科学门：
  ```json
  {"gate": "PASS", "stage": "S1",
   "stage_status": "DESIGN_INSUFFICIENT_NOISELESS",
   "scientific_gate_passed": false, "eligible_parameter_pairs": []}
  ```
- 结论：**V4.1 推荐的三协议组合（5Hz/0.16V、5Hz/0.08V、10Hz/0.16V）
  在无噪声合成条件下无法恢复 G_OH-G_O、k0_2-k0_3、k0_3-G_O 中任何参数对**。
  问题不是噪声或预算，而是三协议信息量不足以解开这些补偿。
- 按 plan 冻结规则：S1 三组参数对 P2 全失败 → **不创建 S2**。
- 证据：Mac 归档
  `~/OER-FTAcV-archive/results/21284b5/pre_experiment_a6_v2_s1_lsoda/20260801_140736/`；
  10 文件，spec SHA-256 见 summary。
- 边界：本结论只否定当前三协议组合在无噪声合成下的恢复能力；
  不改变真实数据 Gate A6 `FAIL_RECOVERY`，不授权任何真实数据反演或参数点估计。
- 下一步：按 roadmap 决策表——原始参数仍不具资格，候选为固定参数、
  报告组合量或仅作诊断；或回到 V4 扩展条件矩阵（需恢复实验数据）。
