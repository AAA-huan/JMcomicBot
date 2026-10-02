# 🎯 JMComic QQ 机器人

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Android-lightgrey.svg)](docs/deployment/windows.md)


</div>

**平台状态说明：**
- ✅ **Windows系统**：已稳定可用　[部署教程](docs/deployment/windows.md)
- ✅ **Linux系统**：  已稳定可用　[部署教程](docs/deployment/linux.md)
- ✅ **Android系统**：已稳定可用　[部署教程](docs/deployment/android.md)

> **推荐**：作者推荐使用安卓部署，同为Linux系统不会像Windows一样容易被ban掉而且手机在身边也方便。

> ✨ **智能漫画下载助手** - 基于 NapCat 的高性能 QQ 机器人，专为漫画爱好者设计

一个功能强大的 QQ 机器人，能够帮助用户轻松下载、管理和分享禁漫天堂的漫画内容，支持多平台部署。


## 🎯 核心功能
- 📥 **智能下载** - 通过漫画ID一键下载漫画内容
- 📤 **便捷发送** - 将已下载的漫画文件直接发送到QQ聊天
- 🔍 **状态监控** - 可查询下载进度和任务状态
- 📚 **内容管理** - 查看和管理已下载的漫画列表
- 📄 **格式转换** - 自动将图片转换为PDF格式，便于阅读
- 📱 **跨平台** - 支持Windows、Linux、Android
- 🌐 **WebUI 控制台** - 可选启用，在手机/电脑浏览器里管理漫画库、在线阅读、下载任务、权限与配置
- 🗄️ **数据库维护** - 版本化迁移、任务与审计、备份 / 扫描 / 修复 / 文件校验


## 🚀 快速开始

1. 按上方平台链接完成部署（Python 3.12+、依赖安装与 NapCat 配置）；
2. 准备配置：`cp .env.example .env`，按需修改 NapCat 地址、端口等；
3. 启动机器人：`uv run python main.py`

> 详细安装步骤见对应部署文档，其余内容见下方文档索引。

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [命令大全](docs/commands.md) | 全部 QQ 指令与别名、批量操作规则 |
| [WebUI 控制台](docs/webui.md) | 访问与首次设置、在线阅读与进度、局域网访问、忘记密码恢复 |
| [维护脚本](docs/maintenance.md) | 备份 / 扫描 / 修复 / 文件校验 / WebUI 管理员重置脚本与数据保留策略 |
| [Windows 部署](docs/deployment/windows.md) | Windows 安装、配置与常驻 |
| [Linux 部署](docs/deployment/linux.md) | Linux 安装、配置与系统服务 |
| [Android 部署](docs/deployment/android.md) | Termux + Ubuntu（proot）部署与常驻 |

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
