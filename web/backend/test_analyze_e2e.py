"""TestClient 验证 /api/data/analyze + 65536 点 simulate 耗时。"""
import sys, time, json
from pathlib import Path

import numpy as np

ROOT = Path('/Users/liushiyu/OER-FTAcV')
sys.path.insert(0, str(ROOT / 'web' / 'backend'))
sys.path.insert(0, str(ROOT / 'python'))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# ---- 1. 加载实验数据 ----
rows = np.loadtxt(ROOT / 'ftacv4-ref.txt')
print(f'数据: {rows.shape}')

# ---- 2. /api/data/analyze ----
t0 = time.perf_counter()
r = client.post('/api/data/analyze', json={'rows': rows.tolist()})
dt = time.perf_counter() - t0
res = r.json()
assert res.get('success'), f"analyze 失败: {res.get('error')}"
meta = res['meta']
print(f'analyze 耗时 {dt:.1f} s')
print(f"识别: f={meta['f']:.4f} Hz, dE={meta['dE']:.4f} V, v={meta['v']*1000:.3f} mV/s")
print(f"      E: {meta['E_start']:.3f} -> {meta['E_end']:.3f} V, "
      f"{meta['duration']:.1f} s, {meta['n_points']} pts, fs={meta['fs']:.1f} Hz")

dc = np.array(res['dc'])
harm = [np.array(h) for h in res['harmonics']]
print(f'DC: max={dc.max():.3f} min={dc.min():.3f}')
for k, h in enumerate(harm):
    # 结构检查：归一化后峰值位置
    pk = int(np.argmax(np.abs(h)))
    print(f'  H{k+1}: max={np.abs(h).max():.3f} 峰值@tdc={res["tdc"][pk]:.3f} V')

# ---- 3. /api/simulate 同步参数（快速档：64 周期 16384 点）----
sim_in = {
    'E_start': meta['E_start'], 'E_end': meta['E_end'],
    'f': meta['f'], 'dE': meta['dE'],
    'n_points': 16384, 'points_per_cycle': 256,
}
t0 = time.perf_counter()
r2 = client.post('/api/simulate', json=sim_in)
dt2 = time.perf_counter() - t0
res2 = r2.json()
if res2.get('success'):
    tdc = np.array(res2['tdc'])
    assert abs(tdc[0] - meta['E_start']) < 0.02, f'tdc 起点错误: {tdc[0]}'
    assert abs(tdc[-1] - meta['E_end']) < 0.02, f'tdc 终点错误: {tdc[-1]}（应为 {meta["E_end"]:.3f}，v 未随参数重算的回归）'
    E_a = np.array(res2['E_actual'])
    assert E_a.max() < meta['E_end'] + 2 * meta['dE'] + 0.5, f'E_actual 超界: {E_a.max()}'
    print(f'\nsimulate {sim_in["n_points"]} pts ({sim_in["n_points"]//256} cyc): {dt2:.1f} s (ode {res2["time_elapsed"]:.1f} s)')
    print(f'tdc: {tdc[0]:.3f} -> {tdc[-1]:.3f} V ✓  E_actual max: {E_a.max():.3f} V ✓')
    sh = np.array(res2['harmonics'][0])
    eh = harm[0]
    n = min(len(sh), len(eh))
    c = np.corrcoef(sh[:n], eh[:n])[0, 1]
    print(f'H1 仿真 vs 实验相关系数: {c:.4f}（各自归一化）')
else:
    print(f'\nsimulate 失败: {res2.get("error")}')

# ---- 4. 若太慢，试 128 周期 ----
if dt2 > 60:
    sim_in['n_points'] = 32768
    t0 = time.perf_counter()
    r3 = client.post('/api/simulate', json=sim_in)
    print(f'simulate 32768 pts (128 cyc): {time.perf_counter()-t0:.1f} s')
