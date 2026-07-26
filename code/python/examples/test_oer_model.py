"""碱性 OER AEM 模型测试脚本（对应 MATLAB test_oer_model.m）。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # 或者 'QtAgg'，确保能弹出窗口
import matplotlib.pyplot as plt

from oer_aem import OERPhysics, OERSignal, initialize_oer_parameters


def main():
    # ===== 1. 初始化参数 =====
    print('===== 初始化 OER AEM 模型参数 =====')
    params = initialize_oer_parameters()
    params['n_points'] = 2048
    params['points_per_cycle'] = 32
    params['total_time'] = (2048 / 32) / params['f']
    params['t_span'] = np.linspace(0, params['total_time'], 2048)

    # ===== 2. 运行模拟 =====
    print('\n===== 运行 ODE 模拟 =====')
    import time
    t0 = time.perf_counter()
    t, y, E_actual, i_total = OERPhysics.solve_ode_system(params)
    elapsed = time.perf_counter() - t0
    print(f'耗时: {elapsed:.1f}s')

    # ===== 3. 可视化 =====
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle("Alkaline OER AEM Model with Pre-oxidation (Co₃O₄ / CoOₓ(OH)ᵧ)", fontsize=13)

    # —— 覆盖度演化 ——
    ax1 = fig.add_subplot(2, 3, 1)
    ax1.plot(E_actual, y[:, 0], label='θ_* (inactive)')
    ax1.plot(E_actual, y[:, 1], label='θ_*ox (active)')
    ax1.plot(E_actual, y[:, 2], label='θ_*ox-OH')
    ax1.plot(E_actual, y[:, 3], label='θ_*ox-O')
    ax1.plot(E_actual, y[:, 4], label='θ_*ox-OOH')
    ax1.set_xlabel('E (V vs RHE)')
    ax1.set_ylabel('Coverage')
    ax1.legend(fontsize=7, loc='best')
    ax1.set_title('Surface Coverage Evolution')
    ax1.grid(True)

    # —— 预氧化 vs 催化分离 ——
    ax2 = fig.add_subplot(2, 3, 2)
    theta_total_ox = y[:, 1] + y[:, 2] + y[:, 3] + y[:, 4]
    ax2.plot(E_actual, y[:, 0], 'b', label='θ_* (reduced)')
    ax2.plot(E_actual, theta_total_ox, 'r', label='θ_total-ox (oxidized)')
    ax2.set_xlabel('E (V vs RHE)')
    ax2.set_ylabel('Coverage')
    ax2.legend(fontsize=8, loc='best')
    ax2.set_title('Pre-oxidation: Reduced vs Oxidized Co Sites')
    ax2.grid(True)

    # —— CV 曲线 ——
    ax3 = fig.add_subplot(2, 3, 3)
    ax3.plot(E_actual, i_total * 1e3, linewidth=1)
    ax3.set_xlabel('E (V vs RHE)')
    ax3.set_ylabel('i (mA)')
    ax3.set_title('Total Current vs Potential')
    ax3.grid(True)

    # —— FFT 频谱 ——
    ax4 = fig.add_subplot(2, 3, 4)
    df = OERSignal.safe_df(t)
    L = len(i_total)
    Y = np.fft.fft(i_total)
    f_axis = df * np.arange(L // 2) / L
    ax4.semilogy(f_axis, np.abs(Y[:L // 2]), linewidth=1)
    ax4.set_xlabel('Frequency (Hz)')
    ax4.set_ylabel('|FFT|')
    ax4.set_title('Current FFT Spectrum')
    ax4.set_xlim([0, 15 * params['f']])
    ax4.grid(True)

    # —— DC 分量 ——
    ax5 = fig.add_subplot(2, 3, 5)
    sos = params.get('lp_filter_sos', None)
    if sos is not None:
        from scipy.signal import filtfilt
        I_dc = np.abs(filtfilt(sos, i_total))
    else:
        I_dc = np.abs(i_total)
    ax5.plot(E_actual, i_total * 1e3, color='lightgray', linewidth=0.8)
    ax5.plot(E_actual, I_dc * 1e3, 'r', linewidth=1.5)
    ax5.set_xlabel('E (V vs RHE)')
    ax5.set_ylabel('i (mA)')
    ax5.legend(['Total', 'DC'], loc='best', fontsize=8)
    ax5.set_title('DC Component Extraction')
    ax5.grid(True)

    # —— 参数摘要 ——
    ax6 = fig.add_subplot(2, 3, 6)
    ax6.axis('off')
    lines = [
        'Model Parameters:',
        f"E0_pre = {params['E0_pre']:.2f} V  (Co³⁺/⁴⁺ pre-oxidation)",
        f"E0_1 = {params['E01']:.2f} V  (*ox → *ox-OH)",
        f"E0_2 = {params['E02']:.2f} V  (*ox-OH → *ox-O)",
        f"E0_3 = {params['E03']:.2f} V  (*ox-O → *ox-OOH)",
        f"E0_4 = {params['E04']:.2f} V  (*ox-OOH → *ox)",
        f"G_OH = {params['G_OH']:.2f} eV, G_O = {params['G_O']:.2f} eV",
        f"scaling = {params['scaling_OOH_OH']:.2f} eV",
        f"ΣΔG = {sum([params['E01'],params['E02'],params['E03'],params['E04']]):.2f} eV",
    ]
    for i, line in enumerate(lines):
        ax6.text(0, 0.95 - i * 0.1, line, fontsize=9 if i > 0 else 11,
                 fontweight='bold' if i == 0 else 'normal')

    plt.tight_layout()
    plt.show()

    # ===== 4. 检查 =====
    print('\n===== 模型检查 =====')
    print(f'覆盖度总和: {np.mean(np.sum(y[:, :5], axis=1)):.6f} (应为 1)')
    print(f'预氧化占比: {np.mean(theta_total_ox):.2%} (扫描平均)')
    print(f'理论过电位: {max(params["E01"], params["E02"], params["E03"], params["E04"]) - 1.23:.3f} V')


if __name__ == '__main__':
    main()
