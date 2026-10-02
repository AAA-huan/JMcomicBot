# 🗄️ 数据库维护

数据库位于 `DB_PATH`（默认 `./data`）下的 `main.db`，启动时自动执行版本化迁移，
迁移前会生成 `main.db.pre-migration.bak` 作为安全网。备份目录由 `BACKUP_PATH`
（默认 `./data/backups`）配置。

进入项目目录并激活虚拟环境后，可使用以下维护脚本：

```bash
# 备份数据库：生成 main-日期-时间-版本号.db，并登记到 backup_record
uv run python scripts/backup_database.py

# 扫描下载目录，将新增/更新漫画同步进数据库
uv run python scripts/scan_mangas.py            # 正式写入
uv run python scripts/scan_mangas.py --dry-run  # 仅预览

# 修复孤儿记录：标记磁盘已无文件的漫画缺失，清理孤儿标签
uv run python scripts/repair_mangas.py --dry-run  # 预览差异
uv run python scripts/repair_mangas.py            # 执行修复

# 校验文件：路径安全、存在性、大小、修改时间与 SHA-256
uv run python scripts/verify_mangas.py            # 校验全部
uv run python scripts/verify_mangas.py --id 350234  # 仅校验指定漫画（可重复）
```

维护说明：

- 备份文件保留最近 10 份且总占用不超过 512MB，超出后每日清理最旧文件，
  记录行长期保留并标记 `deleted`；
- 校验只标记状态（`missing` / `corrupted` / `invalid_path`），不会自动删除或重新下载，
  删除请走删除命令，重新下载请走下载命令；
- 任务与审计默认分别保留 180 天与 365 天，删除、权限、配置、安全类审计长期保留；
- 以上扫描 / 修复 / 备份 / 校验操作也可在 WebUI「维护」页完成（需登录，默认仅本机可访问）。
