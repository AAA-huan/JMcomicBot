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

# 制造损坏 PDF 供阅读器错误界面用例使用（900004 不用于正常阅读用例）
uv run python - <<'PY'
import os
import sqlite3
from pathlib import Path

db_path = Path(os.environ["DB_PATH"]) / "main.db"
conn = sqlite3.connect(db_path)
row = conn.execute(
    "select relative_path from manga_file where manga_id = '900004'"
).fetchone()
conn.close()
if row is None:
    raise SystemExit("E2E 数据缺少 900004 文件记录")
target = Path(os.environ["MANGA_DOWNLOAD_PATH"]) / row[0]
target.write_bytes(b"this is not a valid pdf")
print(f"E2E 损坏 PDF 已就绪: {target.name}")

# 大文件按需加载使用独立漫画，避免改变其他阅读进度用例的数据。
from src.database.database import DatabaseManager
from src.database.repositories import MangaRepository
from tests.smoke.prepare_test_data import _build_pdf

root = Path(os.environ["MANGA_DOWNLOAD_PATH"])
large = root / "900007-大文件读取测试.pdf"
large.write_bytes(_build_pdf(20, page_padding_bytes=256 * 1024))
with DatabaseManager(os.environ["DB_PATH"], download_root=str(root)) as db:
    mangas = MangaRepository(db, str(root))
    mangas.upsert("900007", "大文件读取测试", "测试作者", 1, 20)
    mangas.add_file("900007", str(large), page_count=20)
PY

exec uv run python main.py
