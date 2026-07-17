"""AEM 热力学约束模块。

由 G_OH / G_O 等物理描述符，通过标度关系生成 *OOH 自由能及各步骤平衡电位 E01-E04。
"""

from typing import Dict, Any


def apply_alkaline_aem(params: Dict[str, Any]) -> Dict[str, Any]:
    """Apply AEM thermodynamic constraints to generate equilibrium potentials.

    输入字段（单位 eV）：
        params['G_OH']           - *OH 吸附自由能
        params['G_O']             - *O 吸附自由能
        params['scaling_OOH_OH']  - *OOH/*OH 标度偏移，默认 3.2

    输出新增字段：
        params['G_OOH']           - *OOH 吸附自由能
        params['DeltaG1..4']      - 各步反应自由能
        params['E01..E04']        - 各步平衡电位（V vs RHE）

    硬约束：DeltaG1 + DeltaG2 + DeltaG3 + DeltaG4 = 4.92 eV

    References:
        Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139-147.
        Bergmann et al. (2015) Nat. Commun. 6, 8625.
    """
    params = dict(params)  # 不修改原字典

    G_total = 4 * 1.23  # 4.92 eV
    G_OH = params['G_OH']
    G_O = params['G_O']

    scaling_OOH_OH = params.get('scaling_OOH_OH', 3.2)
    G_OOH = G_OH + scaling_OOH_OH

    dG1 = G_OH
    dG2 = G_O - G_OH
    dG3 = G_OOH - G_O
    dG4 = G_total - G_OOH

    params['E01'] = dG1
    params['E02'] = dG2
    params['E03'] = dG3
    params['E04'] = dG4

    params['G_OOH'] = G_OOH
    params['DeltaG1'] = dG1
    params['DeltaG2'] = dG2
    params['DeltaG3'] = dG3
    params['DeltaG4'] = dG4

    sum_check = dG1 + dG2 + dG3 + dG4
    if abs(sum_check - G_total) > 1e-10:
        import warnings
        warnings.warn(
            f'DeltaG sum = {sum_check:.6f} eV (expected {G_total:.6f} eV)',
            stacklevel=2,
        )

    return params
