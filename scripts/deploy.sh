#!/usr/bin/env bash
# ============================================================================
# JMComicBot 一键部署脚本（Linux / macOS）
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
# 或先下载后运行：
#   bash deploy.sh
#
# 行为：
#   1. 检测 / 安装 git、Python>=3.12、uv
#   2. 克隆或更新项目到当前目录下的 JMcomicBot/ 子目录
#   3. 创建虚拟环境并 uv sync 同步依赖
#   4. 幂等复制 .env / option.yml（已存在则保留用户配置）
#   5. 交互式写入 .env 关键项（已配置的项跳过）
#   6. 创建 downloads / data / logs 运行时目录
#   7. 打印 NapCat 部署提示
#   8. 询问是否立即启动 bot
#
# 幂等：重复运行等同于"拉取最新代码 + 同步依赖"，不会覆盖已有配置。
# ============================================================================

set -euo pipefail

# ============================ 全局配置 ============================
# 支持通过环境变量 JMBOT_REPO_URL 覆盖（便于使用镜像源或本地路径测试）
REPO_URL="${JMBOT_REPO_URL:-https://github.com/AAA-huan/JMcomicBot.git}"
PROJECT_DIR_NAME="JMcomicBot"
REQUIRED_PY_MAJOR=3
REQUIRED_PY_MINOR=12
# 示例值（用于判断 .env 是否仍是模板，决定是否询问）
WS_URL_PLACEHOLDER="ws://localhost:port/qq"

# ============================ 颜色与日志 ============================
if [[ -t 1 ]]; then
    RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    BLUE=$'\033[34m'; CYAN=$'\033[36m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; BOLD=""; RESET=""
fi

log_info()  { printf "%s[信息]%s %s\n" "$CYAN" "$RESET" "$*"; }
log_ok()    { printf "%s[完成]%s %s\n" "$GREEN" "$RESET" "$*"; }
log_warn()  { printf "%s[警告]%s %s\n" "$YELLOW" "$RESET" "$*"; }
log_error() { printf "%s[错误]%s %s\n" "$RED" "$RESET" "$*" >&2; }
log_step()  { printf "\n%s=== %s ===%s\n" "${BOLD}${BLUE}" "$*" "$RESET"; }
die() { log_error "$*"; exit 1; }

# ============================ 工具函数 ============================

# 读取用户输入，兼容三种场景：
#   1. 直接运行 bash deploy.sh：stdin 是终端，直接 read 即可
#   2. curl|bash：stdin 是 curl 输出（脚本内容），需从 /dev/tty 读真实终端
#   3. CI / 无 tty：/dev/tty 不可用，退回 stdin 读取（便于自动化喂入）
# 用 (exec </dev/tty) 在子 shell 探测 /dev/tty 是否真正可打开，区分"设备不存在"
# 与"读到 EOF"，避免误判导致死循环
# 用法：ask "提示语" "默认值"  → 输出用户输入或默认值
ask() {
    local prompt="$1" default="${2:-}" result=""
    if [[ -n "$default" ]]; then
        printf "%s（默认：%s）: " "$prompt" "$default" >&2
    else
        printf "%s: " "$prompt" >&2
    fi
    if (exec </dev/tty) 2>/dev/null; then
        IFS= read -r result < /dev/tty || result=""
    else
        IFS= read -r result || result=""
    fi
    printf '%s' "${result:-$default}"
}

# 跨平台 sed -i（GNU 与 BSD/macOS 兼容）
sed_inplace() {
    local file="$1"; shift
    # 注意：不能把 sed --version 的 stdout 重定向到 /dev/null，否则 grep 永远匹配不到
    if sed --version 2>&1 | grep -q GNU; then
        sed -i "$@" "$file"
    else
        sed -i '' "$@" "$file"
    fi
}

