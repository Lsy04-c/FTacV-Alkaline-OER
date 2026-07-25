# Co3O4 Alkaline OER Mechanism Papers

用途：为碱性 OER AEM/FTacV 代码提供 Co3O4 / CoOx / CoOOH 机理背景、活性相判断和参数范围参考。

## 已下载文献

| 优先级 | 文件 | 主要用途 |
|---|---|---|
| 1 | `moysiadou_2020_cobalt_oxyhydroxide_oer_mechanism_jacs.pdf` | CoOOH/OER 机理核心文献；用于理解 AEM 步骤、CoOOH 活性位、反应中间体和速率控制。 |
| 1 | `moysiadou_2020_cobalt_oxyhydroxide_oer_mechanism_si.pdf` | 上文支撑信息；优先看实验条件、参数拟合逻辑、DFT/动力学细节。 |
| 1 | `davis_2023_co3o4_111_alkaline_oer_natcomm.pdf` | Co3O4(111) 碱性 OER；可用于确定 Co3O4 在 KOH 中的红氧峰、OER 条件和 oxyhydroxide 活性层。 |
| 2 | `rettie_2022_reversible_skin_layer_co3o4_acscatal.pdf` | Co3O4 表面可逆 skin layer / 3D reaction zone；支撑“活性相不是裸 Co3O4，而是重构层”。 |
| 2 | `davis_2024_facet_dependence_co3o4_oer_acscatal.pdf` | Co3O4 晶面依赖；用于判断不同表面结构会影响 OER 活性和参数可迁移性。 |

## 对当前代码的直接启发

- `E0_pre` 应来自本体系红氧峰/预氧化区，不应固定引用中性体系数值。
- `gamma` 应解释为有效参与 FTacV 响应的活性位点，不等于全部 Co 或全部负载量。
- Co3O4 碱性 OER 更合理的活性相写法是 CoOx(OH)y / CoOOH-like reconstructed layer。
- AEM 可以作为第一版机理框架，但需警惕晶面、重构层厚度、缺陷和电荷传输导致的参数耦合。
- 这些文献适合作为“背景和边界条件”，不能直接替代我们自己的 FTacV 数据标定。

## 下载失败记录

`failed_downloads/` 中是未成功获取的网页或空文件，不作为文献使用。
