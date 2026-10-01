#!/usr/bin/env bash
# E2E 专用后端启动脚本：准备隔离数据目录并启动 MangaBot。
# 由 playwright.config.ts 的 webServer 调用，只在开发机运行。
set -euo pipefail

cd "$(dirname "$0")/../.."

export E2E_DIR="${E2E_DIR:-/tmp/jmbot-e2e}"
rm -rf "$E2E_DIR"
mkdir -p "$E2E_DIR"

export MANGA_DOWNLOAD_PATH="$E2E_DIR/downloads"
export DB_PATH="$E2E_DIR/data"
export BACKUP_PATH="$E2E_DIR/backups"
export WEBUI_ENABLED=true
export WEBUI_HOST=127.0.0.1
export WEBUI_PORT="${E2E_PORT:-18080}"
export WEBUI_SESSION_HOURS=24

uv run python tests/smoke/prepare_test_data.py --mangas 6 >/dev/null 2>&1
exec uv run python main.py
