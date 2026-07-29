# Gate A2 正式物理不变量验收

## 结论

- Gate：`FAIL_NUMERICAL`
- 是否允许进入下一 Gate：否
- 是否允许新增机理或启动真实数据反演：否
- 执行 commit：`6486d6958ef1894301d5d4862cd65832b42a7cb7`
- 配置：12 个冻结案例，LSODA，32 cycles，128 points/cycle，
  `rtol=1e-6`，`atol=1e-8`，`first_step=1e-8`

独立 validator 重载五份归档并重算为 `FAIL_NUMERICAL`。本结论保留原阈值
和原案例，不通过重跑、裁剪覆盖度或删除失败案例改变。

## 通过证据

- 冻结的 72 点合法状态 RHS 基线重算通过，最大相对误差
  `1.6555221185962127e-16`，基线 SHA-256：
  `35741fff1f5bf2e40b5523e9248774a29d49c2ec01722739647d1060eb94105a`。
- M0 回退通过：改变 `E_recon/w_recon` 后状态与电流最大绝对误差均为 0。
- 12/12 案例稳态检查通过，最坏稳态 RHS 无穷范数
  `4.792684126083899e-13`。
- 11 个完成轨迹的电流闭合相对误差均低于
  `5.05e-16`；12 个案例的热力学闭合误差均为 0。

## 失败证据

1. `thermo-edge` 在正式 LSODA 轨迹中出现 repeated convergence failures，
   最终为 `Unexpected istate in LSODA`；稳态本身已通过，因此是瞬态数值
   失败，不能归为基础设施失败。
2. 11 个完成案例的边界投影触发次数均非零，范围为 68–1042；冻结门要求 0。
3. 多个完整轨迹越过覆盖度范围或守恒阈值。最坏覆盖度最小值为
   `-4.4341948834499655e-07`，最坏覆盖度和误差为
   `1.425353375328342e-07`。
4. 失败不是电流分解、M0 回退、热力学闭合或重构漂移造成；直接证据指向
   当前覆盖度边界处理和极端热力学案例下的 LSODA 稳定性。

## 证据完整性

`run_manifest.json` 记录的四份核心产物 SHA-256：

- `physics_contract.json`：
  `67883a827c1cbfdeac57e4aa4d3cfa333b0b39e6776d1df3e58455546a71b064`
- `trajectory_metrics.jsonl`：
  `df7ff9c588429e396fb9d5dd28fc0e10d1810f333b454ac9cae27750aee88cce`
- `baseline_comparison.json`：
  `b73b85b36f4e52b5b29d52ead2bbfb477b262f135a4f39767075660c7569d00c`
- `gate_a2_summary.json`：
  `968ed1662c0db8a1a6ef080d48e95512eceab2ee33dcaff2cdc98e31c76f6435`

## 后续路径

停止 Gate A2 的依赖步骤。下一阶段只允许建立新的、预注册的数值诊断：

1. 分离“化学计量守恒 RHS”和“逐分量边界投影”对覆盖度总和的贡献；
2. 在不改变机理与正式阈值的前提下定位 `thermo-edge` 的刚性来源；
3. 设计守恒的状态参数化或积分策略，并用本归档作为不可覆盖的失败基线；
4. 修复候选必须先通过单元和短轨迹测试，再以新 commit 运行新的 Gate，
   不能覆盖本次正式结果。
