# Windows 部署

## 环境要求

- Windows 10 或更高版本，以及可写的项目目录。
- 可访问 GitHub、Python 包索引和 Python 下载源的网络。
- 足够保存 Python 环境、数据库和漫画文件的空间。
- Git、uv 和 Python 3.12+；一键脚本会检查并安装缺少的工具和 Python。

无需额外安装 PowerShell 7、Node.js 或 Visual Studio 编译工具。使用系统自带 Windows PowerShell 和 CMD 即可；Git 若已经安装，winget 也不是必需工具。

## 一键部署：双击 BAT

将 [deploy.bat](https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.bat) 下载到希望存放项目的目录，双击运行。也可以在该目录的 CMD 中执行：

```bat
curl.exe -fL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.bat -o deploy.bat
deploy.bat
```

无法使用 curl 时可直接从浏览器下载文件。脚本使用系统 PowerShell 执行内嵌逻辑，先检查可通过 `python`、`python3` 或 `py` 调用的 Python 3.12+，有则直接使用；没有时检查 uv 已安装的 Python，仍没有则提示并通过 uv 下载 Python 3.12，不必提前安装 Python 或勾选 PATH。

随后脚本会检测并安装 Git、克隆或更新 `JMcomicBot` 子目录、同步运行依赖、生成配置并引导填写 NapCat 地址。Git 缺失时会尝试 winget；没有 winget 的机器请先从 [Git 官网](https://git-scm.com/downloads/win) 安装 Git。NapCat 端口推荐使用 3001–3010，回车默认使用 3001；已有有效地址会保留。

脚本执行结束会暂停，便于查看结果。`deploy.bat --check` 仅检查内嵌脚本语法，不执行部署。已有 `.env` / `option.yml` 会保留，有效 NapCat 地址保留，模板或非法地址会重新询问。

脚本不会安装 NapCat。NapCat、WebUI 和文件路径配置见 [共用配置指南](common.md)。

## 手动部署：由 uv 管理 Python

安装 Git 并确保 `git --version` 可用，然后在 CMD 中安装 uv：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
```

这是 [uv 官方安装器](https://docs.astral.sh/uv/getting-started/installation/)，无需提前安装 Python 或 pip。安装后重新打开 CMD，使 PATH 生效，再在自己的工作目录执行：

```bat
uv --version
uv python install 3.12
git clone https://github.com/AAA-huan/JMcomicBot.git
cd JMcomicBot
uv sync --no-dev --managed-python --python 3.12
```

按 [共用配置指南](common.md) 用 `copy` 复制配置文件，使用记事本等任意编辑器修改 `.env`。配置并启动 NapCat 后，在项目根目录执行：

```bat
uv run --no-dev --managed-python --python 3.12 python main.py
```

按 `Ctrl+C` 正常停止。后续更新时先停止机器人，再在项目根目录执行：

```bat
git pull --ff-only
uv sync --no-dev --managed-python --python 3.12
uv run --no-dev --managed-python --python 3.12 python main.py
```

无需激活 `.venv` 或另外运行 pip。普通部署使用仓库发布的前端资源，无需安装前端构建工具。
