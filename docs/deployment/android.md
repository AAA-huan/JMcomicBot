# Android 部署（Termux + proot）

## 环境要求

- 能运行当前 Termux 软件包的 Android 设备，官方完整软件包支持 Android 7 或更高版本。
- 可访问软件源、GitHub、Python 包索引和 Python 下载源的网络。
- 能容纳 Ubuntu / Debian、Python 环境和漫画文件的存储空间。

本项目的 Android 机器人部署流程在 **proot 内的 Ubuntu / Debian** 执行，Python 全部交给 uv 管理。无需在 Termux 或系统发行版里预先安装 Python、pip、`python3-dev`、`python3-venv`、`build-essential`、`vim`、`screen`。这些工具不列为机器人部署前提。

## 1. 在 Termux 准备 proot

推荐使用ZeroTermux，从 [ZeroTermux GitHub仓库](https://github.com/hanxinhao000/ZeroTermux) 获取 Termux；已有可用环境可直接继续。

以下命令在 **Termux** 中执行：

```bash
pkg update
pkg install proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
```

安装与登录语法以 [proot-distro 官方文档](https://github.com/termux/proot-distro#quick-start) 为准。已有 Ubuntu 容器时只需登录，不重复安装。较旧版本的安装器可能使用 `proot-distro install ubuntu`；可用 `proot-distro install --help` 核对当前版本。

此后以下机器人部署命令都在 **Ubuntu / Debian 内** 执行。默认 proot 登录的 root 是该环境内的身份，不需要额外创建用户或安装 sudo；若自行使用普通用户，先由有权限的账户准备 Git、curl 和证书，再切换用户部署。

## 2. 一键部署机器人

在希望存放项目的父目录执行：

```bash
# 官方源
curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash

# 加速源
curl -fsSL https://ghproxy.net/https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
```
脚本先检查环境中是否有 Python 3.12+，有则直接使用；没有时检查 uv 已安装的 Python，仍没有则提示并通过 uv 下载 Python 3.12，无需提前安装系统 Python 或 pip。

随后脚本会检测并安装 Git、克隆或更新 `./JMcomicBot`、同步运行依赖、准备配置，并引导填写 NapCat 地址等选项。安装 Git 等系统工具时可能需要权限。NapCat 端口推荐使用 3001–3010，回车默认使用 3001；已有有效地址会保留。

一键脚本不会安装 NapCat。配置与文件共享要求见 [共用配置指南](common.md)。已有 `.env` / `option.yml` 会保留，有效 NapCat 地址保留，模板或非法地址会重新询问。

NapCat 端口推荐使用 3001–3010，回车默认使用 3001。如果 NapCat 已使用其他端口，填写实际端口即可。

## 3. 可选的手动部署

在 proot 内安装 Git和uv：

```bash
apt update
apt install -y git
curl -LsSf https://astral.sh/uv/install.sh | sh
```

按安装器提示加载它给出的环境文件或重新登录 proot，确认 `uv --version` 可用，再执行：

```bash
uv python install 3.12
cd ~
git clone https://github.com/AAA-huan/JMcomicBot.git
cd JMcomicBot
uv sync --no-dev --managed-python --python 3.12
```

如果 `command -v uv` 或 Python 相关路径指向 `/data/data/com.termux/`，先修正 proot 的环境设置，或使用专用一键脚本完成环境检查。手动流程也需要在项目根目录复制 `.env` 和 `option.yml`，见 [共用配置指南](common.md)。

## 4. 配置 NapCat 与日常启动

NapCat 可按 [官方 Android/Termux 部署说明](https://napneko.github.io/guide/boot/Shell) 选择独立的 Termux 安装方式，也可按其当前文档选择适合设备的方式；不要直接照搬桌面 Linux 的 sudo/Docker 安装流程。

机器人和 NapCat 位于不同环境时，双方都必须能读取下载目录，并使用匹配的文件路径；仅能连接 WebSocket 不代表能够发送文件。地址、token 和文件访问说明见 [共用配置指南](common.md)。

日常启动时，在 Termux 先登录 proot：

```bash
proot-distro login ubuntu
```

在 proot 内进入项目目录，确认 NapCat 已就绪后启动机器人：

```bash
cd ~/JMcomicBot
uv run python main.py
```

按 `Ctrl+C` 停止机器人，`exit` 退出 proot。更新时在项目根目录执行：

```bash
git pull --ff-only
uv sync --no-dev --managed-python --python 3.12
```

按需在 Android 设置中允许 Termux 后台运行、关闭对它的省电限制；Termux 内的 `termux-wake-lock` / `termux-wake-unlock` 可用于管理唤醒锁。这些是长时间运行的可选设置，不需要为首次部署安装会话管理工具。
