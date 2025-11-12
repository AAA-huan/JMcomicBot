# JMComic QQ 机器人

一个基于 NapCat 的 QQ 机器人，可以帮助用户下载、管理和分享禁漫天堂的漫画内容。支持漫画下载、查询和发送功能，并提供友好的交互界面。

## 🚀 功能特性

- **漫画下载**: 通过漫画ID一键下载漫画
- **漫画发送**: 发送已下载的漫画文件到QQ聊天
- **下载状态查询**: 实时查询下载进度和状态
- **已下载漫画列表**: 查看已下载的漫画内容
- **自动PDF转换**: 支持将下载的图片转换为PDF格式
- **异步处理**: 多线程处理下载任务，不阻塞其他功能
- **通信方式**: 支持WebSocket和HTTP两种通信方式
- **自动重连**: 网络断开时自动尝试重连，保持稳定连接
- **日志系统**: 彩色日志输出，便于问题排查
- **安全认证**: 支持Token验证，保护API安全
- **自定义配置**: 灵活的下载参数配置

---

## 📦 Windows 部署

### 📋 环境要求

- 🐍 Python >= 3.7
- 🪟 Windows 10 或 Windows 11
- 💾 至少 2GB 可用存储空间
- 🌐 稳定的网络连接

### 🚀 部署步骤

#### 一、获取必要的文件

1. **安装 Git（如未安装）**
   ```bash
   # 下载并安装 Git
   # 访问 https://git-scm.com/downloads 下载Windows版Git
   # 安装时选择"Use Git from the Windows Command Prompt"
   # 验证安装：git --version
   ```

2. **使用 Git 克隆项目**
   ```bash
   # 创建项目文件夹
   mkdir JMComicBot
   cd JMComicBot
   
   # 使用 Git 克隆项目
   git clone https://github.com/your-repo/JMComicBot.git .
   ```

#### 二、环境配置

