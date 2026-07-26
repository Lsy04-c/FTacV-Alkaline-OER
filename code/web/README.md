# Web 代码

| 路径 | 内容 |
|---|---|
| `frontend/` | React/Vite 前端 |
| `backend/` | FastAPI 服务 |
| `tests/backend/` | 后端接口测试 |

Web 层只调用 `code/python/src/oer_aem/`，不得复制科学计算逻辑。

当前前端是静态 `frontend/index.html`，没有打包构建步骤。开发入口：

```bash
bash code/web/dev.sh
```

后端测试：

```bash
.venv/bin/python -m pytest code/web/tests/backend -q
```