# 读取 .env 中某 key 的当前值（不存在则为空）
get_env() {
    local key="$1" file="$2"
    local line
    line=$(grep -E "^${key}=" "$file" 2>/dev/null | head -1 || true)
    echo "${line#"${key}="}"
}

# 设置 .env 中某 key 的值（存在则替换整行，不存在则追加）
set_env() {
    local key="$1" val="$2" file="$3"
    # 转义 sed 替换中的特殊字符
    local escaped
    escaped=$(printf '%s' "$val" | sed -e 's/[\\&]/\\&/g' -e 's/[/]/\\\//g')
    if grep -q "^${key}=" "$file"; then
        sed_inplace "$file" "s|^${key}=.*|${key}=${escaped}|"
    else
        printf '%s=%s\n' "$key" "$val" >> "$file"
    fi
}

# ============================ 环境准备 ============================

ensure_git() {
    if command -v git >/dev/null 2>&1; then
        log_ok "git 已安装：$(git --version)"
        return 0
    fi
    log_info "未检测到 git，尝试自动安装..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y git
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y git
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm git
    elif command -v brew >/dev/null 2>&1; then
        brew install git
    else
        die "无法自动安装 git，请手动安装后重试"
    fi
    command -v git >/dev/null 2>&1 || die "git 安装失败"
    log_ok "git 安装完成：$(git --version)"
}

# 找到满足版本要求的 python 命令，输出命令名；找不到返回 1
find_python() {
    local cmd ver major minor rest
    for cmd in python3 python; do
        command -v "$cmd" >/dev/null 2>&1 || continue
        ver=$("$cmd" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo "")
        [[ -n "$ver" ]] || continue
        major=${ver%%.*}
        rest=${ver#*.}
        minor=${rest%%.*}
        if [[ "$major" -gt "$REQUIRED_PY_MAJOR" ]] || \
           { [[ "$major" -eq "$REQUIRED_PY_MAJOR" ]] && [[ "$minor" -ge "$REQUIRED_PY_MINOR" ]]; }; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

ensure_python() {
    local py
    if py=$(find_python); then
        log_ok "Python 已满足要求：$($py --version 2>&1)"
        return 0
    fi
    log_error "未找到 Python >= ${REQUIRED_PY_MAJOR}.${REQUIRED_PY_MINOR}。"
    log_info "请前往 https://www.python.org/downloads/ 下载并安装 Python ${REQUIRED_PY_MAJOR}.${REQUIRED_PY_MINOR}+。"
    die "请安装满足要求的 Python 后重新运行本脚本。"
}

# ============================ uv 安装（三源顺序 fallback） ============================

# uv 安装候选源（按优先级）：
#   1. astral.sh 官方安装器：最完整，自动检测平台、写入 ~/.local/bin 与 shell 配置
#   2. GitHub Release 二进制直连：releases/latest/download/uv-<平台>.tar.gz
#   3. ghproxy 镜像 release：对 github.com 做代理，国内 github 不通时使用
# 按顺序尝试，第一个成功即返回；全部失败则报错并给出手动安装指引（不静默兜底）

# 平台 → uv release 资产名映射
_uv_release_asset() {
    local os arch
    os=$(uname -s)
    arch=$(uname -m)
    case "$os-$arch" in
        Linux-x86_64)   echo "uv-x86_64-unknown-linux-gnu.tar.gz" ;;
        Linux-aarch64)  echo "uv-aarch64-unknown-linux-gnu.tar.gz" ;;
        Darwin-x86_64)  echo "uv-x86_64-apple-darwin.tar.gz" ;;
        Darwin-arm64)   echo "uv-aarch64-apple-darwin.tar.gz" ;;
        *)              return 1 ;;
    esac
}

# 安装后验证：把 ~/.local/bin 加入 PATH 并确认 uv 可用
_verify_uv_after_install() {
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        log_warn "uv 安装后仍不在 PATH 中"
        return 1
    fi
    log_ok "uv 安装完成：$(uv --version)"
    return 0
}

