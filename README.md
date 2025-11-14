# 🎯 JMComic QQ 机器人

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Android-lightgrey.svg)](README.md)
[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](README.md)

</div>

**平台状态说明：**
- ✅ **Windows系统**：已稳定可用
- 🧪 **Linux系统**：正在测试中，暂不推荐生产环境使用
- 🧪 **Android系统**：正在测试中，暂不推荐生产环境使用

> **注意**：Linux和Android平台的部署文档目前为测试版本，可能存在兼容性问题，请等待稳定版本发布后再进行部署。

> ✨ **智能漫画下载助手** - 基于 NapCat 的高性能 QQ 机器人，专为漫画爱好者设计

一个功能强大的 QQ 机器人，能够帮助用户轻松下载、管理和分享禁漫天堂的漫画内容。支持多平台部署，提供直观的交互界面和丰富的功能特性。


### 🎯 核心功能
- 📥 **智能下载** - 通过漫画ID一键下载漫画内容
- 📤 **便捷发送** - 将已下载的漫画文件直接发送到QQ聊天
- 🔍 **状态监控** - 可查询下载进度和任务状态
- 📚 **内容管理** - 查看和管理已下载的漫画列表
- 📄 **格式转换** - 自动将图片转换为PDF格式，便于阅读
- 📱 **跨平台** - 支持Windows、Linux、Android

---

## 📦 Windows 部署

### 📋 环境要求

- 🪟 **Windows 10 或更高版本**
- 🐍 **Python >= 3.7**（推荐 Python 3.8+）
- 💾 **至少 4GB 可用存储空间**（根据下载漫画数量调整）
- 🌐 **稳定的网络连接**（支持代理配置）

### 🚀 部署步骤

#### 📥 第一步：获取项目文件

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
git clone https://github.com/AAA-huan/JM-QQ-Bot.git .
# 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
```

#### ⚙️ 第二步：环境配置

##### 1. 安装 Python 环境
- 访问 [Python官网](https://www.python.org/downloads/) 下载最新版Python
- 安装时务必勾选「Add Python to PATH」选项
- 推荐安装 Python 3.8 或更高版本

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
# 使用 pip 安装依赖（使用阿里云镜像加速）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
```

#### 🔧 第三步：配置机器人

##### 1. 复制配置文件
```bash
# 复制环境变量示例文件
copy .env.example .env

# 复制NapCat配置示例
copy napcat_config_example.yml napcat_config.yml

# 复制漫画下载配置示例
copy option_example.yml option.yml
```

##### 2. 编辑配置文件
打开 `.env` 文件，修改以下关键配置：

```ini
# ======================
# NapCat WebSocket 服务配置
# ======================
# WebSocket 服务地址 - 连接NapCat WebSocket服务的URL
# 把port替换为你实际的NapCat WebSocket服务端口
NAPCAT_WS_URL=ws://localhost:port/qq

# ======================
# 下载配置
# ======================
# 漫画下载存储路径 - 漫画文件下载的存储目录
MANGA_DOWNLOAD_PATH=./downloads

# ======================
# 安全配置
# ======================
# WebSocket服务令牌，与NapCat配置中的两个位置保持一致：
# - WebSocket服务配置部分的`token`字段
# - 中间件配置部分的`access-token`字段
# 
# 简化配置：只需设置NAPCAT_TOKEN一个字段即可
# 系统会自动将token添加到WebSocket连接URL中，无需手动添加
NAPCAT_TOKEN=""

# 为兼容原配置保留的令牌字段（优先级低于NAPCAT_TOKEN）
# 如果NAPCAT_TOKEN未设置，系统会尝试使用此值
ACCESS_TOKEN=
```

#### 四、配置 napcat_config.yml

打开`napcat_config.yml`文件进行配置


