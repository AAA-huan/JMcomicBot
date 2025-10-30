@echo off

:: JMComic下载机器人启动脚本
:: 基于NapCat框架

:: 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误：未找到Python。请先安装Python并将其添加到环境变量中。
    pause
    exit /b 1
)

:: 安装或更新依赖
echo 正在安装/更新依赖...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo 警告：依赖安装失败。请检查网络连接或手动运行 pip install -r requirements.txt
)

:: 创建下载目录
if not exist downloads mkdir downloads

:: 显示启动信息
echo ============================
echo     JMComic下载机器人      
echo     基于NapCat框架
echo ============================

echo 正在启动机器人...
python bot.py

pause