#!/bin/bash
# proot 内的 Debian / Ubuntu 专用部署入口，Python 完全由 uv 管理。
# curl -fsSL https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy-proot.sh | /bin/bash
set -euo pipefail

prepare_proot_environment() {
    # 不继承 Termux 工具路径、动态链接器设置或宿主 Python / 虚拟环境。
    export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    unset PREFIX LD_PRELOAD LD_LIBRARY_PATH PYTHONHOME PYTHONPATH VIRTUAL_ENV CONDA_PREFIX
    unset UV_NO_MANAGED_PYTHON UV_PROJECT_ENVIRONMENT UV_PYTHON_PREFERENCE
    unset UV_PYTHON_BIN_DIR UV_PROJECT UV_WORKING_DIR UV_CONFIG_FILE
    export UV_INSTALL_DIR="$HOME/.local/bin"
    export UV_PYTHON=3.12
    export UV_MANAGED_PYTHON=1
    export UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python"
    export UV_CACHE_DIR="$HOME/.cache/uv"
    export UV_PYTHON_DOWNLOADS=automatic
    if [[ ! -f /etc/os-release ]] || ! command -v apt-get >/dev/null 2>&1; then
        printf '[错误] 请先进入 proot 内的 Debian / Ubuntu，再运行本脚本。\n' >&2
        return 1
    fi
    # uv 的 Linux 托管 Python 使用 glibc，原生 Termux 的 Android 环境不适用。
    getconf GNU_LIBC_VERSION >/dev/null || return 1
}

load_deployment_functions() {
    local script_directory temporary_script
    script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd)
    if [[ -f "$script_directory/deploy.sh" ]]; then
        source "$script_directory/deploy.sh"
    else
        # 管道运行时没有相邻文件，下载相同发布分支的公共部署函数。
        temporary_script=$(mktemp)
        if ! curl -fsSL 'https://raw.githubusercontent.com/AAA-huan/JMcomicBot/main/scripts/deploy.sh' -o "$temporary_script"; then
            rm -f "$temporary_script"
            printf '[错误] 下载公共部署脚本失败，部署中止。\n' >&2
            return 1
        fi
        source "$temporary_script"
        rm -f "$temporary_script"
    fi
}

configure_proot_functions() {
    # 复用公共配置、更新和启动流程；环境相关函数仅使用 proot 内的工具。
    ensure_git() {
        if command -v git >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
            return 0
        fi
        if [[ $(id -u) -ne 0 ]]; then
            die "请先在 proot 内安装 git、curl 和 ca-certificates，再重新运行。"
        fi
        apt-get update
        apt-get install -y git curl ca-certificates
    }

    ensure_uv() {
        if command -v uv >/dev/null 2>&1; then
            uv --version || die "proot 内的 uv 无法运行"
            return 0
        fi
        # 只使用官方安装器；失败直接中止并暴露问题，不静默切换安装源。
        _install_uv_official || die "proot 内安装 uv 失败"
        _verify_uv_after_install || die "proot 内 uv 安装后无法运行"
    }

    find_python() {
        uv python find --managed-python --no-project --no-python-downloads 3.12
    }

    ensure_python() {
        if ! uv python find --managed-python --no-project --no-python-downloads 3.12 >/dev/null 2>&1; then
            log_info "uv 中没有托管 Python 3.12，将通过 uv 下载，无需在 Termux 或 proot 中另装 Python。"
            uv python install 3.12 || die "uv 托管 Python 安装失败"
        fi
        local interpreter
        interpreter=$(find_python) || die "未找到 uv 托管 Python 3.12"
        "$interpreter" --version || die "uv 托管 Python 无法在 proot 内运行"
    }

    setup_python_env() {
        cd "$PROJECT_DIR_NAME"
        log_step "使用 uv 托管 Python 3.12 同步虚拟环境和依赖"
        # uv sync 自动创建环境；旧环境解释器与指定版本不兼容时由 uv 重建。
        uv sync --no-dev --managed-python --python 3.12 || die "proot 环境依赖同步失败"
        uv run --no-sync --managed-python --python 3.12 python -c 'import sys; print("项目解释器：", sys.executable)'
    }

    ask_launch() {
        echo ""
        local answer
        answer=$(ask "是否立即启动 bot？(y/n)" "n") || return 1
        case "$answer" in
            y|Y|yes)
                log_info "启动前请确认 NapCat 已就绪并完成 QQ 登录。"
                exec uv run --no-dev --managed-python --python 3.12 python main.py
                ;;
            *)
                log_ok "部署完成。后续请在 proot 内启动："
                printf '  cd %q && uv run --no-dev --managed-python --python 3.12 python main.py\n' "$(pwd)"
                ;;
        esac
    }

}

main_proot() {
    prepare_proot_environment
    # curl 必须是 proot 内的程序，缺失时由该环境的包管理器安装。
    if ! command -v curl >/dev/null 2>&1; then
        [[ $(id -u) -eq 0 ]] || { printf '[错误] 请在 proot 内安装 curl。\n' >&2; return 1; }
        apt-get update
        apt-get install -y curl ca-certificates
    fi
    load_deployment_functions
    configure_proot_functions
    log_step "JMComicBot proot 专用部署"
    ensure_git
    ensure_uv
    ensure_python
    clone_or_update
    setup_python_env
    prepare_config_files
    interactive_config
    print_napcat_hint
    ask_launch
}

# 测试可加载函数；直接执行时才触发安装和交互。
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]; then
    main_proot "$@"
fi