1. **配置 WebSocket 服务**
   ```yaml
   # WebSocket 服务配置
     - type: websocket-server
       # 监听地址（通常保持默认即可）
       host: 0.0.0.0
       # 监听端口（确保与.env文件中的NAPCAT_WS_URL端口一致）
       port: 8080
       # 路径（必须设置为/qq，与.env文件中的NAPCAT_WS_URL路径一致）
       path: /qq
       # 是否启用访问令牌（用于认证）
       # 此token需要与.env文件中的NAPCAT_TOKEN保持一致
       # 留空表示不启用Token验证
       token: "your_secure_token_here"
   ```

2. **配置中间件的访问令牌**
   ```yaml
   # 默认中间件配置
   default-middlewares &default:
     # 与.env文件中的NAPCAT_TOKEN或ACCESS_TOKEN保持一致
     # 留空表示不启用Token验证
     access-token: 'your_secure_token_here'
   ```

3. **重要配置说明**：
   - **端口一致性**：确保`port`值与`.env`文件中`NAPCAT_WS_URL`的端口部分一致
   - **路径设置**：`path`必须设置为`/qq`，这是机器人正常工作的必要条件
   - **Token一致性**：如果启用token验证，必须确保以下三个位置的token值完全相同：
     * `napcat_config.yml`中的WebSocket服务`token`字段
     * `napcat_config.yml`中的中间件`access-token`字段
     * `.env`文件中的`NAPCAT_TOKEN`或`ACCESS_TOKEN`字段
   - **禁用token验证**：如果不需要身份验证，请将所有token字段都留空（""或''）

#### 五、配置 NapCat

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

#### 六、启动机器人

   ```bash
   # 进入项目目录
   cd JMBot
   
   # 启动机器人
   python bot.py

   # 停止机器人
   Ctrl+C
   ```

#### 🔄 七、常态化启动

##### 1. 启动 NapCat 服务
- 确保 NapCat 已正确安装并配置
- 启动 NapCat 服务

##### 2. 激活虚拟环境并启动机器人
```bash
# 进入项目目录
cd JMBot

# 激活虚拟环境
venv\Scripts\Activate

# 启动机器人
python bot.py
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
   git clone https://github.com/AAA-huan/JM-QQ-Bot.git .
   # 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
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
   # NapCat WebSocket 服务配置
   # 把port替换为你实际的NapCat WebSocket服务端口
   # 系统会自动将token添加到连接URL中，无需手动添加
   NAPCAT_WS_URL=ws://localhost:port/qq
   
   # 漫画下载路径
   MANGA_DOWNLOAD_PATH=/var/lib/JMBot/downloads
   
   # 安全配置
   # 简化配置：只需设置NAPCAT_TOKEN一个字段即可
   NAPCAT_TOKEN=""
   ```

   **配置NapCat配置文件：**
   ```bash
   # 使用编辑器打开配置文件
   vim napcat_config.yml
   ```

   修改以下配置内容：
   
   ```yaml
   # WebSocket 服务配置
     - type: websocket-server
       # 监听地址（通常保持默认即可）
       host: 0.0.0.0
       # 监听端口（确保与.env文件中的NAPCAT_WS_URL端口一致）
       port: 8080
       # 路径（必须设置为/qq，与.env文件中的NAPCAT_WS_URL路径一致）
       path: /qq
       # 是否启用访问令牌（用于认证）
       # 此token需要与.env文件中的NAPCAT_TOKEN保持一致
       token: "your_secure_token_here"

   # 默认中间件配置
   default-middlewares &default:
     # 与.env文件中的NAPCAT_TOKEN或ACCESS_TOKEN保持一致
     access-token: 'your_secure_token_here'
   ```

   **重要配置说明**：
   - **端口一致性**：确保`port`值与`.env`文件中`NAPCAT_WS_URL`的端口部分一致
   - **路径设置**：`path`必须设置为`/qq`，这是机器人正常工作的必要条件
   - **Token一致性**：如果启用token验证，必须确保以下三个位置的token值完全相同：
     * `napcat_config.yml`中的WebSocket服务`token`字段
     * `napcat_config.yml`中的中间件`access-token`字段
     * `.env`文件中的`NAPCAT_TOKEN`或`ACCESS_TOKEN`字段
   - **禁用token验证**：如果不需要身份验证，请将所有token字段都留空（""或''）

   修改完成后，保存文件并退出编辑器。

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
sudo systemctl start JMBot

