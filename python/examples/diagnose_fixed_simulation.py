"""修复后首次完整仿真诊断图：覆盖度 / 总电流 / 功率谱 / DC+谐波包络。"""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, str(Path(sys.executable).parent.parent.parent))

import numpy as np
from daimon_runtime import setup_plot
setup_plot()
import matplotlib.pyplot as plt

from oer_aem import OERPhysics, OERSignal, initialize_oer_parameters

params = initialize_oer_parameters()
params['n_points'] = 16384
params['points_per_cycle'] = 256
params['total_time'] = (params['n_points'] / params['points_per_cycle']) / params['f']
params['t_span'] = np.linspace(0, params['total_time'], params['n_points'])

t, y, E_actual, i_total = OERPhysics.solve_ode_system(params)
print("solver points:", len(t), "/", params['n_points'])
assert len(t) == params['n_points'], "求解器未完成全程！"

E_dc = params['E_start'] + params['v'] * t
df = OERSignal.safe_df(t)
I_harm = OERSignal.extract_harmonics(i_total, df, params)
I_proc = OERSignal.process_current(i_total, df, params)
I_dc = I_proc[:, 0]

fig = plt.figure(figsize=(15, 9))

ax1 = fig.add_subplot(2, 3, 1)
labels = ['θ_*', 'θ_*ox', 'θ_*ox-OH', 'θ_*ox-O', 'θ_*ox-OOH']
for i in range(5):
    ax1.plot(E_dc, y[:, i], label=labels[i], lw=0.8)
ax1.set_xlabel('E_dc (V vs RHE)'); ax1.set_ylabel('Coverage')
ax1.set_title('Surface Coverage Evolution'); ax1.legend(fontsize=7); ax1.grid(alpha=0.3)

ax2 = fig.add_subplot(2, 3, 2)
ax2.plot(E_actual, i_total * 1e3, lw=0.4)
ax2.set_xlabel('E (V vs RHE)'); ax2.set_ylabel('i (mA)')
ax2.set_title('Total Current'); ax2.grid(alpha=0.3)

ax3 = fig.add_subplot(2, 3, 3)
L = len(i_total)
Y = np.fft.fft(i_total - i_total.mean())
P1 = np.abs(Y / L)[:L // 2 + 1] * 2
f_axis = df * np.arange(L // 2 + 1) / L
ax3.semilogy(f_axis, P1, lw=0.8)
for h in range(1, 8):
    ax3.axvline(h * params['f'], color='r', ls=':', alpha=0.4)
ax3.set_xlim(0, 8 * params['f'])
ax3.set_xlabel('Frequency (Hz)'); ax3.set_ylabel('|FFT| (A)')
ax3.set_title('Power Spectrum (harmonics marked)'); ax3.grid(alpha=0.3)

ax4 = fig.add_subplot(2, 3, 4)
ax4.plot(E_dc, I_dc / I_dc.max(), 'k', lw=1.2, label='DC')
ax4.set_xlabel('E_dc (V vs RHE)'); ax4.set_ylabel('normalized |i|')
ax4.set_title('DC Component'); ax4.legend(fontsize=7); ax4.grid(alpha=0.3)

ax5 = fig.add_subplot(2, 3, 5)
for k in range(4):
    h = I_harm[:, k]
    ax5.plot(E_dc, h / max(h.max(), 1e-30), lw=0.8, label=f'{k+1}f')
ax5.set_xlabel('E_dc (V vs RHE)'); ax5.set_ylabel('normalized envelope')
ax5.set_title('Harmonics 1-4'); ax5.legend(fontsize=7); ax5.grid(alpha=0.3)

ax6 = fig.add_subplot(2, 3, 6)
for k in range(4, 7):
    h = I_harm[:, k]
    ax6.plot(E_dc, h / max(h.max(), 1e-30), lw=0.8, label=f'{k+1}f')
ax6.set_xlabel('E_dc (V vs RHE)'); ax6.set_ylabel('normalized envelope')
ax6.set_title('Harmonics 5-7'); ax6.legend(fontsize=7); ax6.grid(alpha=0.3)

fig.suptitle('Fixed-model full-scan FTacV simulation (defaults: f=9.02 Hz, dE=0.15 V, Γ=1e-7)', fontsize=12)
fig.tight_layout()
out = os.path.join(os.path.dirname(__file__), 'fixed_simulation_diagnostics.png')
fig.savefig(out, dpi=180, bbox_inches='tight')
print("saved:", out)

# 定量：各次谐波峰值电流
for k in range(7):
    print(f"harmonic {k+1}: peak = {I_harm[:,k].max():.3e} A")
print(f"DC peak = {I_dc.max():.3e} A")
