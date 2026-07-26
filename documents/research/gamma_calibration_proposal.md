# Gamma 独立标定方案

**背景**：跨数据稳定性诊断显示 `gamma`（Γ_total，活性位点总浓度）的 CV=0.89，与 A、Cdl 存在强补偿，不可单独解释。当前反演中 gamma 被自由优化，导致其值在不同数据集间剧烈波动。需通过独立实验手段给出约束范围。

---

## 1. 三种标定路径

### 路径 A：负载量 → 上限估算

```
Γ_max = m_deposited / (M_Co3O4 × A_geo)
```

- 称量沉积前后电极质量差 → m_deposited
- M_Co3O4 = 240.8 g/mol
- 假定所有 Co 原子都是表面位点 → 给出 gamma 的**物理上限**
- 实际可用作"反演值不得超过此上限"的硬边界

### 路径 B：电容/ECSA → 有效面积估算

```
Γ_eff = Cdl_measured / C_specific × (surface_atom_density / N_A)
```

- Cdl 由 EIS 或 FTacV 数据直接测得（当前 ~28 µF/cm²）
- C_specific：光滑 Co3O4(111) 约 80 µF/cm²（Davis 2023），粗糙 CoOOH 约 40-60 µF/cm²（Moysiadou 2020）
- 粗糙度因子 = Cdl / C_specific → 有效面积 = A_geo × RF
- 表面 Co 密度约 6.1×10¹⁴ atoms/cm²（Moysiadou 2020，引用 Esswein）
- Γ_eff = 表面 Co 密度 × RF / N_A

### 路径 C：CV 预氧化峰积分 → 可逆 Co 位点（最可靠）

```
Γ_rev = Q_ox / (F × A_geo)
```

- 对 Co³⁺/⁴⁺ 氧化峰做背景扣除
- 积分峰面积得 Q_ox（单位 C 或 µC）
- Γ_rev 是"参与可逆氧化还原的 Co 位点浓度"——最接近 gamma 的物理含义
- 需要明确的预氧化峰数据（CV 数据已存在，可检查峰是否可分辨）

---

## 2. 推荐顺序

1. **先用路径 C**：检查 CV 数据中 Co³⁺/⁴⁺ 峰的清晰程度，积分得到 Γ_rev 的估计值
2. **再用路径 B**：用已有 Cdl 数据估算粗糙度因子，验证 Γ_rev 的量级是否合理
3. **路径 A 作为备选**：如果没有称量数据，可以用文献中类似制备条件的负载量做参考

---

## 3. 对反演的直接影响

一旦 gamma 被约束到一个合理范围（如 [5×10⁻¹⁰, 5×10⁻⁹] mol/cm²），反演中将 gamma 设为 fixed_params，TPE 不再自由搜索 gamma。预期效果：

- 断开 gamma/A/Cdl 补偿链
- k0_i 的反演值跨数据稳定性提升
- DC amplitude 的拟合不再由 gamma 提供虚假自由度

---

## 4. 当前已有数据

| 数据 | 可用信息 |
|------|---------|
| `cv-ftacv2.txt`、`cv2-ftacv8.txt`、`cv4-ftacv3.txt` | CV 曲线，E=0-0.9V，可检查预氧化峰 |
| FTacV 数据的 Cdl 标定值 | ~17-35 µF/cm²（跨 4 组数据的平均值 28 µF/cm²）|
| 文献 | 表面 Co 密度 6.1×10¹⁴/cm²，C_specific ~80 µF/cm² |

## 5. 待执行

- [ ] 检查 CV 数据中 Co 氧化峰的清晰度和峰面积
- [ ] 选择一组 FTacV 数据作为参考（建议 ftacv2-ref-5hz，谐波质量最好）
- [ ] 将 gamma 改为固定值重新反演，观察 k0_i 稳定性的改善
