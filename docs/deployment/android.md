# Android 部署

## 📋 环境要求

- 📱 **Android 7.0+ 系统（推荐）**
- 💾 至少 4GB 可用存储空间（Ubuntu系统需要更多空间）
- 🐍 Python >= 3.12
- 🌐 稳定的网络连接

## ⚡ 一键快速部署

先看下面proot的部署方式，然后在 proot Ubuntu 环境内，可直接运行一键部署脚本：它会自动安装 git/Python/uv、克隆项目、同步依赖、生成配置并引导填写关键项。

```bash
curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
```

脚本完成后会打印 NapCat 部署要点。若希望了解手动步骤再操作，可继续阅读下文。

> 脚本支持重复运行：再次执行等同于「拉取最新代码 + 同步依赖」，不会覆盖已填写的 `.env` / `option.yml`。

## 🚀 部署步骤

### 第一步：安装 Termux 和 proot

1. **安装 Termux**
   - 从 [F-Droid](https://f-droid.org/packages/com.termux/) 或 Google Play 安装 Termux
   - 或者下载 Termux APK 文件手动安装
   - 或者前往[ZeroTermux-Github](https://github.com/hanxinhao000/ZeroTermux/releases/tag/release)下载ZeroTermux.apk安装(推荐)

2. **换源**
   1. 如果下载的是原版termux，换源请前往短视频平台搜索教程，这里不过多赘述。
   2. 如果下载的是ZeroTermux，双击屏幕左侧边缘（部分ZT版本是按音量上/下键），下滑并点击"切换源"，随意选择，推荐选择清华源，等待脚本运行完成， 如无特殊说明，当出现 (Y/I/N/O/D/Z)[default=?] 或 [Y/N] 时，直接点击回车，选择默认选项即可。

3. **配置 Termux 并安装 proot**
   ```bash
   # 更新包管理器
   pkg update && pkg upgrade
   
   # 安装 proot-distro（更简单的Ubuntu安装方式）
   pkg install proot-distro -y
   ```

### 第二步：安装 Ubuntu 系统

1. **使用 proot-distro 安装 Ubuntu**
   ```bash
   # 安装 Ubuntu 系统
   proot-distro install ubuntu
   
   # 登录 Ubuntu 系统
   proot-distro login ubuntu
   ```

2. **用户账户配置（可选但推荐）**
   直接使用root用户操作所有命令可能有安全风险，建议创建一个普通用户账户：
   
**配置说明：**
   - 创建非root用户可以提高安全性，避免误操作
   - 添加sudo权限允许用户执行管理员命令
   - 密码输入时不显示是正常现象
   - 输入两次密码之后全部回车即可
   - 建议使用有意义的用户名，如 `jmbot`

      ```bash
      # 创建用户账户（将 username 替换为你的用户名）
      adduser username
      
      # 添加sudo权限
      usermod -aG sudo username
      
      # 切换到新用户
      su username
      
      # 验证用户权限
      sudo whoami
      ```
   

3. **配置 Ubuntu 系统**
   ```bash
   # 更新包管理器
   apt update && apt upgrade -y
   
   # 安装必要工具
   apt install sudo vim git python3-dev python3-venv build-essential screen curl python3-pip
   ```

### 第三步：在 Ubuntu 中部署机器人

1. **获取项目文件**
   ```bash
   # 切换到用户主目录
   cd ~

   # 创建项目目录
   mkdir JMBot
   cd ~/JMBot
   
   # 使用Git克隆项目
   git clone https://github.com/AAA-huan/JMcomicBot.git .
   # 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
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

4. **配置环境变量**
   ```bash
   # 复制漫画下载配置
   cp option_example.yml option.yml

   # 复制配置文件
   cp .env.example .env
   ```

   **编辑配置文件**
   ```bash
   # 使用编辑器打开配置文件
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
5. **创建数据目录**
   ```bash
   # 创建下载目录（在当前项目目录下）
   mkdir -p downloads
   chmod 755 downloads
   ```

### 第四步：配置 NapCat

1. **安装 NapCat**
   ```bash
   # 安装 NapCat
   curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
   sudo bash napcat.sh --docker n --cli y

   # 打开NapCat
   sudo napcat
   ```

2. **配置 WebSocket**
   - 用方向键和回车键选择
   - 在 NapCat 中配置 WebSocket 服务端
   - 确保端口与机器人配置一致
   - 在最后记得空格勾选启用配置
   - 配置完成后启动 NapCat

### 第五步：启动机器人

1. **在 Ubuntu 环境中启动**
   ```bash
   # 进入项目目录
   cd ~/JMBot

   # 启动机器人（uv 会自动使用 .venv，无需手动激活虚拟环境）
   uv run python main.py

   # 停止机器人
   Ctrl+C
   ```

### 🔄 六、常态化启动机器人

##### 1. 登录 Ubuntu 系统
```bash
# 在 Termux 中登录 Ubuntu
proot-distro login ubuntu

# 如果配置了非root用户，切换到该用户
su username
```

##### 2. 启动 NapCat 服务
```bash
# 在 Ubuntu 中启动 NapCat 服务
sudo napcat 
```

##### 3. 启动机器人
```bash
# 进入项目目录
cd ~/JMBot

# 启动机器人（uv 会自动使用 .venv，无需手动激活虚拟环境）
uv run python main.py

# 停止机器人
Ctrl+C
```

### 进程管理
```bash
# 查看机器人进程
ps aux | grep python

# 停止机器人（uv run 最终仍由 python 解释器执行 main.py）
pkill -f "main.py"

# 退出Ubuntu环境
exit
```

**推荐设置**
- 1. 推荐把termux的省电策略更改为：无限制
- 2. 推荐在进入termux还未登录proot时为termux打开唤醒锁(看到手机上方通知栏显示termux持有唤醒锁即成功)
```bash
   termux-wake-lock    # 打开唤醒锁
   termux-wake-unlock  # 关闭唤醒锁
```
