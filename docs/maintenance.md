# 🛠️ 维护脚本使用指南

`scripts/` 目录下提供了一组命令行维护脚本，用于备份数据库、扫描入库、修复孤儿记录、校验文件完整性以及重置 WebUI 管理员。这些脚本与 WebUI「维护」页调用同一套服务，命令行场景下可直接使用。

## 📋 脚本清单

| 脚本 | 用途 | 是否写库 | 推荐先 `--dry-run` |
|---|---|---|---|
| `backup_database.py` | 创建数据库一致性备份并登记到 `backup_record` | 是 | 无 dry-run 选项 |
| `scan_mangas.py` | 扫描下载目录，将漫画 PDF 元数据同步入库 | 是（`--dry-run` 除外） | ✅ 推荐 |
| `repair_mangas.py` | 标记孤儿漫画为缺失、删除孤儿标签 | 是（`--dry-run` 除外） | ✅ 必须 |
| `verify_mangas.py` | 校验文件路径、存在性、大小、修改时间与 SHA-256 | 是（仅写校验状态） | 无 dry-run 选项 |
| `reset_web_admin.py` | 清除 WebUI 管理员与会话记录，回到首次设置 | 是 | 需 `--yes` 显式确认 |

## 📌 通用说明

- **运行方式**：所有命令均通过 `uv run python` 在项目根目录执行；若使用传统虚拟环境，把 `uv run python` 换成激活后的 `python` 即可。
- **配置加载**：脚本通过 `ConfigManager` 读取 `.env`，使用 `DB_PATH`（默认 `./data`，文件名 `main.db`）、`MANGA_DOWNLOAD_PATH`（默认 `./downloads`）、`BACKUP_PATH`（默认 `./data/backups`）三项。
- **数据库初始化**：脚本启动时会自动执行版本化迁移，迁移前生成 `main.db.pre-migration.bak` 作为安全网（不属于 `backup_record`）。
- **与 WebUI 的关系**：扫描 / 修复 / 备份 / 校验操作在 WebUI「维护」页同样可完成（需登录，默认仅本机可访问），二者共用底层服务，行为一致。
- **执行时机**：维护脚本会访问数据库，建议**先停止机器人再执行** `reset_web_admin.py` 等写操作；`backup_database.py`、`scan_mangas.py`、`verify_mangas.py` 可在运行时执行，但 `repair_mangas.py` 建议在低负载时段运行。

## 🔧 各脚本详细说明

### 1. backup_database.py — 数据库备份

使用 SQLite backup API 创建一致性备份，文件名形如 `main-日期-时间-版本号.db`，并写入 `backup_record` 与任务审计。

```bash
uv run python scripts/backup_database.py
```

- 备份文件落在 `BACKUP_PATH`（默认 `./data/backups`）。
- 备份记录由 `backup_record` 表登记，迁移前的 `main.db.pre-migration.bak` **不**计入保留清理。
- 失败时会以非零退出码退出并在日志输出 `备份失败: <原因>`。

> ⚠️ 备份只复制数据库文件，不包含 `downloads/` 内的漫画 PDF；漫画文件需另行保管。

### 2. scan_mangas.py — 漫画扫描入库

扫描 `MANGA_DOWNLOAD_PATH` 内的漫画 PDF，将元数据与文件记录同步到数据库。

```bash
uv run python scripts/scan_mangas.py              # 扫描并写入数据库
uv run python scripts/scan_mangas.py --dry-run    # 仅预览将入库的内容，不写入
uv run python scripts/scan_mangas.py --enrich     # 扫描后联网补全作者/标签等元数据
```

| 参数 | 说明 |
|---|---|
| `--dry-run` | 仅预览将入库的漫画，不实际写入数据库 |
| `--enrich` | 扫描后联网补全作者/标签等元数据；与 `--dry-run` 同时使用时联网补全仍会写入 entry（不入库） |

输出统计字段：

- `扫描到 PDF 文件` / `聚合漫画` / `新增` / `更新`
- 预览模式额外输出 `待清理残留`；正式模式输出 `标记缺失`

> 📌 对数据库已有记录仅更新可解析的标题与章节数，保留更完整的元数据；schema 要求一漫画只保留一个最终 PDF，多文件旧数据取最后扫描到的候选。

### 3. repair_mangas.py — 漫画资料修复

