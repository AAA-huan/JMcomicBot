# ============================================================================
# JMComicBot 一键部署脚本（Windows PowerShell）
#
# 用法：
#   irm https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.ps1 | iex
# 或先下载后运行：
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
#
# 行为：
#   1. 检查 Python>=3.12，检测 / 安装 git、uv
#   2. 克隆或更新项目到当前目录下的 JMcomicBot\ 子目录
#   3. 创建虚拟环境并 uv sync 同步依赖
#   4. 幂等复制 .env / option.yml（已存在则保留用户配置）
#   5. 校验 NapCat 地址并引导配置关键项（有效地址保留，其他项回车保留）
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

# ============================ 日志函数 ============================
function Log-Info  ($msg) { Write-Host "[信息] $msg" -ForegroundColor Cyan }
function Log-Ok    ($msg) { Write-Host "[完成] $msg" -ForegroundColor Green }
function Log-Warn  ($msg) { Write-Host "[警告] $msg" -ForegroundColor Yellow }
function Log-Error($msg) { Write-Host "[错误] $msg" -ForegroundColor Red }
function Log-Step  ($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Blue }
function Die       ($msg) { Log-Error $msg; exit 1 }

# 交互输入：兼容 irm | iex 和标准输入；EOF 与用户回车必须区分。
function Ask ([string]$Prompt, [string]$Default = '') {
    if ($Default) {
        $promptText = "${Prompt}（默认：${Default}）: "
    } else {
        $promptText = "${Prompt}: "
    }
    Write-Host -NoNewline $promptText
    $line = $null
    try {
        $line = [Console]::ReadLine()
    } catch {
        throw "无法读取终端输入，请在可交互终端运行脚本：$($_.Exception.Message)"
    }
    if ($null -eq $line) { throw '输入已结束，部署中止。请在可交互终端重新运行脚本。' }
    if ([string]::IsNullOrWhiteSpace($line)) { return $Default }
    return $line.Trim()
}

# ============================ 工具函数 ============================

# 获取 .env 中某个 key 的值
function Get-Env ([string]$Key, [string]$File) {
    if (-not (Test-Path $File)) { return '' }
    $line = Get-Content $File -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$Key\s*=" } |
        Select-Object -First 1
    if (-not $line) { return '' }
    $value = ($line -replace "^\s*$Key\s*=", '').Trim()
    # 引号内的 # 属于值；只去除引号外或未加引号值的行尾注释。
    if ($value -match '^"([^"]*)"\s*(?:#.*)?$' -or $value -match "^'([^']*)'\s*(?:#.*)?$") {
        return $Matches[1]
    }
    return ($value -replace '\s+#.*$', '').Trim()
}

# 设置 .env 中某个 key 的值（存在则替换整行，不存在则追加）
function Set-Env ([string]$Key, [string]$Value, [string]$File) {
    $lines = if (Test-Path $File) { @(Get-Content $File -Encoding UTF8) } else { @() }
    $found = $false
    $newLines = @(foreach ($l in $lines) {
        if ($l -match "^\s*$Key\s*=") {
            $found = $true
            "$Key=$Value"
        } else {
            $l
        }
    })
    if (-not $found) { $newLines += "$Key=$Value" }
    # Windows PowerShell 5.1 的 Out-File UTF8 会写 BOM，导致 Python dotenv
    # 可能无法识别首行配置；配置文件统一使用无 BOM 的 UTF-8。
    $filePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($File)
    [IO.File]::WriteAllLines($filePath, [string[]]$newLines, [Text.UTF8Encoding]::new($false))
}

# 纯端口只适用于同机部署，.env 中始终保存完整 WebSocket 地址。
# 非法值返回空字符串，交互流程会明确要求重新输入。
function Normalize-WsUrl ([string]$Value) {
    $value = $Value.Trim()
    if ($value -match '^[0-9]+$') {
        $port = 0
        if ($value.Length -gt 5 -or -not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            return ''
        }
        return "ws://localhost:${port}/qq"
    }
    $uri = $null
    if ($value -match '\s' -or -not [Uri]::TryCreate($value, [UriKind]::Absolute, [ref]$uri)) { return '' }
    if ($uri.Scheme -notin @('ws', 'wss') -or -not $uri.Host -or $uri.Port -eq 0 -or $uri.Fragment) { return '' }
    # 空端口不是合法的显式端口，避免 Uri 自动替换为默认值。
    if ($uri.Authority.EndsWith(':') -or $value -match '^wss?://[^/?#]*:(?:[/?#]|$)') { return '' }
    return $value
}