# 源1：astral.sh 官方安装器（最完整）
_install_uv_official() {
    log_info "尝试源1：astral.sh 官方安装器"
    local url="https://astral.sh/uv/install.sh"
    if command -v curl >/dev/null 2>&1; then
        if curl -fsSL --max-time 30 "$url" | sh; then return 0; fi
    elif command -v wget >/dev/null 2>&1; then
        if wget -qO- --timeout=30 "$url" | sh; then return 0; fi
    else
        log_warn "未找到 curl 或 wget，跳过源1"
        return 1
    fi
    log_warn "源1（astral.sh 官方安装器）失败"
    return 1
}

# 源2/3：GitHub Release 二进制（prefix 为空=直连，prefix=镜像前缀=走镜像）
#   prefix 示例："" 或 "https://ghproxy.net/"
_install_uv_release() {
    local prefix="$1"
    local desc="${prefix:-GitHub 直连}"
    [[ -n "$prefix" ]] && desc="${prefix}"
    log_info "尝试源：GitHub Release 二进制（${desc}）"

    local asset
    if ! asset=$(_uv_release_asset); then
        log_warn "当前平台 $(uname -s)-$(uname -m) 无对应 release 资产，跳过"
        return 1
    fi
    local url="${prefix}https://github.com/astral-sh/uv/releases/latest/download/${asset}"

    # 临时文件 / 目录（mktemp 不带 -t，跨 GNU/BSD 兼容）
    local tmpfile tmpdir
    tmpfile=$(mktemp) || { log_warn "无法创建临时文件"; return 1; }
    tmpdir=$(mktemp -d) || { rm -f "$tmpfile"; log_warn "无法创建临时目录"; return 1; }

    # 下载（curl 优先，wget 兜底）
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL --max-time 60 -o "$tmpfile" "$url"; then
            log_warn "下载失败（${desc}）"; rm -rf "$tmpfile" "$tmpdir"; return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -q --timeout=60 -O "$tmpfile" "$url"; then
            log_warn "下载失败（${desc}）"; rm -rf "$tmpfile" "$tmpdir"; return 1
        fi
    else
        log_warn "未找到 curl 或 wget"; rm -rf "$tmpfile" "$tmpdir"; return 1
    fi

    # 解压并定位 uv 可执行文件（结构：uv-<平台>/uv 与 uv-<平台>/uvx）
    if ! tar -xzf "$tmpfile" -C "$tmpdir"; then
        log_warn "解压失败（${desc}）"; rm -rf "$tmpfile" "$tmpdir"; return 1
    fi
    local extracted_bin
    extracted_bin=$(find "$tmpdir" -name uv -type f 2>/dev/null | head -1)
    if [[ -z "$extracted_bin" ]]; then
        log_warn "解压后未找到 uv 可执行文件"; rm -rf "$tmpfile" "$tmpdir"; return 1
    fi
    chmod +x "$extracted_bin"

    # 复制到 ~/.local/bin（与官方安装器默认路径一致，便于后续 PATH 复用）
    local bindir="$HOME/.local/bin"
    mkdir -p "$bindir"
    cp "$extracted_bin" "$bindir/uv"
    chmod +x "$bindir/uv"
    # uvx 一并复制（如存在）
    local extracted_uvx
    extracted_uvx=$(find "$tmpdir" -name uvx -type f 2>/dev/null | head -1)
    if [[ -n "$extracted_uvx" ]]; then
        chmod +x "$extracted_uvx"
        cp "$extracted_uvx" "$bindir/uvx"
    fi
    rm -rf "$tmpfile" "$tmpdir"
    return 0
}