扫描下载目录与数据库差异，将磁盘已不存在的漫画标记为缺失，并删除无关联的孤儿标签。

```bash
uv run python scripts/repair_mangas.py --dry-run   # 仅预览差异，不执行任何写入
uv run python scripts/repair_mangas.py             # 确认后执行修复
```

| 参数 | 说明 |
|---|---|
| `--dry-run` | 仅预览差异清单（孤儿漫画 ID、孤儿标签名），不执行任何写入 |

预览输出会列出：

- `待标记缺失漫画: <manga_id>`
- `待删除孤儿标签: <tag_name>`

> ⚠️ 修复前**务必先 `--dry-run` 查看差异清单**，确认无误后再去掉 `--dry-run` 执行。修复只标记缺失与清理孤儿标签，不会删除漫画文件本身。

### 4. verify_mangas.py — 漫画文件校验

逐文件校验下载目录与数据库记录的一致性：路径安全、存在性、大小、修改时间与 SHA-256。

```bash
uv run python scripts/verify_mangas.py                # 校验全部漫画文件
uv run python scripts/verify_mangas.py --id 350234    # 仅校验指定漫画（可重复指定）
uv run python scripts/verify_mangas.py --id 350234 --id 350235
```

| 参数 | 说明 |
|---|---|
| `--id <MANGA_ID>` | 仅校验指定漫画 ID，可重复指定多个 |

输出统计字段：

- `文件` 总数 / `正常` / `缺失` / `损坏` / `路径异常` / `读取错误`

校验只会**标记状态**，不会自动删除或重新下载：

| 状态 | 含义 | 后续处理 |
|---|---|---|
| `missing` | 数据库有记录但磁盘文件不存在 | 走删除命令清理记录，或走下载命令重新下载 |
| `corrupted` | 文件大小 / 修改时间 / SHA-256 与登记值不符 | 走删除命令后重新下载 |
| `invalid_path` | 路径不安全（越界等） | 走删除命令清理 |

> 📌 已有登记值与磁盘不符时标记 `corrupted`，并保留旧摘要便于诊断，不覆盖原值。

### 5. reset_web_admin.py — WebUI 管理员重置（忘记密码）

删除 `web_admin` 与 `web_session` 表中的全部记录，使 WebUI 回到未初始化状态，随后从本机访问 WebUI 会重新进入「首次设置」流程。

```bash
uv run python scripts/reset_web_admin.py --yes
```

| 参数 | 说明 |
|---|---|
| `--yes` | 确认执行重置；缺省时只输出提示并以退出码 2 退出 |

> ⚠️ 该脚本**只影响 WebUI 登录记录**，不会影响漫画数据、下载文件与 QQ 功能。建议**先停止机器人再执行**，完成后重启 `uv run python main.py`，用本机浏览器访问 WebUI 重新完成首次设置。

## 🗄️ 保留策略与状态枚举

### 备份保留

备份文件由 `CleanupService` 按以下规则清理（常量定义于 `src/service/cleanup_service.py`）：

- **永远保留最新一份**；
- 其余备份从最旧开始按数量与空间上限挑出待删除项；
- 保留最近 `BACKUP_KEEP_COUNT = 10` 份；
- 总占用不超过 `BACKUP_MAX_TOTAL_BYTES = 512 MB`；
- 超出上限的最旧文件被标记 `deleted`，记录行长期保留。

### 任务与审计保留

- 任务记录默认保留 `180` 天；
- 审计事件默认保留 `365` 天；
- 清理在机器人运行的常规清理流程中触发，每次清理会写入 `maintenance.cleanup_completed` 审计。

> 以上保留期为 `CleanupService` 默认值，配置化后可在 `.env` / WebUI 调整。

## ❓ 常见问题

- **报错 `option.yml` 缺失**：脚本本身不依赖 `option.yml`，但机器人主进程依赖；若同时启动机器人发现下载静默失败，请确认根目录有 `option.yml`（可从 `option_example.yml` 复制）。
- **脚本提示 `DB_PATH` 不存在**：脚本会自动初始化数据库并执行迁移；若想从空库开始，删除 `./data/main.db` 后再运行即可。
- **扫描入库后 WebUI 未刷新**：WebUI 数据来自同一数据库，刷新页面即可；若仍不刷新，检查浏览器缓存或 WebSocket 连接。
- **校验状态无法自动恢复**：校验只标记，删除请走删除命令，重新下载请走下载命令。
