# Windows 部署

## 📋 环境要求

- 🪟 **Windows 10 或更高版本**
- 🐍 **Python >= 3.12**
- 💾 **至少 4GB 可用存储空间**（根据下载漫画数量调整）
- 🌐 **稳定的网络连接**（支持代理配置）

## ⚡ 推荐：使用 uv 部署（更简单）

[uv](https://docs.astral.sh/uv/) 是 Python 包与环境管理器，可自动创建虚拟环境、按 `uv.lock` 安装依赖并运行程序，省去手动 `venv` 与 `pip` 步骤：

```powershell
# 1. 安装 uv（一次性；也可用 pip install uv）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 在项目目录内安装依赖（自动创建 .venv）
uv sync

# 3. 启动机器人（无需手动激活虚拟环境）
uv run python main.py
```

> 使用 uv 后，下文「环境配置」中的 `python -m venv` 与 `pip install` 可跳过；后文所有 `python main.py` 均可替换为 `uv run python main.py`。

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

##### 2. 创建虚拟环境
```bash
# 确保在JMBot项目文件夹内
# 鼠标右键打开powershell
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows PowerShell:
venv\Scripts\Activate

# 验证虚拟环境激活
python --version
pip --version
```

##### 3. 安装项目依赖
```bash
# 使用 pip 安装依赖
pip install -r requirements.txt  --upgrade
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
   # 启动机器人
   python main.py

   # 或使用 uv 运行（无需手动激活虚拟环境）
   uv run python main.py

   # 停止机器人
   Ctrl+C
   ```

### 🔄 六、常态化启动

##### 1. 启动 NapCat 服务
- 确保 NapCat 已正确安装并配置
- 启动 NapCat 服务

##### 2. 激活虚拟环境并启动机器人
   ```bash
   # 进入项目目录
   # 右键点击项目文件夹，选择在powershell中打开

   # 激活虚拟环境
   venv\Scripts\Activate

   # 启动机器人
   python main.py

   # 或使用 uv 运行（无需激活虚拟环境）
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
