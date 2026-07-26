"""参数初始化与默认值（对应 MATLAB initialize_oer_parameters.m）。

为 Co₃O₄ 碱性 OER AEM 模型提供合理的默认参数集合。
"""

import numpy as np

from .physics import initialize_system, OERPhysics
from .objective import get_optim_config


def initialize_oer_parameters() -> dict:
    """初始化碱性 OER AEM 模型的全部参数，返回完整 params 字典。

    Returns
    -------
    params : dict
    """
    params = {}

    # ==================== 数据路径 ====================
    params['data_path'] = ""
    params['result_root'] = ""

    # ==================== AEM 热力学参数（物理描述符） ====================
    # 依据：Man et al. 2011 ChemCatChem 3, 1159（标度关系 + Co3O4 火山图位置）
    # ΔG_O−ΔG_OH = 1.57 eV ≈ Co3O4 在该文中的描述符值（最优 1.6），η_理论 ≈ 0.40 V
    # G_OH 绝对值泛函敏感（DFT+U 会移动吸附腿），作为拟合描述符使用
    params['G_OH'] = 1.10             # *OH 吸附自由能 (eV)
    params['G_O'] = 2.70              # *O 吸附自由能 (eV)
    params['scaling_OOH_OH'] = 3.2    # *OOH/*OH 标度偏移 (Man 2011: 3.20±0.2 eV)

    # ==================== 预氧化参数 ====================
    # 依据：1 M KOH 中 Co3+/4+ 氧化峰 1.43–1.5 V vs RHE（碱性 CoOx 文献一致区间）
    # 注意：Bonke 2016 的 E0cat=1.9–2.1 V 是 pH 9.2 硼酸体系，不可移植
    params['E0_pre'] = 1.45           # Co³⁺/⁴⁺ 氧化电位 (V vs RHE)
    params['k0_pre'] = 500.0          # 预氧化速率 (s⁻¹, Bonke k0cat=90–325 同量级，待标定)

    # ==================== AEM 动力学参数 ====================
    # BV 标准速率常数无文献表值，属反演目标量
    # 默认值置于 FTacV 敏感窗口（k0 ~ 2πf ≈ 57 s⁻¹）附近，保证谐波对各步有区分度
    params['k0_1'] = 5e3    # *ox → *ox-OH
    params['k0_2'] = 5e3    # *ox-OH → *ox-O
    params['k0_3'] = 20.0   # *ox-O → *ox-OOH (PDS, 最慢，增强非线性)
    params['k0_4'] = 5e3    # *ox-OOH → *ox + O₂

    # ==================== 电极与电解液参数 ====================
    params['electrode_type'] = 'Planar'
    params['A'] = 1.0                # 电极面积 (cm²)
    params['Ru'] = 10.0              # 未补偿电阻 (Ω)
    params['Cdl'] = 20e-6            # 双电层电容 (F/cm²)
    params['gamma'] = 5e-8           # 活性位点总浓度 (mol/cm²)

    # ---- 候选M1：高电位活性位增长（默认关闭）----
    # gamma_eff = gamma * [1 + beta_recon * sigmoid((E - E_recon) / w_recon)]
    params['beta_recon'] = 0.0        # 0严格恢复固定gamma的M0模型
    params['E_recon'] = 1.55          # 重构启动电位 (V vs RHE)
    params['w_recon'] = 0.05          # 重构过渡宽度 (V)

    # ==================== FTacV 扫描参数 ====================
    params['Eref'] = 0.0             # 参比偏置 (V)
    params['E_start'] = 0.9          # 起始电位 (V vs RHE)
    params['E_end'] = 2.0            # 终止电位 (V vs RHE, 覆盖 OER 全范围)
    params['n_points'] = 16384       # 总采样点数（确保谐波分辨率）
    params['points_per_cycle'] = 256  # 每周期点数（7th 谐波 ≈37 pts/cycle）
    params['f'] = 9.02               # 正弦频率 (Hz)
    params['dE'] = 0.20              # 交流振幅 (V)

    # ==================== 物理常数 ====================
    params['F'] = 96485.0            # 法拉第常数 (C/mol)
    params['R'] = 8.314              # 气体常数 (J/(mol·K))
    params['T'] = 298.15             # 温度 (K)
    params['a'] = 0.5                # 转移系数

    # ==================== 数值参数 ====================
    params['N'] = 2                  # 扩散网格（暂不含传质）
    params['use_steady_state'] = True
    params['use_mex'] = False
    params['use_fft'] = True
    params['objective_mode'] = 'ftacv'

    # ==================== 谐波与滤波 ====================
    params['band'] = np.ones(8) * 1.0
    params['harmonic_weights'] = np.ones(8)

    # ==================== 优化设置 ====================
    params['max_number'] = 50000
    params['optimize_params'] = [
        'G_OH', 'G_O', 'scaling_OOH_OH',
        'log_k0_pre', 'log_k0_1', 'log_k0_2', 'log_k0_3', 'log_k0_4',
        'E0_pre', 'log_gamma', 'Ru',
    ]

    params['G_OH_range'] = [1.0, 2.2]
    params['G_O_range'] = [2.0, 4.0]
    params['scaling_OOH_OH_range'] = [2.8, 3.4]
    params['log_k0_pre_range'] = [-2, 5]
    params['log_k0_1_range'] = [-2, 5]
    params['log_k0_2_range'] = [-2, 5]
    params['log_k0_3_range'] = [-2, 5]
    params['log_k0_4_range'] = [-2, 5]
    params['E0_pre_range'] = [1.2, 1.8]
    params['log_gamma_range'] = [-12, -7]
    params['beta_recon_range'] = [0.0, 5.0]
    params['E_recon_range'] = [1.40, 1.70]
    params['w_recon_range'] = [0.02, 0.15]
    params['Ru_range'] = [0, 200]

    # ==================== 衍生参数计算 ====================
    params['omega'] = 2 * np.pi * params['f']
    params['total_time'] = (params['n_points'] / params['points_per_cycle']) / params['f']
    params['v'] = (params['E_end'] - params['E_start']) / params['total_time']
    params['t_span'] = np.linspace(0.0, params['total_time'], params['n_points'])

    # ==================== 应用 AEM 热力学约束 ====================
    params = OERPhysics.apply_alkaline_aem_embedded(params)

    # ==================== 初始化系统 ====================
    params = initialize_system(params)

    # ==================== 构建初始优化向量 ====================
    x0, lb, ub, names = get_optim_config(params)

    # ==================== 打印参数摘要 ====================
    _print_summary(params)

    return params


def _print_summary(params: dict) -> None:
    """打印参数初始化摘要。"""
    print("\n========== OER AEM 模型参数初始化完成 ==========")
    print(f"热力学描述符:")
    print(f"  G_OH  = {params['G_OH']:.2f} eV")
    print(f"  G_O   = {params['G_O']:.2f} eV")
    print(f"  scaling_OOH_OH = {params['scaling_OOH_OH']:.2f} eV"
          f" (G_OOH = {params.get('G_OOH', params['G_OH']+params['scaling_OOH_OH']):.2f} eV)")
    print("平衡电位:")
    print(f"  E0_pre = {params['E0_pre']:.3f} V (预氧化)")
    print(f"  E01 = {params['E01']:.3f}, E02 = {params['E02']:.3f}, "
          f"E03 = {params['E03']:.3f}, E04 = {params['E04']:.3f} V")
    print(f"理论过电位: η = {max(params['E01'], params['E02'], params['E03'], params['E04']) - 1.23:.3f} V")
    print("==================================================\n")
