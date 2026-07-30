# V4.1 正式实验信息设计验收

- Gate：`PASS`
- 计算提交：`fbbba8df521292776e080606a0cc27963466cfb6`
- TaskSpec hash：`sha256:da9e7e59995c77feb59a94965361d4411b9b54d306a5929bf614b6bf1a8de80b`
- 正式环境：Legion WSL，8 workers，LSODA/BDF；每个 worker 的
  OMP/OpenBLAS/MKL/NumExpr 线程均为 1。
- 运行状态：`STATUS=SUCCESS`，退出码 0。
- 完整性：792 个主任务、80 个半步长任务、72 个敏感矩阵；872/872
  正演成功，所有正式产物和 manifest 哈希通过冻结 validator。
- 独立复算：在相同提交、平台、数值库和线程环境下，对两项候选协议执行
  8 条独立 LSODA baseline 复算，8/8 通过冻结一致性门。
- 条件模型推荐：
  1. `candidate_5hz_amp_008`
  2. `candidate_10hz_matched_scan`

## 结论边界

该 PASS 只证明：在冻结 M0、8 个 V3 条件参数点和当前局部敏感性指标下，
上述两项采集协议形成稳健的两阶段优先级。它不证明真实参数可恢复，不替代
独立 `Ru/Cdl/gamma`、面积、负载量和预处理记录，也不把 A1
`FAIL_METADATA`、A3 `FAIL` 或 A6 `FAIL_RECOVERY` 改为 PASS。

Mac 跨平台重建出现约 `1e-14` 的派生矩阵末位差异；Legion 未恢复正式
单线程变量时，一条 baseline 最大相对漂移约 `4.55e-5`。两者均未用于
放宽科学阈值；最终结论来自冻结 Legion 环境的 8/8 复算。