#### 设置开机自启
sudo systemctl enable JMBot

##### 查看服务状态
sudo systemctl status JMBot
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

#### 🔄 启动机器人

##### 1. 启动 NapCat 服务
- 确保 NapCat 已正确安装并配置
- 启动 NapCat 服务（具体步骤参考 NapCat 官方文档）

##### 2. 启动机器人
```bash
# 进入项目目录
cd ~/JMBot

# 激活虚拟环境
source venv/bin/activate

# 启动机器人
python bot.py

# 停止机器人
Ctrl+C
```

#### QQ命令使用
- `漫画帮助` - 查看帮助信息
- `漫画下载 350234` - 下载指定ID的漫画
- `发送 350234` - 发送已下载的漫画文件
- `查询已下载漫画` - 查看已下载漫画列表

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
   - 从 [F-Droid](https://f-droid.org/packages/com.termux/) 或 Google Play 安装 Termux
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

#### 三、在 Ubuntu 中部署机器人

1. **获取项目文件**
   ```bash
   # 切换到用户主目录
   cd ~

   # 创建项目目录
   mkdir JMBot
   cd ~/JMBot
   
   # 使用Git克隆项目
   git clone https://github.com/AAA-huan/JM-QQ-Bot.git .
   # 注意：使用.参数表示将代码克隆到当前JMBot目录，不会创建额外的子目录
   ```

2. **创建虚拟环境**
   ```bash
   # 创建虚拟环境
   python3 -m venv venv

   # 激活虚拟环境
   source venv/bin/activate

   # 验证虚拟环境是否激活（应该显示venv前缀）
   which python3
   ```

3. **安装 Python 依赖**
   ```bash
   # 安装项目依赖
   pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
   ```

4. **配置环境变量**
   ```bash
   # 复制漫画下载配置
   cp option_example.yml option.yml

   # 复制配置文件
   cp .env.example .env
   
   # 编辑配置
   vim .env
   ```

   修改以下配置：
   ```ini
   # NapCat WebSocket 服务配置
   # 把port替换为你实际的NapCat WebSocket服务端口
   # 系统会自动将token添加到连接URL中，无需手动添加
   NAPCAT_WS_URL=ws://localhost:port/qq
   
   # 漫画下载路径（使用相对路径，简化目录结构）
   MANGA_DOWNLOAD_PATH=./downloads
   
   # 安全配置
   # 简化配置：只需设置NAPCAT_TOKEN一个字段即可
   NAPCAT_TOKEN=""
   ```

      **配置NapCat配置文件：**
   ```bash
   # 复制NapCat配置示例
   cp napcat_config_example.yml napcat_config.yml
    
   # 使用编辑器打开配置文件
   vim napcat_config.yml
   ```

y   ```ini
   确保以下配置正确：
   - `port`: WebSocket服务端口与.env文件中的端口保持一致
   - `token`和`access-token`: 与.env文件中的NAPCAT_TOKEN保持一致

   修改完成后，保存文件并退出编辑器。
   ```

5. **创建数据目录**
   ```bash
   # 创建下载目录（在当前项目目录下）
   mkdir -p downloads
   chmod 755 downloads
   ```

#### 四、配置 NapCat

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

#### 五、启动机器人

1. **在 Ubuntu 环境中启动**
   ```bash
   # 进入项目目录
   cd ~/JMBot

   # 启动机器人
   python3 bot.py

   # 停止机器人
   Ctrl+C
   ```

#### 🔄 六、常态化启动机器人

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

# 激活虚拟环境
source venv/bin/activate

# 启动机器人
python3 bot.py

# 停止机器人
Ctrl+C
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
- `漫画下载 350234` - 下载指定ID的漫画
- `发送 350234` - 发送已下载的漫画文件
- `查询已下载漫画` - 查看已下载漫画列表

---

## ❓ 常见问题解答

### 🚨 启动与连接问题

#### 1. 机器人无法启动
**问题描述：** 启动机器人时出现错误或无法连接
**解决方案：**
- 检查 NapCat 是否正常运行
- 确认 `.env` 文件中的 `NAPCAT_WS_URL` 配置正确
- 检查防火墙设置，确保端口 `port` 未被阻止
- 查看日志文件获取详细错误信息

#### 2. WebSocket 连接失败
**问题描述：** 无法连接到 NapCat WebSocket 服务
**解决方案：**
- 确认 NapCat 服务已启动并监听正确端口
- 检查 `NAPCAT_WS_URL` 格式是否正确（ws://localhost:port/qq）
- 验证网络连接和防火墙设置
- 如果启用了token验证，请确保.env文件中的`NAPCAT_TOKEN`与NapCat配置中的token和access-token字段值完全一致
- 检查WebSocket路径是否正确设置为`/qq`

### 📥 下载相关问题

#### 3. 漫画下载失败
**问题描述：** 下载漫画时出现错误或下载中断
**解决方案：**
- 检查网络连接是否稳定
- 确认下载路径 `MANGA_DOWNLOAD_PATH` 有写入权限
- 检查磁盘空间是否充足
- 尝试调整 `thread_count` 参数（降低并发数）

#### 4. 下载速度过慢
**问题描述：** 下载速度不理想或频繁中断
**解决方案：**
- 调整 `thread_count` 增加并发下载数
- 配置代理服务器提高连接稳定性
- 检查网络带宽和服务器状态

### 💬 消息与通信问题

#### 5. 消息发送失败
**问题描述：** 机器人无法发送消息到QQ
**解决方案：**
- 确认 NapCat 与QQ客户端的连接正常
- 检查机器人是否被QQ群或好友屏蔽
- 查看 NapCat 日志确认消息发送状态

#### 6. 命令无响应
**问题描述：** 发送命令后机器人无反应
**解决方案：**
- 确认命令格式正确（如：`下载漫画 漫画ID`）
- 检查机器人是否在线且正常运行
- 查看日志文件排查错误信息

### ⚡ 性能与优化

#### 7. 性能优化建议
**问题描述：** 机器人运行缓慢或占用资源过高
**解决方案：**
- 调整 `thread_count` 参数控制并发下载数
- 设置合理的 `timeout` 值避免长时间等待
- 定期清理下载目录释放磁盘空间
- 考虑使用代理服务器提高下载稳定性

#### 8. 内存占用过高
**问题描述：** 机器人占用过多系统内存
**解决方案：**
- 限制同时下载的漫画数量
- 定期重启机器人释放内存
- 监控日志文件排查内存泄漏

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

### 如何贡献

1. **报告问题**
   - 在GitHub Issues中描述您遇到的问题
   - 提供详细的错误信息和复现步骤

2. **功能建议**
   - 提出新的功能想法或改进建议
   - 描述使用场景和预期效果

## 📄 许可证

本项目基于 MIT 许可证开源发布。

```
MIT License

Copyright (c) 2024 AAA-huan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ⚠️ 免责声明

本项目仅作为技术学习和研究用途，作者不对任何不当使用本工具造成的后果负责。请用户自行承担使用风险，并确保遵守所在国家或地区的相关法律法规。

**重要提示：**
- 请尊重版权，仅下载和使用您拥有合法权限的内容
- 请勿将本项目用于商业用途
- 请遵守您所在国家或地区的法律法规
- 使用本工具产生的任何后果由使用者自行承担