1. **安装 Python**
   - 访问 [Python官网](https://www.python.org/downloads/) 下载最新版Python
   - 安装时勾选「Add Python to PATH」选项

2. **安装依赖包**
   ```bash
   # 验证 Python 安装
   python --version

   # 使用 pip 安装依赖
   pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
   ```

#### 三、配置机器人

1. **复制配置文件**
   ```bash
   # 复制环境变量示例文件
   copy .env.example .env
   
   # 复制NapCat配置示例
   copy napcat_config_example.yml napcat_config.yml
   ```

2. **编辑配置文件**
   - 打开 `.env` 文件，修改以下配置：
   ```ini
   # NapCat WebSocket 服务配置
   NAPCAT_WS_URL=ws://localhost:6099/wsapi
   
   # 漫画下载路径
   MANGA_DOWNLOAD_PATH=./downloads
   
   # 安全认证 Token
   TOKEN=your_secure_token_here
   ```

#### 四、配置 NapCat

1. **安装 NapCat**
   - 下载并安装 NapCat：https://github.com/NapNeko/NapCatQQ
   - 启动 NapCat 并扫码登录 QQ 账号

2. **配置 WebSocket 服务**
   - 访问 NapCat 的 WebUI（默认地址：http://localhost:6099/webui）
   - 在「网络配置」→「WebSocket 服务端」中创建服务
   - 配置与 `.env` 文件中的 `NAPCAT_WS_URL` 匹配

#### 五、启动机器人

1. **手动启动（推荐）**
   ```bash
   # 进入项目目录
   cd JMComicBot
   
   # 启动机器人
   python bot.py

   # 停止机器人
   Ctrl+C
   ```

### 🎯 使用方法

在QQ群或私聊中发送以下命令：

- `漫画帮助` - 查看所有可用命令
- `漫画下载 350234` - 下载指定ID的漫画
- `发送 350234` - 发送已下载的漫画文件
- `查询已下载漫画` - 查看已下载漫画列表

---

## 🐧 Linux 部署

### 📋 环境要求

- 🐍 Python >= 3.7
- 🐧 **Ubuntu 18.04 或更高版本（推荐）**
- 💾 至少 4GB 可用存储空间
- 🌐 稳定的网络连接
- 🔧 系统管理员权限

### 🚀 部署步骤

#### 一、获取必要的文件

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
   sudo mkdir -p /opt/JMBot
   sudo chown $USER:$USER /opt/JMBot
   cd /opt/JMBot
   ```

3. **使用 Git 克隆项目**
   ```bash
   # 使用 Git 克隆项目到当前目录
   git clone https://github.com/your-repo/JMComicBot.git .
   ```

#### 二、环境配置

1. **安装系统依赖**
   ```bash
   # 更新系统包
   sudo apt update
   sudo apt upgrade -y
   
   # 安装Python和必要工具
   sudo apt install -y python3 python3-pip python3-venv git
   ```

2. **创建虚拟环境**
   ```bash
   # 创建虚拟环境
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **安装依赖包**
   ```bash
   # 安装项目依赖
   pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
   ```

#### 三、配置机器人

1. **复制配置文件**
   ```bash
   # 复制环境变量示例文件
   cp .env.example .env
   
   # 复制NapCat配置示例
   cp napcat_config_example.yml napcat_config.yml
   ```

2. **编辑配置文件**
   ```bash
   # 编辑环境变量配置
   vim .env
   ```
   
   修改以下配置：
   ```ini
   # NapCat WebSocket 服务配置
   NAPCAT_WS_URL=ws://localhost:6099/wsapi
   
   # 漫画下载路径
   MANGA_DOWNLOAD_PATH=/var/lib/JMBot/downloads

3. **创建数据目录**
   ```bash
   # 创建下载目录
   sudo mkdir -p /var/lib/JMBot/downloads
   sudo chown $USER:$USER /var/lib/JMBot/downloads
   ```

#### 四、系统服务配置（可选）

> **💡 重要提示**：系统服务配置是可选的，仅在以下情况下需要：
> - 需要在服务器上24小时运行机器人
> - 需要开机自动启动功能
> - 需要自动故障恢复和重启
> 
> **如果只是临时使用或测试，可以直接跳过此步骤，使用手动启动方式即可。**

1. **创建系统服务用户**
   ```bash
   # 创建专用用户
   sudo useradd -r -s /bin/false JMBot
   
   # 设置目录权限
   sudo chown -R JMBot:JMBot /opt/JMBot
   sudo chown -R JMBot:JMBot /var/lib/JMBot
   ```

2. **创建系统服务文件**
   ```bash
   # 创建服务文件
   sudo vim /etc/systemd/system/JMBot.service
   ```
   
   添加以下内容：
   ```ini
   [Unit]
   Description=JMBot QQ Robot
   After=network.target
   
   [Service]
   Type=simple
   User=JMBot
   WorkingDirectory=/opt/JMBot
   Environment=PATH=/opt/JMBot/venv/bin
   ExecStart=/opt/JMBot/venv/bin/python bot.py
   Restart=always
   RestartSec=10
   
   [Install]
   WantedBy=multi-user.target
   ```

3. **配置系统服务**
   ```bash
   # 重新加载系统服务
   sudo systemctl daemon-reload
   
   # 启动服务
   sudo systemctl start mangabot
   
   # 设置开机自启
   sudo systemctl enable mangabot
   
   # 查看服务状态
   sudo systemctl status mangabot
   ```

#### 五、配置 NapCat

1. **安装 NapCat**
   - 参考 NapCatQQ 文档安装 NapCat https://github.com/NapNeko/NapCatQQ
   - 配置 WebSocket 服务端与机器人配置匹配

### 🎯 使用方法

#### 系统服务管理
```bash
# 启动服务
sudo systemctl start JMBot

# 停止服务
sudo systemctl stop JMBot

# 重启服务
sudo systemctl restart JMBot

# 查看服务状态
sudo systemctl status JMBot

# 查看实时日志
sudo journalctl -u JMBot -f
```

#### QQ命令使用
- `漫画帮助` - 查看帮助信息
- `漫画下载 350234` - 下载漫画ID为350234的漫画
- `发送 350234` - 发送已下载的漫画文件

---

## 📱 Android 部署（使用 proot + Ubuntu）

### 📋 环境要求

- 📱 **Android 7.0+ 系统（推荐）**
- 💾 至少 4GB 可用存储空间（Ubuntu系统需要更多空间）
- 🐍 Python >= 3.7
- 🌐 稳定的网络连接

### 🚀 部署步骤

#### 一、安装 Termux 和 proot

1. **安装 Termux**
   - 从 F-Droid 或 Google Play 安装 Termux
   - 或者下载 Termux APK 文件手动安装

2. **配置 Termux 并安装 proot**
   ```bash
   # 更新包管理器
   pkg update && pkg upgrade
   
   # 安装 proot-distro（更简单的Ubuntu安装方式）
   pkg install proot-distro -y
   ```

#### 二、安装 Ubuntu 系统

1. **使用 proot-distro 安装 Ubuntu**
   ```bash
   # 安装 Ubuntu 系统
   proot-distro install ubuntu
   
   # 登录 Ubuntu 系统
   proot-distro login ubuntu
   ```

2. **配置 Ubuntu 系统**
   ```bash
   # 更新包管理器
   apt update && apt upgrade -y
   
   # 安装必要工具
   apt install sudo vim git python3-dev python3-venv build-essential screen curl python3-pip
   ```

#### 四、在 Ubuntu 中部署机器人

1. **获取项目文件**
   ```bash
   # 创建项目目录（简化目录结构）
   mkdir -p ~/JMBot
   cd ~/JMBot
   
   # 使用Git克隆项目
   git clone https://github.com/AAA-huan/JM-QQ-Bot.git .
   ```

2. **安装 Python 依赖**
   ```bash
   # 确认Python版本
   python3 --version

   # 安装项目依赖
   pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
   ```

3. **配置环境变量**
   ```bash
   # 复制配置文件
   cp .env.example .env
   
   # 编辑配置
   vim .env
   ```

   修改以下配置：
   ```ini
   # NapCat WebSocket 服务配置
   NAPCAT_WS_URL=ws://localhost:6099/wsapi
   
   # 漫画下载路径（使用相对路径，简化目录结构）
   MANGA_DOWNLOAD_PATH=./downloads
   ```

4. **创建数据目录**
   ```bash
   # 创建下载目录（在当前项目目录下）
   mkdir -p downloads
   chmod 755 downloads
   ```

#### 五、配置 NapCat

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
   - 配置完成后启动 NapCat

#### 六、启动机器人

1. **在 Ubuntu 环境中启动**
   ```bash
   # 进入项目目录
   cd /opt/JMBot
   
   # 启动机器人
   python3 bot.py

   # 停止机器人
   CTRL + C
   ```


### 🎯 使用方法

#### 启动和进入 Ubuntu 环境
```bash
# 登录 Ubuntu 系统
proot-distro login ubuntu

# 在Ubuntu中启动机器人
cd ~/JMBot && python3 bot.py
```

#### 进程管理
```bash
# 查看机器人进程
ps aux | grep python

# 停止机器人
pkill -f "python3 bot.py"

# 退出Ubuntu环境
exit
```

#### QQ命令使用
- `漫画帮助` - 查看帮助信息
- `漫画下载 [ID]` - 下载指定漫画
- `发送 [ID]` - 发送漫画文件

---

## ⚙️ 配置说明

### 环境变量配置

编辑 `.env` 文件进行配置：

```ini
# ======================
# NapCat 配置
# ======================
# WebSocket 服务地址
NAPCAT_WS_URL=ws://localhost:6099/wsapi

# ======================
# 下载配置
# ======================
# 漫画下载存储路径
MANGA_DOWNLOAD_PATH=./downloads

# ======================
# 安全配置
# ======================
# API访问令牌（建议设置）
TOKEN=your_secure_token_here

# ======================
# 日志配置
# ======================
# 日志级别：DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
```

### JMComic 下载配置

如需自定义下载参数，编辑 `option.yml`：

```yaml
# 下载线程数
thread_count: 5

# 下载重试次数
retry_count: 3

# 下载超时时间（秒）
timeout: 30

# 是否启用代理（如需）
proxy: null
```

---

## ❓ 常见问题解答

### Windows 环境问题

#### Q: 机器人启动后无响应？
A: 检查 NapCat 是否正常运行，确认 WebSocket 配置是否正确。

#### Q: 下载漫画失败？
A: 检查网络连接，确认漫画ID是否正确，查看错误日志。

#### Q: 如何找到漫画ID？
A: 在禁漫天堂网站浏览漫画时，URL中的数字即为漫画ID。

### Linux 环境问题

#### Q: 服务启动失败？
A: 检查系统日志：`sudo journalctl -u JMBot -n 50`

#### Q: 端口被占用？
A: 停止占用端口的进程或检查NapCat WebSocket端口配置。

### Android 环境问题

#### Q: Termux 中无法安装依赖？
A: 尝试使用国内镜像源：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`

#### Q: 存储空间不足？
A: 清理缓存或使用外部存储：`MANGA_DOWNLOAD_PATH=/sdcard/JMComicBot/downloads`

#### Q: 后台运行被杀死？
A: 使用 Termux 的 wakelock 功能或考虑使用 Termux:Boot。

---

## 🔧 故障排除

### 日志查看

- **Windows**: 查看命令行窗口输出
- **Linux**: `sudo journalctl -u JMBot -f`
- **Android**: Termux 终端输出

### 错误代码说明

- **WebSocket连接失败**: 检查 NapCat 状态和配置
- **下载失败**: 检查网络和漫画ID有效性
- **权限错误**: 检查文件和目录权限
- **存储空间不足**: 清理下载目录或调整存储路径

### 性能优化

1. **调整下载线程数**：在 `option.yml` 中修改 `thread_count`
2. **使用代理**：如有网络限制，配置代理服务器
3. **定期清理**：删除不再需要的漫画文件释放空间

---

## 📄 许可证

本项目仅供学习和研究使用。使用本工具时，请遵守相关法律法规。

## ⚠️ 免责声明

本项目仅作为技术学习和研究用途，作者不对任何不当使用本工具造成的后果负责。请用户自行承担使用风险，并确保遵守所在国家或地区的相关法律法规。