# 🎯 JMComic QQ 机器人

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Android-lightgrey.svg)](README.md)


</div>

**平台状态说明：**
- ✅ **Windows系统**：已稳定可用    [部署教程](#windows-部署)
- ✅ **Linux系统**：  已稳定可用    [部署教程](#linux-部署)
- ✅ **Android系统**：已稳定可用    [部署教程](#android-部署)

> **推荐**：作者推荐使用安卓部署，同为Linux系统不会像Windows一样容易被ban掉而且手机在身边也方便。

> ✨ **智能漫画下载助手** - 基于 NapCat 的高性能 QQ 机器人，专为漫画爱好者设计

一个功能强大的 QQ 机器人，能够帮助用户轻松下载、管理和分享禁漫天堂的漫画内容，支持多平台部署。


### 🎯 核心功能
- 📥 **智能下载** - 通过漫画ID一键下载漫画内容
- 📤 **便捷发送** - 将已下载的漫画文件直接发送到QQ聊天
- 🔍 **状态监控** - 可查询下载进度和任务状态
- 📚 **内容管理** - 查看和管理已下载的漫画列表
- 📄 **格式转换** - 自动将图片转换为PDF格式，便于阅读
- 📱 **跨平台** - 支持Windows、Linux、Android

### 🔧 命令大全

- `漫画帮助` - 查看帮助信息（群聊中请先@机器人；别名：帮助、帮助漫画）
- `漫画下载 350234` - 下载指定ID的漫画,批量操作用逗号隔开（别名：下载、下载漫画）
- `发送漫画 350234` - 发送已下载的指定ID的漫画文件,批量操作用逗号隔开,--all可发送全部（别名：发送、漫画发送）
- `漫画列表` - 查看已下载漫画列表（别名：列表、列表漫画）
- `查询漫画 350234` - 查询指定ID的漫画是否已下载
- `漫画版本` - 查看当前机器人的版本信息
- `下载进度` - 查看当前漫画下载队列的状况
- `发送进度` - 查看当前漫画发送队列的状况
- `测试id` - 查看当前机器人的id(QQ号)
- `测试文件` - 发送一个txt文件测试当前是否能发送文件
- `删除漫画` - 删除指定ID的漫画文件
- `重发重发` - 断线后确认重发未送达的漫画文件
- `你好` / `hi` / `hello` / `在吗` - 打招呼

- `注` - 批量操作支持中文/英文逗号、句号作为分隔符，例如 `350234,350235` 或 `350234，350235`
---

## 感谢以下两个项目的贡献

- [NapCat](https://github.com/NapNeko/NapCat) - 一个基于 NTQQ 协议的聊天机器人框架
- [JMcomic](https://github.com/JMasann/JMComic) - 提供Python API访问禁漫天堂，同时支持网页端和移动端
---

## ⚠️ 免责声明

本项目仅作为技术学习和研究用途，作者不对任何不当使用本工具造成的后果负责。请用户自行承担使用风险，并确保遵守所在国家或地区的相关法律法规。

**重要提示：**
- 请尊重版权，仅下载和使用您拥有合法权限的内容
- 请勿将本项目用于商业用途
- 请遵守您所在国家或地区的法律法规
- 使用本工具产生的任何后果由使用者自行承担

---

## Windows 部署

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
git clone https://github.com/AAA-huan/JMcomicBot.git .
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
# 使用 pip 安装依赖
pip install -r requirements.txt  --upgrade
```

#### 🔧 第三步：配置机器人

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

#### 第四步：配置 NapCat

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

#### 第五步：启动机器人

   ```bash
   # 进入项目目录
   # 右键点击项目文件夹，选择在powershell中打开
   # 启动机器人
   python main.py

   # 停止机器人
   Ctrl+C
   ```

#### 🔄 六、常态化启动

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

---

## Linux 部署

### 📋 环境要求

- 🐍 Python >= 3.7
- 🐧 **Ubuntu 18.04 或更高版本（推荐）**
- 💾 至少 4GB 可用存储空间
- 🌐 稳定的网络连接
- 🔧 系统管理员权限

### 🚀 部署步骤

#### 第一步：获取必要的文件

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

#### 第二步：环境配置

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
   pip install -r requirements.txt --upgrade
   ```

#### 第三步：配置机器人

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


#### 第四步：配置 NapCat

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

#### 第五步：使用方法

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
python main.py

# 停止机器人
Ctrl+C
```

---

## Android 部署

### 📋 环境要求

- 📱 **Android 7.0+ 系统（推荐）**
- 💾 至少 4GB 可用存储空间（Ubuntu系统需要更多空间）
- 🐍 Python >= 3.7
- 🌐 稳定的网络连接

### 🚀 部署步骤

#### 第一步：安装 Termux 和 proot

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

#### 第二步：安装 Ubuntu 系统

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

#### 第三步：在 Ubuntu 中部署机器人

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
   pip3 install -r requirements.txt --upgrade
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

#### 第四步：配置 NapCat

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

#### 第五步：启动机器人

1. **在 Ubuntu 环境中启动**
   ```bash
   # 进入项目目录
   cd ~/JMBot

   # 启动机器人
   python3 main.py

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
python3 main.py

# 停止机器人
Ctrl+C
```

#### 进程管理
```bash
# 查看机器人进程
ps aux | grep python

# 停止机器人
pkill -f "python3 main.py"

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

---
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