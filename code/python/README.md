# Python 代码

## 目录

| 路径 | 内容 |
|---|---|
| `src/oer_aem/` | 科学计算核心 |
| `tests/` | 核心单元测试和回归测试 |
| `scripts/` | 计算、诊断、验证和结果生成入口 |
| `examples/` | 最小使用示例 |
| `experimental/` | 未通过正式等价性门、不得被生产路径隐式导入的实验实现 |

## 测试

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

新增科学逻辑放入 `src/oer_aem/`，对应测试放入 `tests/`。不要在脚本中复制核心算法。
实验实现先放入 `experimental/`；只有补齐测试、科学等价性证据和项目记录后，才能迁入正式包。
