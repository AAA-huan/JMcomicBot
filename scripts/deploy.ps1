# ============================================================================
# JMComicBot 一键部署脚本（Windows PowerShell）
#
# 用法：
#   irm https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.ps1 | iex
# 或先下载后运行：
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
#
# 行为：
#   1. 检测 / 安装 git、Python>=3.12、uv
#   2. 克隆或更新项目到当前目录下的 JMcomicBot\ 子目录
#   3. 创建虚拟环境并 uv sync 同步依赖
#   4. 幂等复制 .env / option.yml（已存在则保留用户配置）
#   5. 交互式写入 .env 关键项（已配置的项跳过）
#   6. 创建 downloads / data / logs 运行时目录
#   7. 打印 NapCat 部署提示
#   8. 询问是否立即启动 bot
#
# 幂等：重复运行等同于"拉取最新代码 + 同步依赖"，不会覆盖已有配置。
# ============================================================================

# Strict mode + 中文输出
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# ============================ 全局配置 ============================
# 支持通过环境变量 JMBOT_REPO_URL 覆盖（便于使用镜像源或本地路径测试）
if ($env:JMBOT_REPO_URL) { $RepoUrl = $env:JMBOT_REPO_URL } else { $RepoUrl = 'https://github.com/AAA-huan/JMcomicBot.git' }
$ProjectDirName   = 'JMcomicBot'
$RequiredPyMajor  = 3
$RequiredPyMinor  = 12
$WsUrlPlaceholder = 'ws://localhost:port/qq'

# ============================ 日志函数 ============================
function Log-Info  ($msg) { Write-Host "[信息] $msg" -ForegroundColor Cyan }
function Log-Ok    ($msg) { Write-Host "[完成] $msg" -ForegroundColor Green }
function Log-Warn  ($msg) { Write-Host "[警告] $msg" -ForegroundColor Yellow }
function Log-Error($msg) { Write-Host "[错误] $msg" -ForegroundColor Red }
function Log-Step  ($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Blue }
function Die       ($msg) { Log-Error $msg; exit 1 }

# 交互输入：兼容 irm | iex 管道与无终端场景
# [Console]::In 可能在管道下不可用，故优先尝试，失败则退回标准 stdin
function Ask ([string]$Prompt, [string]$Default = '') {
    if ($Default) {
        $promptText = "$Prompt（默认：$Default）: "
    } else {
        $promptText = "$Prompt: "
    }
    Write-Host -NoNewline $promptText
    $line = $null
    try {
        $line = [Console]::ReadLine()
    } catch {
        # [Console]::In 不可用（管道模式），尝试从 $input 读取
        if ($input) {
            $line = ($input | Select-Object -First 1)
        }
    }
    if ([string]::IsNullOrWhiteSpace($line)) { return $Default }
    return $line.Trim()
}

# ============================ 工具函数 ============================

# 获取 .env 中某个 key 的值
function Get-Env ([string]$Key, [string]$File) {
    if (-not (Test-Path $File)) { return '' }
    $line = Get-Content $File -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^$Key=" } |
        Select-Object -First 1
    if (-not $line) { return '' }
    return ($line -replace "^$Key=", '')
}

# 设置 .env 中某个 key 的值（存在则替换整行，不存在则追加）
function Set-Env ([string]$Key, [string]$Value, [string]$File) {
    if (-not (Test-Path $File)) {
        "$Key=$Value" | Out-File -FilePath $File -Append -Encoding UTF8
        return
    }
    $lines = Get-Content $File -Encoding UTF8
    $found = $false
    $newLines = foreach ($l in $lines) {
        if ($l -match "^$Key=") {
            $found = $true
            "$Key=$Value"
        } else {
            $l
        }
    }
    if (-not $found) { $newLines += "$Key=$Value" }
    $newLines | Out-File -FilePath $File -Encoding UTF8
}

# ============================ 环境准备 ============================

function Ensure-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) {
        Log-Ok "git 已安装：$(& git --version)"
        return
    }
    Log-Info "未检测到 git，尝试通过 winget 安装..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    } else {
        Log-Error "未找到 winget，无法自动安装 git。"
        Log-Info "请前往 https://git-scm.com/downloads 下载并安装 Git（安装时勾选 'Add to PATH'）。"
        Die "请安装 git 后重新运行本脚本。"
    }
    # 刷新当前会话 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Die "git 安装失败，请手动安装后重试"
    }
    Log-Ok "git 安装完成：$(& git --version)"
}