function Ask-Boolean ([string]$Prompt, [string]$Default) {
    while ($true) {
        $value = Ask "$Prompt (true/false)" $Default
        switch -Regex ($value.ToLower()) {
            '^(true|yes|y|1|on)$' { return 'true' }
            '^(false|no|n|0|off)$' { return 'false' }
            default { Log-Warn '请输入 true 或 false。' }
        }
    }
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

# ============================ uv 安装（三源顺序 fallback） ============================

# uv 安装候选源（按优先级）：
#   1. astral.sh 官方安装器：最完整，自动检测平台、写入 ~/.local/bin 与 shell 配置
#   2. GitHub Release 二进制直连：releases/latest/download/uv-<平台>.zip
#   3. ghproxy 镜像 release：对 github.com 做代理，国内 github 不通时使用
# 按顺序尝试，第一个成功即返回；全部失败则报错并给出手动安装指引（不静默兜底）

# 安装后验证：把 ~/.local/bin 加入 PATH 并确认 uv 可用
function Verify-UvAfterInstall {
    $env:Path = (Join-Path $HOME '.local\bin') + ';' + $env:Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Log-Warn "uv 安装后仍不在 PATH 中"
        return $false
    }
    Log-Ok "uv 安装完成：$(uv --version)"
    return $true
}

# 源1：astral.sh 官方安装器（最完整）
function Install-UvFromAstral {
    Log-Info "尝试源1：astral.sh 官方安装器"
    try {
        $resp = Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing -TimeoutSec 30
        & ([scriptblock]::Create($resp.Content))
        return $true
    } catch {
        Log-Warn "源1（astral.sh 官方安装器）失败：$($_.Exception.Message)"
        return $false
    }
}

# 源2/3：GitHub Release 二进制（prefix 为空=直连，prefix=镜像前缀=走镜像）
function Install-UvFromRelease ([string]$Prefix) {
    $desc = if ($Prefix) { $Prefix } else { 'GitHub 直连' }
    Log-Info "尝试源：GitHub Release 二进制（${desc}）"

    # 平台资产映射：默认 x64，ARM64 设备用 aarch64
    $asset = 'uv-x86_64-pc-windows-msvc.zip'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        $asset = 'uv-aarch64-pc-windows-msvc.zip'
    }
    $url = "${Prefix}https://github.com/astral-sh/uv/releases/latest/download/${asset}"

    $tmpZip = Join-Path $env:TEMP "uv-download-$(Get-Random).zip"
    try {
        Invoke-WebRequest -Uri $url -OutFile $tmpZip -UseBasicParsing -TimeoutSec 60
    } catch {
        Log-Warn "下载失败（${desc}）"
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        return $false
    }

    $extractDir = Join-Path $env:TEMP "uv-extract-$(Get-Random)"
    try {
        Expand-Archive -Path $tmpZip -DestinationPath $extractDir -Force
    } catch {
        Log-Warn "解压失败（${desc}）"
        Remove-Item $tmpZip, $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    # 定位 uv.exe（结构：uv-<平台>/uv.exe 与 uv-<平台>/uvx.exe）
    $uvExe = Get-ChildItem -Path $extractDir -Recurse -Filter 'uv.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $uvExe) {
        Log-Warn "解压后未找到 uv.exe"
        Remove-Item $tmpZip, $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }

    # 复制到 ~/.local/bin（与官方安装器默认路径一致）
    $binDir = Join-Path $HOME '.local\bin'
    if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
    Copy-Item $uvExe.FullName (Join-Path $binDir 'uv.exe') -Force
    $uvxExe = Get-ChildItem -Path $extractDir -Recurse -Filter 'uvx.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($uvxExe) { Copy-Item $uvxExe.FullName (Join-Path $binDir 'uvx.exe') -Force }

    Remove-Item $tmpZip, $extractDir -Recurse -Force -ErrorAction SilentlyContinue
    return $true
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Log-Ok "uv 已安装：$(uv --version)"
        return
    }
    # 官方安装器与 release 二进制都写入此路径
    $uvPath = Join-Path $HOME '.local\bin\uv.exe'
    if (Test-Path $uvPath) {
        $env:Path = (Join-Path $HOME '.local\bin') + ';' + $env:Path
        Log-Ok "uv 已安装：$(uv --version)"
        return
    }

    Log-Info "未检测到 uv，开始安装（三源顺序 fallback）"
    if ((Install-UvFromAstral) -and (Verify-UvAfterInstall)) { return }
    if ((Install-UvFromRelease -Prefix '') -and (Verify-UvAfterInstall)) { return }
    if ((Install-UvFromRelease -Prefix 'https://ghproxy.net/') -and (Verify-UvAfterInstall)) { return }

    Log-Error "uv 安装失败：所有候选源均不可用"
    Log-Info "请手动安装 uv：https://docs.astral.sh/uv/getting-started/installation/"
    Die "uv 安装失败，请手动安装后重试"
}

