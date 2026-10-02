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

ensure_uv() {
    # 已经在 PATH 中
    if command -v uv >/dev/null 2>&1; then
        log_ok "uv 已安装：$(uv --version)"
        return 0
    fi
    # uv 默认安装到 ~/.local/bin（astral 安装器）
    if [[ -x "$HOME/.local/bin/uv" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
        log_ok "uv 已安装：$(uv --version)"
        return 0
    fi
    log_info "未检测到 uv，使用官方安装器安装..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        die "未找到 curl 或 wget，无法安装 uv，请手动安装后重试"
    fi
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv 安装失败，请手动安装后重试"
    log_ok "uv 安装完成：$(uv --version)"
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
        echo "格式形如 ws://主机:端口/路径，例如 ws://localhost:3001/qq" >&2
        local ws=""
        while true; do
            ws=$(ask "请输入 NAPCAT_WS_URL" "")
            if [[ -z "$ws" ]]; then
                log_warn "NAPCAT_WS_URL 不能为空，请重新输入"
                continue
            fi
            if [[ "$ws" =~ ^wss?://.+ ]]; then
                break
            fi
            log_warn "格式应为 ws://host:port/path，请重新输入"
        done
        set_env "NAPCAT_WS_URL" "$ws" ".env"
        log_ok "NAPCAT_WS_URL 已写入"
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
