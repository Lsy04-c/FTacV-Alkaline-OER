# Gate A5 特征通道契约正式验收

## 结论

- Gate：`PASS`
- 执行 commit：`13adcb1ffa6f38feaee7b3951b0303489ac131ad`
- runner 与独立 validator：均为 `PASS`
- 是否运行 TPE：否
- 是否允许真实数据正式反演：否，Gate A1 仍为 `FAIL_METADATA`

本门只证明目标函数的活动通道、目标侧权重、锁相掩码和归一化分母
不随候选参数改变。它不证明任一特征模式提高反演精度，也不关闭 Gate A6。

## 结构与契约

- FT2、FT3、FT4、FT8 × legacy、complex-SNR、lock-in-only、hybrid：
  16/16 个 `(dataset_id, feature_mode)` 审计记录完整且唯一。
- 16 个记录产生 10 个唯一结构哈希。legacy 和 lock-in-only 在四个
  数据集上结构相同，因此合法共享哈希；数据集身份未混入结构哈希。
- 所有活动通道的目标权重和损失权重均有限且严格为正。
- 所有非活动通道均记录合法排除原因。
- 所有归一化分母均等于活动损失权重之和。
- 16/16 个缺失值注入均返回固定 `1e9` 特征失败惩罚，且
  `n_feature_fail` 恰好增加 1。

## 真实目标侧结果

- legacy：四个数据集均活动 `DC + H1–H3 envelope`，分母均为 4。
- complex-SNR：
  - FT2、FT3 活动 `DC + H1–H3 amplitude/phase`；
  - FT4、FT8 的 H3 低于冻结 SNR 门，明确记录
    `below_snr_floor`，不进入分母；
  - 四个分母依次为 3.7670403568、2.6609377261、
    2.1676397122、1.7026042060。
- lock-in-only：四个数据集均活动
  `DC + H1–H3 amplitude/phase`，每个锁相块使用 36 个冻结点，
  分母均为 7。
- hybrid：使用 complex-SNR 与 lock-in 活动块并集；FT2/FT3 有
  13 个活动块，FT4/FT8 因 complex H3 低 SNR 有 11 个活动块。

## 独立验证

独立 validator 不导入 runner 或 `oer_aem.inversion`，重新检查：

- 三个核心产物的 SHA-256；
- 16 个数据集/模式键及重复记录；
- 契约规范化 JSON 哈希；
- 活动权重和分母；
- 排除原因；
- 两个有限候选的哈希、活动通道和分母不变性；
- 缺失值注入的惩罚和计数；
- runner summary 与 manifest provenance。

验证器的篡改测试覆盖结构失败、数值失败和契约失败三类退出路径。

## 归档哈希

- `channel_contracts.jsonl`：
  `a72e8699a0aa413e46893f96342590225cfb6284dc149b694f0fb225a9335564`
- `candidate_invariance.jsonl`：
  `4220976a20185efa1c9e45876bc3dedc32ff6d17255ae093e60724065071dc82`
- `gate_a5_summary.json`：
  `9ee2d7547cae480cdd650b532f6cc44342562315e79f5a8542974096fb23123d`

## 允许与禁止的结论

允许：

- 候选参数不能再静默改变活动特征、SNR 权重、锁相有效点或损失分母；
- 候选侧缺失或非有限值按固定特征失败处理；
- 可以继续下一项底层架构工作。

禁止：

- 把 A5 PASS 写成 lock-in 或 hybrid 提高反演精度；
- 跨模式直接比较内部 `total_loss`；
- 把低于 SNR 门的 H3 写成实验中不存在；
- 在 Gate A1 元数据缺失时启动真实数据正式 TPE。
