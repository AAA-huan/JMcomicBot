# Linux 部署

## 环境要求

- 可运行项目依赖的 Linux 系统，Ubuntu / Debian 可按下文安装工具。
- 可访问 GitHub、Python 包索引和 Python 下载源的网络。
- 可写的项目目录，以及容纳环境、数据库和漫画文件的存储空间。
- Git、uv 和 Python 3.12 或更高版本；Python 可在手动流程中由 uv 安装。

运行机器人不要求 root。只有需要安装系统软件时才使用系统管理员权限。`vim`、`screen`、Docker、系统 `pip`、`python3-venv` 和完整系统升级不作为必需步骤；若某个依赖确实报编译缺包，再按错误安装对应工具。

## 一键部署

现有 `deploy.sh` **检查预装且可通过 `python3` 或 `python` 调用的 Python 3.12+**，不会替你安装该 Python。已有符合要求的 Python 时，在希望存放项目的父目录执行：

```bash
curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
```

若缺少 curl，Ubuntu / Debian 可先执行：

```bash
sudo apt update
sudo apt install -y curl ca-certificates
```

脚本会检测并安装 Git/uv、克隆或更新 `./JMcomicBot`、同步运行依赖、准备配置，并引导填写 NapCat 地址等选项。安装 Git 等系统工具时可能需要权限；如果 Python 检查未通过，请使用下方手动流程。

脚本不会安装 NapCat，配置方法见 [共用配置指南](common.md)。已有 `.env` / `option.yml` 会保留，有效 NapCat 地址保留，模板或非法地址会重新询问；更新失败或输入结束会中止。

## 手动部署：由 uv 管理 Python

Ubuntu / Debian 只需先准备 Git、curl 和 HTTPS 证书；其他发行版使用各自的软件包管理器安装对应工具。以 root 操作时，以下系统安装命令去掉 `sudo`。

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
```

安装 uv，按安装器提示重新打开终端或加载它给出的环境文件，再确认命令可用：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv --version
uv python install 3.12
cd ~
git clone https://github.com/AAA-huan/JMcomicBot.git
cd JMcomicBot
uv sync --no-dev --managed-python --python 3.12
```

uv 可以安装 Python 并创建项目虚拟环境，无需另装系统 Python、pip 或手动创建 venv；详见 [uv 的 Python 管理说明](https://docs.astral.sh/uv/guides/install-python/)。

按 [共用配置指南](common.md) 复制 `.env`、`option.yml`，安装并配置 NapCat，然后启动：

```bash
uv run --no-dev --managed-python --python 3.12 python main.py
```

按 `Ctrl+C` 停止。后续更新时，在项目根目录执行：

```bash
git pull --ff-only
uv sync --no-dev --managed-python --python 3.12
uv run --no-dev --managed-python --python 3.12 python main.py
```
