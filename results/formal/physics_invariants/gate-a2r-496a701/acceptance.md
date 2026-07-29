# Gate A2-R 守恒积分正式验收

## 结论

- Gate：`PASS`
- 是否允许继续下一底层架构 Gate：是
- 是否允许真实数据正式反演：否，Gate A1 仍为 `FAIL_METADATA`
- 执行 commit：`496a701d819b6da16f9963ac60e2d5184dd2a864`
- 配置：12 个冻结案例，32 cycles，128 points/cycle，
  `rtol=1e-6`，覆盖度 `atol=3e-11`，表面电位 `atol=1e-8`

独立 validator 重载六份核心产物，重算为 `PASS`。Gate A2 的
`gate-a2-6486d69` 失败归档保持不变；A2-R 是新提交和新协议下的修复门。

## 守恒与物理门

- 12/12 案例稳态、动态求解和有限值检查通过。
- 逐分量边界投影已删除；实际投影次数为 0。
- 最坏覆盖度最小值：`-5.702157723067235e-09`，位于 `-1e-8` 门内。
- 最坏覆盖度最大值：`1.0000000004269556`，位于 `1+1e-8` 门内。
- 最坏覆盖度和误差：`3.750555421788704e-12`。
- 最坏电流闭合相对误差：`4.985328185743095e-16`。
- 最坏稳态 RHS 无穷范数：`4.82615900368466e-13`。
- 12 个案例热力学和误差均为 0。

## 后端证据

- 11 个常规案例使用 LSODA 完成，没有触发回退。
- `thermo-edge` 的 LSODA 在首个输出点报告
  `Unexpected istate in LSODA`；随后 BDF 从原始稳态初值完整重启，
  返回 4096 点。
- 回退是显式的两条 attempt 记录，没有把 BDF 标记为 LSODA。
- BDF–Radau 独立交叉验证：
  - 覆盖度最大绝对差：`2.418484533472931e-06`；
  - 表面电位最大绝对差：`1.0664489386469356e-05 V`；
  - 电流 NRMSE：`8.928013139874965e-07`；
  - 电流最大缩放误差：`1.8187449072822423e-05`。

四项均通过预注册阈值。

## 行为保持

- 72 点冻结合法状态 RHS 基线最大相对误差：
  `1.6555221185962127e-16`。
- 基线 SHA-256：
  `35741fff1f5bf2e40b5523e9248774a29d49c2ec01722739647d1060eb94105a`。
- M0 回退使用 LSODA；改变禁用的 `E_recon/w_recon` 后，状态和电流最大
  绝对误差均为 0。

## 归档哈希

- `physics_contract.json`：
  `d914de544b56bd0f34ed8ca5b39e3552b179ee42b85daafbd2221a80b1e74ea0`
- `trajectory_metrics.jsonl`：
  `c189b19e3260cd203fd70b3ec9163c9f1addada9ec629ec836687d184138323b`
- `backend_attempts.jsonl`：
  `4107e1a7e04ea16a26bad2b61479bf6d57acaea1141008bddc047cb7fed9080f`
- `implicit_crosscheck.json`：
  `f8ce8eb4ed2b8e6cd43756762a3623d0620a52d69d14f7dafbba71fccc33816a`
- `baseline_comparison.json`：
  `b73b85b36f4e52b5b29d52ead2bbfb477b262f135a4f39767075660c7569d00c`
- `gate_a2r_summary.json`：
  `80d64e02ea2ab39407e55d2972cc6993d751f683f0f51d47ec785b5d2eef3900`

## 允许与禁止的结论

允许：

- 当前五步 M0 在冻结合成案例内满足覆盖度、热力学和电流不变量；
- 状态分量容差与显式 BDF 回退解决了 A2 发现的数值失败；
- 可以继续下一底层架构 Gate。

禁止：

- 把 BDF 回退写成 LSODA 成功；
- 把 12 个合成案例升级为完整参数空间稳定性证明；
- 把 A2-R PASS 写成机理真实性、参数可识别性或实验反演可信；
- 在 Gate A1 元数据缺失时启动真实数据正式反演。