ensure_uv() {
    # 已经在 PATH 中
    if command -v uv >/dev/null 2>&1; then
        log_ok "uv 已安装：$(uv --version)"
        return 0
    fi
    # uv 默认安装到 ~/.local/bin（官方安装器与 release 二进制都写入此路径）
    if [[ -x "$HOME/.local/bin/uv" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
        log_ok "uv 已安装：$(uv --version)"
        return 0
    fi

    log_info "未检测到 uv，开始安装（三源顺序 fallback）"
    if _install_uv_official                && _verify_uv_after_install; then return 0; fi
    if _install_uv_release ""              && _verify_uv_after_install; then return 0; fi
    if _install_uv_release "https://ghproxy.net/" && _verify_uv_after_install; then return 0; fi

    log_error "uv 安装失败：所有候选源均不可用"
    log_info "请手动安装 uv：https://docs.astral.sh/uv/getting-started/installation/"
    die "uv 安装失败，请手动安装后重试"
}

# ============================ 项目获取 / 更新 ============================

clone_or_update() {
    if [[ -d "$PROJECT_DIR_NAME/.git" ]]; then
        log_step "更新现有项目（git pull）"
        if ! git -C "$PROJECT_DIR_NAME" pull --ff-only; then
            log_warn "git pull 失败，可能存在本地改动或分叉。请手动处理 $PROJECT_DIR_NAME 目录。"
        fi
    else
        log_step "克隆项目到 ./$PROJECT_DIR_NAME"
        if [[ -d "$PROJECT_DIR_NAME" ]]; then
            die "./$PROJECT_DIR_NAME 已存在但不是 git 仓库，请手动处理后重试"
        fi
        git clone "$REPO_URL" "$PROJECT_DIR_NAME"
        log_ok "克隆完成"
    fi
}

# ============================ Python 环境与依赖 ============================

setup_python_env() {
    cd "$PROJECT_DIR_NAME"
    log_step "创建虚拟环境与同步依赖"

    # 创建虚拟环境（已存在则复用）
    uv venv
    log_ok "虚拟环境就绪（.venv）"

    # 同步依赖（基于 pyproject.toml + uv.lock，跳过 dev 组以加快部署）
    log_info "同步依赖（uv sync --no-dev），首次可能耗时较长..."
    uv sync --no-dev
    log_ok "依赖同步完成"
}

# ============================ 配置文件 ============================

prepare_config_files() {
    log_step "准备配置文件"
    # .env：不存在才复制，已存在保留用户配置
    if [[ ! -f ".env" ]]; then
        cp .env.example .env
        log_ok "已从 .env.example 生成 .env"
    else
        log_ok ".env 已存在，保留现有配置"
    fi
    # option.yml：jmcomic 下载配置，缺失会导致下载静默失败
    if [[ ! -f "option.yml" ]]; then
        cp option_example.yml option.yml
        log_ok "已从 option_example.yml 生成 option.yml"
    else
        log_ok "option.yml 已存在，保留现有配置"
    fi
    # 运行时目录
    mkdir -p downloads data logs
    log_ok "运行时目录就绪（downloads / data / logs）"
}

# 交互式写入 .env 关键项（仅当当前值仍是示例/默认值时才询问）
interactive_config() {
    log_step "配置关键项（已配置的项将跳过）"

    # 1. NAPCAT_WS_URL —— 必填
    local cur_ws
    cur_ws=$(get_env "NAPCAT_WS_URL" ".env")
    if [[ -z "$cur_ws" ]] || [[ "$cur_ws" == "$WS_URL_PLACEHOLDER" ]]; then
        echo "NapCat WebSocket 地址是 bot 与 NapCat 通信的关键。" >&2
        echo "NapCat 与 bot 同机时只需输入端口号（如 3001），将自动拼接为 ws://localhost:<端口>/qq" >&2
        echo "若 NapCat 在远端或路径不同，可直接输入完整地址（如 ws://1.2.3.4:8080/qq）" >&2
        local ws=""
        while true; do
            ws=$(ask "请输入 NapCat WebSocket 端口或完整地址" "")
            if [[ -z "$ws" ]]; then
                log_warn "不能为空，请重新输入"
                continue
            fi
            # 纯数字：当作端口，拼接默认地址（NapCat 与 bot 同机的最常见场景）
            if [[ "$ws" =~ ^[0-9]+$ ]]; then
                ws="ws://localhost:${ws}/qq"
                break
            fi
            # 完整 ws/wss 地址直接采用
            if [[ "$ws" =~ ^wss?://.+ ]]; then
                break
            fi
            log_warn "格式应为端口号（如 3001）或 ws://host:port/path，请重新输入"
        done
        set_env "NAPCAT_WS_URL" "$ws" ".env"
        log_ok "NAPCAT_WS_URL 已写入: $ws"
    else
        log_ok "NAPCAT_WS_URL 已配置（$cur_ws），跳过"
    fi

    # 2. NAPCAT_TOKEN —— 可选，当前值作为默认（回车即保留，便于幂等）
    local cur_token
    cur_token=$(get_env "NAPCAT_TOKEN" ".env")
    # 去掉示例值两侧引号占位
    [[ "$cur_token" == '""' ]] && cur_token=""
    local token
    token=$(ask "请输入 NAPCAT_TOKEN（NapCat 鉴权 token，可留空）" "$cur_token")
    # 去掉用户输入两侧引号避免重复
    token="${token#\"}"; token="${token%\"}"
    set_env "NAPCAT_TOKEN" "$token" ".env"
    log_ok "NAPCAT_TOKEN 已写入"

    # 3. LOW_MEMORY_MODE —— 当前值作为默认，每次都确认（回车即保留）
    local cur_lm
    cur_lm=$(get_env "LOW_MEMORY_MODE" ".env")
    [[ -z "$cur_lm" ]] && cur_lm="false"
    echo "低内存模式：开启后下载完立即发送并自动删除，适合存储/内存受限环境。" >&2
    local lm
    lm=$(ask "是否开启低内存模式？(true/false)" "$cur_lm")
    case "$lm" in
        true|True|TRUE|yes|y|Y) lm="true" ;;
        *) lm="false" ;;
    esac
    set_env "LOW_MEMORY_MODE" "$lm" ".env"
    log_ok "LOW_MEMORY_MODE=$lm"

    # 4. WebUI 是否启用 —— 当前值作为默认，每次都确认（回车即保留）
    local cur_webui
    cur_webui=$(get_env "WEBUI_ENABLED" ".env")
    [[ -z "$cur_webui" ]] && cur_webui="true"
    echo "WebUI 控制台：可在浏览器管理漫画库与任务，默认监听本机 127.0.0.1:7999。" >&2
    local webui
    webui=$(ask "是否启用 WebUI？(true/false)" "$cur_webui")
    case "$webui" in
        false|False|FALSE|no|n|N) webui="false" ;;
        *) webui="true" ;;
    esac
    set_env "WEBUI_ENABLED" "$webui" ".env"
    log_ok "WEBUI_ENABLED=$webui"
}

# ============================ NapCat 部署提示 ============================

print_napcat_hint() {
    cat <<'EOF'

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
EOF
}

# ============================ 启动询问 ============================

ask_launch() {
    echo ""
    local ans
    ans=$(ask "是否立即启动 bot？(y/n)" "n")
    case "$ans" in
        y|Y|yes)
            log_info "启动前请确认 NapCat 已就绪并完成 QQ 登录。"
            log_step "启动 bot（uv run python main.py，Ctrl+C 退出）"
            exec uv run python main.py
            ;;
        *)
            log_ok "部署完成。后续启动命令："
            echo "  cd $(pwd) && uv run python main.py"
            ;;
    esac
}

# ============================ 主流程 ============================

main() {
    log_step "JMComicBot 一键部署"

    # 工作目录：脚本运行时的当前目录
    log_info "工作目录：$(pwd)"

    ensure_git
    ensure_python
    ensure_uv

    clone_or_update
    setup_python_env

    prepare_config_files
    interactive_config

    print_napcat_hint
    ask_launch
}

main "$@"
