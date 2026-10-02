# Windows 部署

## 📋 环境要求

- 🪟 **Windows 10 或更高版本**
- 🐍 **Python >= 3.12**
- 💾 **至少 4GB 可用存储空间**（根据下载漫画数量调整）
- 🌐 **稳定的网络连接**（支持代理配置）

## ⚡ 一键快速部署

如果你希望最快完成部署，可直接使用powershell运行一键部署脚本：它会自动安装 git/Python/uv、克隆项目、同步依赖、生成配置并引导填写关键项。

```powershell
irm https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.ps1 | iex
```

脚本完成后会打印 NapCat 部署要点。若希望了解手动步骤再操作，可继续阅读下文。

> 脚本支持重复运行：再次执行等同于「拉取最新代码 + 同步依赖」，不会覆盖已填写的 `.env` / `option.yml`。

## 🚀 部署步骤

### 📥 第一步：获取项目文件

##### 1. 安装 Git（如未安装）
```bash
# 下载并安装 Git
# 访问 https://git-scm.com/downloads 下载Windows版Git
# 安装时选择"Use Git from the Windows Command Prompt"
# 验证安装：git --version
```

##### 2. 克隆项目到本地
```bash
# 创建项目文件夹
mkdir JMBot
cd JMBot

# 使用 Git 克隆项目
git clone https://github.com/AAA-huan/JMcomicBot.git .
# 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
```

### ⚙️ 第二步：环境配置

##### 1. 安装 Python 环境
- 访问 [Python官网](https://www.python.org/downloads/) 下载最新版Python
- 安装时务必勾选「Add Python to PATH」选项
- 必须安装 Python 3.12 或更高版本（项目依赖要求）

##### 2. 安装 uv
[uv](https://docs.astral.sh/uv/) 是 Python 包与环境管理器，可自动创建虚拟环境、按 `uv.lock` 安装依赖并运行程序，省去手动 `venv` 与 `pip` 步骤：
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

##### 3. 安装项目依赖
```powershell
# 在项目目录内执行（自动创建 .venv 并按 uv.lock 安装依赖）
uv sync
```

### 🔧 第三步：配置机器人

##### 1. 复制配置文件
```bash
# 复制环境变量示例文件
copy .env.example .env

# 复制漫画下载配置示例
copy option_example.yml option.yml
```

##### 2. 编辑配置文件
打开 `.env` 文件，修改以下关键配置：

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

### 第四步：配置 NapCat

1. **安装 NapCat**
   - 下载并安装 NapCat：https://github.com/NapNeko/NapCatQQ
   - 启动 NapCat 并扫码登录 QQ 账号

2. **加载配置文件**
   - 启动NapCat时，确保它能够加载到您配置的`napcat_config.yml`文件
   - 您也可以通过NapCat的WebUI界面进行配置（WebUI地址可在NapCat启动面板查看）

3. **验证配置**
   - 访问 NapCat 的 WebUI
   - 检查「网络配置」→「WebSocket 服务端」中的设置是否与您在文件中配置的一致
   - 确认路径(path)为 `/qq`
   - 确认token值与.env文件中的配置一致（如果启用了验证）

### 第五步：启动机器人

   ```bash
   # 进入项目目录
   # 右键点击项目文件夹，选择在powershell中打开
   # 启动机器人（uv 会自动使用 .venv，无需手动激活虚拟环境）
   uv run python main.py

   # 停止机器人
   Ctrl+C
   ```

### 🔄 六、常态化启动

##### 1. 启动 NapCat 服务
- 确保 NapCat 已正确安装并配置
- 启动 NapCat 服务

##### 2. 启动机器人
   ```bash
   # 进入项目目录
   # 右键点击项目文件夹，选择在powershell中打开

   # 启动机器人（uv 会自动使用 .venv，无需手动激活虚拟环境）
   uv run python main.py
   ```

##### 3. 验证运行状态
- 检查任务管理器是否有 `python.exe` 进程
- 查看日志文件确认机器人正常运行

##### 4. 停止程序
```bash
# 方法一：通过任务管理器结束 python.exe 进程

# 方法二：使用 PowerShell 命令
   ctrl + C
```