function Find-Python {
    foreach ($cmd in @('python', 'python3', 'py')) {
        $g = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $g) { continue }
        $verOut = & $cmd -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>$null
        if (-not $verOut) { continue }
        $parts = $verOut.Trim() -split '\.'
        if ($parts.Count -lt 2) { continue }
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -gt $RequiredPyMajor -or
            ($major -eq $RequiredPyMajor -and $minor -ge $RequiredPyMinor)) {
            return $cmd
        }
    }
    return $null
}

function Ensure-Python {
    $py = Find-Python
    if ($py) {
        Log-Ok "Python 已满足要求：$(& $py --version 2>&1)"
        return
    }
    Log-Error "未找到 Python >= $RequiredPyMajor.$RequiredPyMinor。"
    Log-Info "请前往 https://www.python.org/downloads/ 下载并安装 Python $RequiredPyMajor.$RequiredPyMinor+。"
    Log-Info "安装时务必勾选 'Add Python to PATH'。"
    Die "请安装满足要求的 Python 后重新运行本脚本。"
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Log-Ok "uv 已安装：$(uv --version)"
        return
    }
    # astral 安装器默认路径
    $uvPath = Join-Path $HOME '.local\bin\uv.exe'
    if (Test-Path $uvPath) {
        $env:Path = (Join-Path $HOME '.local\bin') + ';' + $env:Path
        Log-Ok "uv 已安装：$(uv --version)"
        return
    }
    Log-Info "未检测到 uv，使用官方安装器安装..."
    & ([scriptblock]::Create((Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing).Content))
    $env:Path = (Join-Path $HOME '.local\bin') + ';' + $env:Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Die "uv 安装失败，请手动安装后重试"
    }
    Log-Ok "uv 安装完成：$(uv --version)"
}

# ============================ 项目获取 / 更新 ============================

function Clone-Or-Update {
    $repoDir = Join-Path (Get-Location) $ProjectDirName
    if (Test-Path (Join-Path $repoDir '.git')) {
        Log-Step "更新现有项目（git pull）"
        & git -C $repoDir pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Log-Warn "git pull 失败，可能存在本地改动或分叉，请手动处理 $ProjectDirName 目录。"
        }
    } else {
        Log-Step "克隆项目到 .\$ProjectDirName"
        if (Test-Path $repoDir) {
            Die ".\$ProjectDirName 已存在但不是 git 仓库，请手动处理后重试"
        }
        & git clone $RepoUrl $ProjectDirName
        if ($LASTEXITCODE -ne 0) { Die "git clone 失败" }
        Log-Ok "克隆完成"
    }
}

# ============================ Python 环境与依赖 ============================

function Setup-PythonEnv {
    Set-Location $ProjectDirName
    Log-Step "创建虚拟环境与同步依赖"
    uv venv
    if ($LASTEXITCODE -ne 0) { Die "uv venv 失败" }
    Log-Ok "虚拟环境就绪（.venv）"

    Log-Info "同步依赖（uv sync --no-dev），首次可能耗时较长..."
    uv sync --no-dev
    if ($LASTEXITCODE -ne 0) { Die "uv sync 失败" }
    Log-Ok "依赖同步完成"
}

# ============================ 配置文件 ============================

function Prepare-ConfigFiles {
    Log-Step "准备配置文件"

    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Log-Ok "已从 .env.example 生成 .env"
    } else {
        Log-Ok ".env 已存在，保留现有配置"
    }

    if (-not (Test-Path 'option.yml')) {
        Copy-Item 'option_example.yml' 'option.yml'
        Log-Ok "已从 option_example.yml 生成 option.yml"
    } else {
        Log-Ok "option.yml 已存在，保留现有配置"
    }

    foreach ($d in @('downloads', 'data', 'logs')) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
    }
    Log-Ok "运行时目录就绪（downloads / data / logs）"
}

