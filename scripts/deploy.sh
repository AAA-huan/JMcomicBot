#!/usr/bin/bash
# ============================================================================
# JMComicBot 一键部署脚本（Linux）
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh | bash
# 或先下载后运行：
#   bash deploy.sh
#
# 行为：
#   1. 检查 Python>=3.12，缺失时由 uv 安装；检测 / 安装 git、uv
#   2. 克隆或更新项目到当前目录下的 JMcomicBot/ 子目录
#   3. 创建虚拟环境并 uv sync 同步依赖
#   4. 幂等复制 .env / option.yml（已存在则保留用户配置）
#   5. 校验 NapCat 地址并引导配置关键项（有效地址保留，其他项回车保留）
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
DEPLOY_PYTHON=""

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
# 与"读到 EOF"；输入结束时明确报错，不把 EOF 当作回车
# 用法：ask "提示语" "默认值"  → 输出用户输入或默认值
ask() {
    local prompt="$1" default="${2:-}" result=""
    if [[ -n "$default" ]]; then
        printf "%s（默认：%s）: " "$prompt" "$default" >&2
    else
        printf "%s: " "$prompt" >&2
    fi
    if (exec </dev/tty) 2>/dev/null; then
        IFS= read -r result < /dev/tty || { log_error "终端输入已结束，部署中止。"; return 1; }
    else
        IFS= read -r result || { log_error "标准输入已结束，请在可交互终端重新运行脚本。"; return 1; }
    fi
    result=$(printf '%s' "$result" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
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
    line=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | head -1 || true)
    local value="${line#*=}"
    value=$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    # 引号内的 # 是值的一部分；只去除引号外的行尾注释。
    local double_quoted='^"([^"]*)"([[:space:]]*#.*)?$'
    local single_quoted="^'([^']*)'([[:space:]]*#.*)?$"
    if [[ "$value" =~ $double_quoted ]] || [[ "$value" =~ $single_quoted ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    else
        printf '%s' "$value" | sed 's/[[:space:]]#.*$//;s/[[:space:]]*$//'
    fi
}

# 设置 .env 中某 key 的值（存在则替换整行，不存在则追加）
set_env() {
    local key="$1" val="$2" file="$3"
    # 转义 sed 替换中的特殊字符
    local escaped
    escaped=$(printf '%s' "$val" | sed 's/[\\&|]/\\&/g')
    if grep -q "^[[:space:]]*${key}[[:space:]]*=" "$file"; then
        sed_inplace "$file" "s|^[[:space:]]*${key}[[:space:]]*=.*|${key}=${escaped}|"
    else
        printf '%s=%s\n' "$key" "$val" >> "$file"
    fi
}

# Python 已在部署前检查版本；使用标准 URL 解析器校验端口、主机与 IPv6。
# 纯端口仅适用于 NapCat 与机器人同机，配置文件仍写入完整 WebSocket 地址。
normalize_ws_url() {
    local py
    py=$(find_python) || return 1
    "$py" -c '
from urllib.parse import urlsplit
import re
import sys

value = sys.argv[1].strip()
if re.fullmatch(r"[0-9]+", value):
    if len(value) > 5 or not 1 <= int(value) <= 65535:
        sys.exit(1)
    value = f"ws://localhost:{int(value)}/qq"
try:
    parsed = urlsplit(value)
    if (parsed.scheme not in ("ws", "wss") or not parsed.hostname
            or re.search(r"\s", value) or parsed.fragment
            or parsed.netloc.endswith(":") or parsed.port == 0):
        sys.exit(1)
except ValueError:
    sys.exit(1)
print(value)
' "$1"
}

# 布尔值必须明确识别，输入错误时重新询问，避免静默改动原配置。
ask_boolean() {
    local value
    while true; do
        value=$(ask "$1 (true/false)" "$2") || return 1
        case "$value" in
            true|True|TRUE|yes|y|Y|1|on) printf 'true'; return 0 ;;
            false|False|FALSE|no|n|N|0|off) printf 'false'; return 0 ;;
            *) log_warn "请输入 true 或 false。" >&2 ;;
        esac
    done
}

