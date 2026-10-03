# 开发质量检查

使用项目依赖环境运行：

```bash
uv run black --check .
uv run pylint src
uv run pyright src
uv run pytest tests/ -v
cd webui
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
```

`.pylintrc` 明确了现有架构的检查尺度：机器人装配、命令分发和完整下载流程保留现有结构，按项目规模设定参数、属性、分支与行数上限。ORM 模型及结果对象不要求凑公共方法；职责独立的仓储不强行合并相似事务代码，因此停用 `too-few-public-methods` 与 `duplicate-code`。其他错误与警告继续检查。

仓储抽象入口的可变参数与各具体资源查询签名有意不同，相关仓储局部标注 `arguments-differ`。SQLAlchemy 的动态 `func.count()` 使用局部 `not-callable` 标注；运行于任务或命令边界的既有异常捕获，以及仅适用于 Unix 的延迟导入也采用局部标注。此轮没有改写这些既有运行逻辑。

E2E 使用临时目录和独立数据库，覆盖桌面与 360px 手机视口。大文件用例生成约 5 MiB、20 页的 PDF，验证停留首页时的 Range 请求量小于 3 MiB，跳转未读页面会产生新的 Range 请求。浏览器视口模拟不替代 Termux 实机内存和性能验证。