# ============================ 项目获取 / 更新 ============================

function Clone-Or-Update {
    $repoDir = Join-Path (Get-Location) $ProjectDirName
    if (Test-Path (Join-Path $repoDir '.git')) {
        Log-Step "更新现有项目（git pull）"
        & git -C $repoDir pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Die "git pull 失败，部署已中止。请处理网络、本地改动或分叉后重新运行。"
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
    Log-Step "配置关键项（有效 NapCat 地址保留，其他项回车保留）"

    # 1. NAPCAT_WS_URL —— 必填
    $curWs = Get-Env 'NAPCAT_WS_URL' '.env'
    $normalizedWs = Normalize-WsUrl $curWs
    if ($normalizedWs) {
        if ($normalizedWs -ne $curWs) {
            Set-Env 'NAPCAT_WS_URL' $normalizedWs '.env'
            Log-Ok "已将 NapCat 端口转换为完整地址：$normalizedWs"
        } else {
            Log-Ok "NAPCAT_WS_URL 地址格式有效（$curWs），保留现有配置"
        }
    } else {
        if ($curWs) { Log-Warn '现有 NapCat 地址无效或仍是模板，请重新配置。' }
        Write-Host "NapCat WebSocket 地址是 bot 与 NapCat 通信的关键。"
        Write-Host "NapCat 与 bot 同机时只需输入端口号（如 3001），将自动拼接为 ws://localhost:<端口>/qq"
        Write-Host "若 NapCat 在远端或路径不同，可直接输入完整地址（如 ws://1.2.3.4:8080/qq）"
        while ($true) {
            $ws = Ask "请输入 NapCat WebSocket 端口（1–65535），远端可填完整地址" ""
            if ([string]::IsNullOrWhiteSpace($ws)) {
                Log-Warn "不能为空，请重新输入"
                continue
            }
            $normalizedWs = Normalize-WsUrl $ws
            if ($normalizedWs) {
                $ws = $normalizedWs
                break
            }
            Log-Warn "请输入 1–65535 的端口，或主机、端口有效的 ws:// / wss:// 地址。"
        }
        Set-Env 'NAPCAT_WS_URL' $ws '.env'
        Log-Ok "NAPCAT_WS_URL 已写入: $ws"
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
    Write-Host "低内存模式：开启后启动机器人会清空下载目录，下载完成后按配置延迟删除文件（默认 3 分钟）。"
    $lm = Ask-Boolean "是否开启低内存模式？" $curLm
    Set-Env 'LOW_MEMORY_MODE' $lm '.env'
    Log-Ok "LOW_MEMORY_MODE=$lm"

    # 4. WebUI 是否启用 —— 当前值作为默认，每次都确认（回车即保留）
    $curWebui = Get-Env 'WEBUI_ENABLED' '.env'
    if ([string]::IsNullOrWhiteSpace($curWebui)) { $curWebui = 'true' }
    Write-Host "WebUI 控制台：可在浏览器管理漫画库与任务，默认监听本机 127.0.0.1:7999。"
    $webui = Ask-Boolean "是否启用 WebUI？" $curWebui
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
  - Windows 原生版：
      按 NapCatQQ 文档安装并启动，随后在 NapCat WebUI 配置 WebSocket 服务端。

关键配置要点（踩坑高频区）：
  1. WebSocket 服务端 host 改为 0.0.0.0（容器化必须，否则宿主机连不上）
  2. token 与 .env 的 NAPCAT_TOKEN 必须一致（如启用了鉴权）
     同机部署在脚本中只填端口即可；Docker 还需映射该 WebSocket 端口。
  3. Docker 部署时，把 downloads 目录同路径 bind mount 进容器：
       -v /绝对路径/JMcomicBot/downloads:/绝对路径/JMcomicBot/downloads
     否则 NapCat 找不到 bot 发送的文件，报 "识别URL失败"
     使用自定义下载目录时，以 .env 的 MANGA_DOWNLOAD_PATH 为准。
  4. 在 NapCat WebUI 的 autoLoginAccount 填入 QQ 号，重启免扫码

部署说明：docs/deployment/windows.md
WebUI 访问与排障：docs/webui.md
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

# 点导入时只加载函数，便于测试；直接执行或 irm | iex 仍启动部署。
if ($MyInvocation.InvocationName -ne '.') { Main }