# ============================ 环境准备 ============================

# 检测当前用户能否获得 root 权限，供安装系统软件前判断是否可用 sudo：
#   输出 "root" —— 已是 root，命令直接执行；
#   输出 "sudo" —— 可借 sudo 提权（免密，或交互式终端提示输入密码）；
#   无任何提权途径时输出空字符串并返回 1。
detect_privilege() {
    if [[ "$(id -u)" -eq 0 ]]; then
        printf 'root'
        return 0
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        return 1
    fi
    if sudo -n true >/dev/null 2>&1; then
        printf 'sudo'
        return 0
    fi
    # 非免密 sudo：区分"需要输入密码"（可用）与"不在 sudoers"（真正无权限）
    local err
    err=$(sudo -n true 2>&1 || true)
    if [[ "$err" == *"sudoers"* ]]; then
        return 1
    fi
    printf 'sudo'
    return 0
}

# 以 root / sudo 方式执行命令：提权方式由 detect_privilege 的结果指定
run_privileged() {
    local mode="$1"; shift
    if [[ "$mode" == "root" ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

ensure_git() {
    if command -v git >/dev/null 2>&1; then
        log_ok "git 已安装：$(git --version)"
        return 0
    fi
    log_info "未检测到 git，尝试自动安装..."

    # 先检测提权途径，无 root / sudo 权限时立即精确报错，避免安装中途失败
    local priv
    priv=$(detect_privilege) || die "当前用户既不是 root 也无法使用 sudo，无法自动安装 git，请以 root 运行或手动安装 git"
    if [[ "$priv" == "sudo" ]]; then
        log_info "将使用 sudo 安装（如提示输入密码，请输入当前用户密码）"
    fi

    if command -v apt-get >/dev/null 2>&1; then
        run_privileged "$priv" apt-get update -y && run_privileged "$priv" apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then
        run_privileged "$priv" dnf install -y git
    elif command -v yum >/dev/null 2>&1; then
        run_privileged "$priv" yum install -y git
    elif command -v pacman >/dev/null 2>&1; then
        run_privileged "$priv" pacman -S --noconfirm git
    elif command -v brew >/dev/null 2>&1; then
        brew install git
    else
        die "无法自动安装 git，请手动安装后重试"
    fi
    command -v git >/dev/null 2>&1 || die "git 安装失败"
    log_ok "git 安装完成：$(git --version)"
}

# 找到满足版本要求的系统 Python，输出绝对路径；找不到返回 1。
find_system_python() {
    local cmd ver major minor rest
    for cmd in python3 python; do
        command -v "$cmd" >/dev/null 2>&1 || continue
        ver=$("$cmd" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null) || continue
        [[ -n "$ver" ]] || continue
        major=${ver%%.*}
        rest=${ver#*.}
        minor=${rest%%.*}
        if [[ "$major" -gt 3 ]] || \
           { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 12 ]]; }; then
            "$cmd" -c 'import sys;print(sys.executable)'
            return 0
        fi
    done
    return 1
}

find_python() {
    if [[ -n "$DEPLOY_PYTHON" ]]; then
        printf '%s\n' "$DEPLOY_PYTHON"
        return 0
    fi
    find_system_python
}

ensure_python() {
    local py
    if py=$(find_system_python); then
        DEPLOY_PYTHON="$py"
        log_ok "Python 已满足要求：$("$py" --version 2>&1)"
        ensure_uv
        return 0
    fi
    log_info "未找到系统 Python 3.12+，检查 uv 中的 Python。"
    ensure_uv
    if ! py=$(uv python find --managed-python --no-project --no-python-downloads ">=3.12" 2>/dev/null); then
        log_info "没有可用的 Python，将通过 uv 下载 Python 3.12，无需手动安装。"
        uv python install "3.12" || die "uv 安装 Python 失败，部署中止。"
        py=$(uv python find --managed-python --no-project --no-python-downloads ">=3.12") || die "uv 安装后未找到可用 Python。"
    fi
    DEPLOY_PYTHON="$py"
    "$py" --version || die "uv 中的 Python 无法运行。"
    log_ok "使用 uv 托管 Python：$py"
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
            die "git pull 失败，部署已中止。请处理网络、本地改动或分叉后重新运行。"
        fi
        return 0
    fi
    log_step "克隆项目到 ./$PROJECT_DIR_NAME"
    if [[ -d "$PROJECT_DIR_NAME" ]]; then
        die "./$PROJECT_DIR_NAME 已存在但不是 git 仓库，请手动处理后重试"
    fi

    # 候选源：直连 → GitHub 加速代理（按顺序尝试，单源失败切下一个）
    # 仅使用 GitHub 通用加速代理，不使用清华等只收录大项目的镜像源。
    local sources=(
        "$REPO_URL"
        "https://ghproxy.net/$REPO_URL"
        "https://mirror.ghproxy.com/$REPO_URL"
    )
    local cloned=0 url
    for url in "${sources[@]}"; do
        log_info "尝试克隆源：$url"
        # 低速超时：30 秒内下载不足 1000 字节即判定失败，避免慢源卡死流程
        if GIT_HTTP_LOW_SPEED_TIME=30 GIT_HTTP_LOW_SPEED_LIMIT=1000 \
           git clone --depth 1 "$url" "$PROJECT_DIR_NAME" 2>/dev/null; then
            cloned=1
            break
        fi
        log_warn "克隆失败，尝试下一个源"
        rm -rf "$PROJECT_DIR_NAME" 2>/dev/null
    done
    [[ $cloned -eq 1 ]] || die "所有克隆源均不可用，请检查网络或手动克隆：$REPO_URL"

    # 克隆成功后把 remote 改回官方源，保证后续 git pull 优先直连
    git -C "$PROJECT_DIR_NAME" remote set-url origin "$REPO_URL" 2>/dev/null
    log_ok "克隆完成"
}

# ============================ Python 环境与依赖 ============================

setup_python_env() {
    cd "$PROJECT_DIR_NAME"
    log_step "创建虚拟环境与同步依赖"

    # 同步依赖（基于 pyproject.toml + uv.lock，跳过 dev 组以加快部署）
    # 明确使用环境检查选定的解释器；uv sync 同时创建或更新 .venv。
    log_info "同步依赖（uv sync --no-dev），首次可能耗时较长..."
    uv sync --no-dev --python "$DEPLOY_PYTHON" --no-python-downloads
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
    # option.yml：jmcomic 下载配置，缺失会导致创建下载配置时抛错
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

# 有效 NapCat 地址保留；其余关键项每次确认，回车保留当前值。
interactive_config() {
    log_step "配置关键项（有效 NapCat 地址保留，其他项回车保留）"

    # 1. NAPCAT_WS_URL —— 必填
    local cur_ws normalized_ws
    cur_ws=$(get_env "NAPCAT_WS_URL" ".env")
    if normalized_ws=$(normalize_ws_url "$cur_ws"); then
        if [[ "$normalized_ws" != "$cur_ws" ]]; then
            set_env "NAPCAT_WS_URL" "$normalized_ws" ".env"
            log_ok "已将 NapCat 端口转换为完整地址：$normalized_ws"
        else
            log_ok "NAPCAT_WS_URL 地址格式有效（$cur_ws），保留现有配置"
        fi
    else
        [[ -z "$cur_ws" ]] || log_warn "现有 NapCat 地址无效或仍是模板，请重新配置。"
        echo "NapCat WebSocket 地址是 bot 与 NapCat 通信的关键。" >&2
        echo "NapCat 与 bot 同机时只需输入端口号（如 3001），将自动拼接为 ws://localhost:<端口>/qq" >&2
        echo "若 NapCat 在远端或路径不同，可直接输入完整地址（如 ws://1.2.3.4:8080/qq）" >&2
        local ws=""
        while true; do
            ws=$(ask "请输入 NapCat WebSocket 端口（推荐 3001–3010），远端可填完整地址" "3001") || return 1
            if normalized_ws=$(normalize_ws_url "$ws"); then
                ws="$normalized_ws"
                break
            fi
            log_warn "请输入 1–65535 的端口，或主机、端口有效的 ws:// / wss:// 地址。"
        done
        set_env "NAPCAT_WS_URL" "$ws" ".env"
        log_ok "NAPCAT_WS_URL 已写入: $ws"
    fi

    # 2. NAPCAT_TOKEN —— 可选，当前值作为默认（回车即保留，便于幂等）
    local cur_token
    cur_token=$(get_env "NAPCAT_TOKEN" ".env")
    # 去掉示例值两侧引号占位
    [[ "$cur_token" == '""' ]] && cur_token=""
    local token
    token=$(ask "请输入 NAPCAT_TOKEN（NapCat 鉴权 token，可留空）" "$cur_token") || return 1
    # 去掉用户输入两侧引号避免重复
    token="${token#\"}"; token="${token%\"}"
    set_env "NAPCAT_TOKEN" "$token" ".env"
    log_ok "NAPCAT_TOKEN 已写入"

    # 3. LOW_MEMORY_MODE —— 当前值作为默认，每次都确认（回车即保留）
    local cur_lm
    cur_lm=$(get_env "LOW_MEMORY_MODE" ".env")
    [[ -z "$cur_lm" ]] && cur_lm="false"
    echo "低内存模式：开启后启动机器人会清空下载目录，下载完成后按配置延迟删除文件（默认 3 分钟）。" >&2
    local lm
    lm=$(ask_boolean "是否开启低内存模式？" "$cur_lm") || return 1
    set_env "LOW_MEMORY_MODE" "$lm" ".env"
    log_ok "LOW_MEMORY_MODE=$lm"

    # 4. WebUI 是否启用 —— 当前值作为默认，每次都确认（回车即保留）
    local cur_webui
    cur_webui=$(get_env "WEBUI_ENABLED" ".env")
    [[ -z "$cur_webui" ]] && cur_webui="true"
    echo "WebUI 控制台：可在浏览器管理漫画库与任务，默认监听本机 127.0.0.1:7999。" >&2
    local webui
    webui=$(ask_boolean "是否启用 WebUI？" "$cur_webui") || return 1
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
     同机部署在脚本中只填端口即可；Docker 还需映射该 WebSocket 端口。
  3. Docker 部署时，把 downloads 目录同路径 bind mount 进容器：
       -v /绝对路径/JMcomicBot/downloads:/绝对路径/JMcomicBot/downloads
     否则 NapCat 找不到 bot 发送的文件，报 "识别URL失败"
     使用自定义下载目录时，以 .env 的 MANGA_DOWNLOAD_PATH 为准。
  4. 在 NapCat WebUI 的 autoLoginAccount 填入 QQ 号，重启免扫码

部署说明：docs/deployment/linux.md、docs/deployment/android.md
WebUI 访问与排障：docs/webui.md
========================================================================
EOF
}

# ============================ 启动询问 ============================

ask_launch() {
    echo ""
    local ans
    ans=$(ask "是否立即启动 bot？(y/n)" "n") || return 1
    case "$ans" in
        y|Y|yes)
            log_info "启动前请确认 NapCat 已就绪并完成 QQ 登录。"
            log_step "启动 bot（uv run --no-dev python main.py，Ctrl+C 退出）"
            exec uv run --no-dev python main.py
            ;;
        *)
            log_ok "部署完成。后续启动命令："
            echo "  cd $(pwd) && uv run --no-dev python main.py"
            ;;
    esac
}

# ============================ 主流程 ============================

main() {
    log_step "JMComicBot 一键部署"

    # 工作目录：脚本运行时的当前目录
    log_info "工作目录：$(pwd)"

    ensure_python
    ensure_git

    clone_or_update
    setup_python_env

    prepare_config_files
    interactive_config

    print_napcat_hint
    ask_launch
}

# 允许测试加载函数，只有直接执行脚本时才启动部署。
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]; then
    main "$@"
fi
