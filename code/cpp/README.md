# C++ 求解器

| 路径 | 内容 |
|---|---|
| `src/oer_cn_solver.cpp` | 正式 Crank–Nicolson 求解器 |
| `src/experimental/` | 未进入正式路径的实验实现 |
| `tests/` | C++ 与 bridge 测试 |
| `build/` | 本机动态库，Git 忽略 |

macOS 构建：

```bash
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.dylib code/cpp/src/oer_cn_solver.cpp
```

Legion 使用同一源码构建 `liboercn.so`。不得复制 macOS 动态库到 Linux。
