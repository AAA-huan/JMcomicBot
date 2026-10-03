# Linux 部署

## 📋 环境要求

- 🐍 Python >= 3.12
- 🐧 **Ubuntu 18.04 或更高版本（推荐）**
- 💾 至少 4GB 可用存储空间
- 🌐 稳定的网络连接
- 🔧 系统管理员权限

## ⚡ 一键快速部署

先安装 Python 3.12 或更高版本，再运行一键部署脚本：它会检查 Python 版本、检测并安装 git/uv、克隆项目、同步依赖、生成配置并引导填写关键项。

```bash
curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
```

脚本完成后会打印 NapCat 部署要点。若希望了解手动步骤再操作，可继续阅读下文。

NapCat 与机器人同机时，在脚本中只需填写 WebSocket 服务端端口（如 `3001`，有效范围 `1–65535`），脚本会写入 `NAPCAT_WS_URL=ws://localhost:3001/qq`。远端部署或自定义路径可填写完整 `ws://` / `wss://` 地址。手动编辑 `.env` 时仍须使用完整地址。

已有的纯端口配置会自动转换；有效地址会保留，模板或非法地址会重新询问。输入结束或代码更新失败时脚本会中止，处理原因后可重新运行。

> 脚本支持重复运行：再次执行等同于「拉取最新代码 + 同步依赖」，不会覆盖已填写的 `.env` / `option.yml`。

## 🚀 部署步骤

### 第一步：获取必要的文件

1. **安装 Git（如未安装）**
   ```bash
   # 更新包管理器并安装 Git
   sudo apt update
   sudo apt install git -y
   
   # 验证安装
   git --version
   ```

2. **创建项目目录**
   ```bash
   # 创建项目文件夹
   mkdir -p ~/JMBot
   cd ~/JMBot
   ```

3. **使用 Git 克隆项目**
   ```bash
   # 使用 Git 克隆项目到当前目录
   git clone https://github.com/AAA-huan/JMcomicBot.git .
   # 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
   ```

### 第二步：环境配置

1. **安装系统依赖**
   ```bash
   # 更新系统包
   sudo apt update
   sudo apt upgrade -y
   
   # 安装Python和必要工具
   sudo apt install -y python3 python3-venv git curl
   ```

2. **安装 uv**
   [uv](https://docs.astral.sh/uv/) 是 Python 包与环境管理器，可自动创建虚拟环境、按 `uv.lock` 安装依赖并运行程序，省去手动 `venv` 与 `pip` 步骤：
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **安装项目依赖**
   ```bash
   # 在项目目录内执行（自动创建 .venv 并按 uv.lock 安装依赖）
   uv sync
   ```

### 第三步：配置机器人

1. **复制配置文件**
   ```bash
   # 复制环境变量示例文件
   cp .env.example .env
    
   # 复制漫画下载配置示例
   cp option_example.yml option.yml
   ```

2. **编辑配置文件**
   ```bash
   # 编辑环境变量配置
   vim .env
   ```
   
   修改以下配置：
   ```ini
   # 必须修改的只有NAPCAT_WS_URL的port
   # 其他配置根据实际情况修改即可

   # WebSocket服务端配置
   # 修改port为实际的监听端口
   NAPCAT_WS_URL=ws://localhost:port/qq

   # API Token配置（可选）
   # 用于NapCat WebSocket服务的身份验证
   # 系统会自动将token添加到WebSocket连接URL中
   NAPCAT_TOKEN=""

   # 漫画下载路径
   # 可以使用相对路径（如./downloads）或绝对路径（如D:/downloads）
   MANGA_DOWNLOAD_PATH=./downloads # 默认使用当前目录下的downloads文件夹

   # 黑白名单配置
   # 群组白名单：允许使用机器人的群聊ID列表，多个ID用逗号分隔
   # 留空表示不限制（所有群组都可以使用）
   GROUP_WHITELIST=""

   # 私信白名单：允许使用机器人的用户ID列表，多个ID用逗号分隔
   # 留空表示不限制（所有用户都可以私信使用）
   PRIVATE_WHITELIST=""

   # 全局黑名单：任何情况下都禁止使用机器人的用户ID列表，多个ID用逗号分隔
   # 黑名单优先级高于白名单
   GLOBAL_BLACKLIST=""
   
   # 删除权限名单：允许使用删除功能的用户ID，允许为空，最多只能有一个用户ID
   DELETE_PERMISSION_USER=""

   # 内存低占用模式
   # true: 开启低占用模式，下载后立刻发送，发送后3分钟删除，启动时清空下载文件夹
   # false: 默认模式，保留下载的漫画（默认值）
   LOW_MEMORY_MODE=false

   # 更多高级配置项（如文件发送速率、批次大小、断线重发超时等）
   # 请参考项目根目录的 .env.example
   ```
   完成修改后保存并退出

3. **创建数据目录**
   ```bash
   # 创建下载目录
   mkdir -p ~/JMBot/downloads
   ```


### 第四步：配置 NapCat

1. **安装 NapCat**
   - 参考 NapCatQQ 文档安装 NapCat https://github.com/NapNeko/NapCatQQ
   - 配置 WebSocket 服务端与机器人配置匹配

> **注意** - 若使用docker部署napcat，则需要注意以下几点
1. napcat的websocket服务端的host该改为0.0.0.0
2. 部署时需要把downloads目录挂载到容器内
```bash
docker run -d \
-e NAPCAT_GID=$(id -g) \
-e NAPCAT_UID=$(id -u) \
-p 3000:3000 \
-p 3001:3001 \
-p 6099:6099 \
--name napcat \
--restart=always \
-v /home/$USER/JMBot/downloads:/home/$USER/JMBot/downloads \ # 加这行
mlikiowa/napcat-docker:latest

```

### 第五步：使用方法

##### 1. 启动 NapCat 服务
- 确保 NapCat 已正确安装并配置
- 启动 NapCat 服务（具体步骤参考 NapCat 官方文档）

##### 2. 启动机器人
```bash
# 进入项目目录
cd ~/JMBot

# 启动机器人（uv 会自动使用 .venv，无需手动激活虚拟环境）
uv run python main.py

# 停止机器人
Ctrl+C
```
