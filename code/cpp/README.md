# C++ 求解器

| 路径 | 内容 |
|---|---|
| `src/oer_cn_solver.cpp` | CN screen-only 求解器（解析 Newton Jacobian；未通过 A3 前不得作正式结论） |
| `src/experimental/` | 未进入正式路径的实验实现 |
| `tests/` | C++ 与 bridge 测试 |
| `build/` | 本机动态库，Git 忽略 |

macOS 构建：

```bash
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.dylib code/cpp/src/oer_cn_solver.cpp
```

Legion 使用同一源码构建 `liboercn.so`。不得复制 macOS 动态库到 Linux。

该库返回 `0` 表示有限输出，`-1` 表示输入非法，`-2` 表示稳态初始化未收敛，
`-3` 表示数值非有限，`-4` 表示输出区间内的 CN Newton/细分未收敛。
CN 与 LSODA/BDF 的相位等价性仍需单独通过 Gate A3；速度提升不能替代等价性验收。

批量入口 `oer_cn_solve_batch` 接收连续的 `n_cases × 32` 参数块，返回
`n_cases × n_points` 电流和逐案例状态码。批量接口只用于 screen-only 候选筛选；
失败案例必须依据 status 单独处理，不得用 NaN 或静默删除代替失败证据。
