# 部署后的配置与使用

本文供 [Linux](linux.md)、[Windows](windows.md) 和 [Android/proot](android.md) 部署流程共用。所有项目命令均在包含 `main.py`、`pyproject.toml` 的项目根目录执行。

## 准备配置文件

一键脚本会生成 `.env` 和 `option.yml`。手动部署首次运行前需要复制示例文件；已有配置保留，不重复覆盖。

Linux / proot：

```bash
cp .env.example .env
cp option_example.yml option.yml
```

Windows CMD：

```bat
copy .env.example .env
copy option_example.yml option.yml
```

使用任意文本编辑器修改 `.env`。`option.yml` 是漫画下载和扫描联网补全使用的配置文件，必须保留在项目根目录；按需调整其中的客户端、代理和下载选项。

## 连接 NapCat

安装方式以 [NapCat 官方部署文档](https://napneko.github.io/guide/boot/Shell) 为准。启动 NapCat 并登录 QQ，在网络配置中启用 **WebSocket 服务端**，设置监听端口、路径和可选 token，再填写机器人 `.env`：

```ini
NAPCAT_WS_URL=ws://localhost:3001/qq
NAPCAT_TOKEN=""
```

`3001` 是一键脚本的默认端口，NapCat 也需配置相同端口；若已使用其他端口，改为实际监听端口。路径 `/qq` 与 NapCat 配置保持一致。启用 token 验证时，两边的 token 必须相同。NapCat 在另一台机器时，将 `localhost` 换成实际地址，并确保网络可达。

一键脚本推荐端口范围为 3001–3010，直接回车使用 3001。也可填写其他 1–65535 的合法端口，脚本会自动生成同机地址；远端 NapCat 可填写完整 `ws://` 或 `wss://` 地址。手动编辑 `.env` 须填写完整地址。

## 按需调整项目设置

| 设置 | 默认值 / 用途 |
|---|---|
| `MANGA_DOWNLOAD_PATH` | `./downloads`，漫画 PDF 保存目录 |
| `DB_PATH` | `./data`，数据库目录，内含 `main.db` |
| `BACKUP_PATH` | `./data/backups`，数据库备份目录 |
| `WEBUI_HOST`、`WEBUI_PORT` | `127.0.0.1`、`7999`，本机 WebUI 地址 |
| `GROUP_WHITELIST`、`PRIVATE_WHITELIST` | 允许响应的群 / 私聊；留空不限制 |
| `GLOBAL_BLACKLIST` | 禁止响应的用户；优先于白名单 |
| `DELETE_PERMISSION_USER` | QQ 删除权限用户，最多一个 |
| `LOW_MEMORY_MODE` | 默认 `false`；开启后会按配置清理漫画文件 |

完整选项与默认值见项目根目录 `.env.example`。程序会创建配置的下载目录和数据库目录，通常无需手动 `mkdir` 或 `chmod`；运行账户需要对这些目录有写入权限。

WebUI 随项目发布，普通部署无需安装 Node.js 或重新构建前端。启动后访问 `http://127.0.0.1:7999`（端口以实际配置为准）完成管理员首次设置，更多用法见 [WebUI 指南](../webui.md)。

## NapCat 与漫画文件访问

NapCat 发送文件时需要能够读取机器人生成的 PDF。分开部署在不同机器时，需要另外处理文件共享和路径一致性；仅配置 WebSocket 地址不能让远端 NapCat 自动获得本地文件。

使用 Docker 部署 NapCat 时，按官方文档创建容器，再将下载目录绑定到容器内的**相同绝对路径**。例如机器人保存到 `/home/huan/JMcomicBot/downloads`，则容器挂载参数为：

```text
-v /home/huan/JMcomicBot/downloads:/home/huan/JMcomicBot/downloads
```

示例路径须替换成自己的实际路径。容器中的 WebSocket 服务端须监听容器可访问的地址（通常为 `0.0.0.0`），并映射实际使用的 WebSocket 端口。Docker 是 NapCat 的一种可选部署方式，机器人本身不要求安装 Docker。

## 启动与更新

先让 NapCat 就绪并完成 QQ 登录，然后在项目根目录启动机器人。各平台指南提供对应的启动命令；终端中按 `Ctrl+C` 正常停止。

部署时使用 `uv sync --no-dev` 安装运行依赖，启动和维护时也使用 `uv run --no-dev`，避免安装开发检查工具。uv 会管理 `.venv`，不需要手动激活环境或再执行 `pip install`。

更新前停止机器人，在项目根目录执行 `git pull --ff-only`，然后按平台指南的命令重新同步依赖并启动。已有 `.env`、`option.yml` 和漫画文件保留；有数据库版本变化时，程序启动会自动迁移。

也可回到首次部署时的父目录，重新运行一键脚本。脚本会更新该目录下的 `JMcomicBot` 子目录；不要在项目目录内重复执行，以免误建嵌套目录。

维护操作见 [维护脚本指南](../maintenance.md)。后台常驻可按平台自行选择 systemd、任务计划程序或终端会话管理工具，均不是首次部署的必需工具。