function Interactive-Config {
    Log-Step "配置关键项（已配置的项将跳过）"

    # 1. NAPCAT_WS_URL —— 必填
    $curWs = Get-Env 'NAPCAT_WS_URL' '.env'
    if ([string]::IsNullOrWhiteSpace($curWs) -or $curWs -eq $WsUrlPlaceholder) {
        Write-Host "NapCat WebSocket 地址是 bot 与 NapCat 通信的关键。"
        Write-Host "格式形如 ws://主机:端口/路径，例如 ws://localhost:3001/qq"
        while ($true) {
            $ws = Ask "请输入 NAPCAT_WS_URL" ""
            if ([string]::IsNullOrWhiteSpace($ws)) {
                Log-Warn "NAPCAT_WS_URL 不能为空，请重新输入"
                continue
            }
            if ($ws -match '^wss?://.+') { break }
            Log-Warn "格式应为 ws://host:port/path，请重新输入"
        }
        Set-Env 'NAPCAT_WS_URL' $ws '.env'
        Log-Ok "NAPCAT_WS_URL 已写入"
    } else {
        Log-Ok "NAPCAT_WS_URL 已配置（$curWs），跳过"
    }

    # 2. NAPCAT_TOKEN —— 可选，当前值作为默认（回车即保留，便于幂等）
    $curToken = Get-Env 'NAPCAT_TOKEN' '.env'
    if ($curToken -eq '""') { $curToken = '' }
    $token = Ask "请输入 NAPCAT_TOKEN（NapCat 鉴权 token，可留空）" $curToken
    $token = $token.Trim('"')
    Set-Env 'NAPCAT_TOKEN' $token '.env'
    Log-Ok "NAPCAT_TOKEN 已写入"

    # 3. LOW_MEMORY_MODE —— 当前值作为默认，每次都确认（回车即保留）
    $curLm = Get-Env 'LOW_MEMORY_MODE' '.env'
    if ([string]::IsNullOrWhiteSpace($curLm)) { $curLm = 'false' }
    Write-Host "低内存模式：开启后下载完立即发送并自动删除，适合存储/内存受限环境。"
    $lm = Ask "是否开启低内存模式？(true/false)" $curLm
    switch -Regex ($lm.ToLower()) {
        '^(true|yes|y)$' { $lm = 'true' }
        default          { $lm = 'false' }
    }
    Set-Env 'LOW_MEMORY_MODE' $lm '.env'
    Log-Ok "LOW_MEMORY_MODE=$lm"

    # 4. WebUI 是否启用 —— 当前值作为默认，每次都确认（回车即保留）
    $curWebui = Get-Env 'WEBUI_ENABLED' '.env'
    if ([string]::IsNullOrWhiteSpace($curWebui)) { $curWebui = 'true' }
    Write-Host "WebUI 控制台：可在浏览器管理漫画库与任务，默认监听本机 127.0.0.1:7999。"
    $webui = Ask "是否启用 WebUI？(true/false)" $curWebui
    switch -Regex ($webui.ToLower()) {
        '^(false|no|n)$' { $webui = 'false' }
        default          { $webui = 'true' }
    }
    Set-Env 'WEBUI_ENABLED' $webui '.env'
    Log-Ok "WEBUI_ENABLED=$webui"
}

# ============================ NapCat 部署提示 ============================

function Print-NapcatHint {
    @'

============================ NapCat 部署提醒 ============================
bot 本身无法独立工作，需要配合 NapCat（OneBot11 协议端）才能与 QQ 通信。

两种安装方式：
  - Docker 镜像：mlikiowa/napcat-docker
      文档：https://github.com/NapNeko/NapCatQQ
  - Shell 原生版（适合服务器 / Termux）：
      curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
      sudo bash napcat.sh --docker n --cli y

关键配置要点（踩坑高频区）：
  1. WebSocket 服务端 host 改为 0.0.0.0（容器化必须，否则宿主机连不上）
  2. token 与 .env 的 NAPCAT_TOKEN 必须一致（如启用了鉴权）
  3. Docker 部署时，把 downloads 目录同路径 bind mount 进容器：
       -v /绝对路径/JMcomicBot/downloads:/绝对路径/JMcomicBot/downloads
     否则 NapCat 找不到 bot 发送的文件，报 "识别URL失败"
  4. 在 NapCat WebUI 的 autoLoginAccount 填入 QQ 号，重启免扫码

详细排障可参考项目根目录的 napcat-docker-部署总结.md（如有）。
========================================================================
'@
}

# ============================ 启动询问 ============================

function Ask-Launch {
    Write-Host ""
    $ans = Ask "是否立即启动 bot？(y/n)" "n"
    switch -Regex ($ans.ToLower()) {
        '^(y|yes)$' {
            Log-Info "启动前请确认 NapCat 已就绪并完成 QQ 登录。"
            Log-Step "启动 bot（uv run python main.py，Ctrl+C 退出）"
            & uv run python main.py
        }
        default {
            Log-Ok "部署完成。后续启动命令："
            Write-Host "  cd $(Get-Location); uv run python main.py"
        }
    }
}

# ============================ 主流程 ============================

function Main {
    Log-Step "JMComicBot 一键部署"
    Log-Info "工作目录：$(Get-Location)"

    Ensure-Git
    Ensure-Python
    Ensure-Uv

    Clone-Or-Update
    Setup-PythonEnv

    Prepare-ConfigFiles
    Interactive-Config

    Print-NapcatHint
    Ask-Launch
}

Main
