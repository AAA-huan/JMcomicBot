# 维护脚本使用指南

命令在项目根目录（包含 `main.py`、`pyproject.toml`）执行，使用已部署的 uv 环境。维护不需要额外安装开发工具、数据库命令行工具或 PDF 转换软件。

| 脚本 | 用途 | 参数 |
|---|---|---|
| `backup_database.py` | 创建数据库一致性备份 | 无业务参数 |
| `scan_mangas.py` | 登记本地 PDF，按需补全详情和页数 | `--dry-run`、`--enrich`、`--read-pages`、`--check-chapters` |
| `repair_mangas.py` | 标记缺失漫画，清理无关联的孤儿标签 | `--dry-run` |
| `verify_mangas.py` | 校验登记文件的路径、存在性与摘要 | `--id <漫画ID>`，可重复 |
| `reset_web_admin.py` | 重置 WebUI 管理员与登录会话 | `--yes` |

## 配置与运行方式

- 脚本读取项目 `.env`：`MANGA_DOWNLOAD_PATH` 默认 `./downloads`，`DB_PATH` 默认 `./data`（内含 `main.db`），`BACKUP_PATH` 默认 `./data/backups`。确认使用与机器人相同的配置，避免维护另一份数据库。
- 普通部署命令使用 `uv run --no-dev`，无需激活虚拟环境或重新运行 pip。若按平台指南固定使用 uv 托管 Python 3.12，可将本文命令前缀换成 `uv run --no-dev --managed-python --python 3.12`，Android/proot 建议使用这个前缀。
- `--enrich` 读取项目根目录的 `option.yml`，配置缺失或无效会报错。其他维护操作不需要用它查询站点；机器人下载仍需要该文件。
- 脚本会初始化数据库并执行必要迁移；有旧库需要升级时，生成 `main.db.pre-migration.bak`。因此 `--dry-run` 表示不执行本次扫描或修复的业务写入，不保证首次初始化和迁移完全不写磁盘。
- 扫描、修复、校验和备份也可在 WebUI「维护」页执行，二者共用服务；管理员重置由命令行执行。

## 备份数据库

```bash
uv run --no-dev python scripts/backup_database.py
```

使用 SQLite backup API 生成一致性备份，保存到 `BACKUP_PATH` 并登记备份记录与任务审计。文件名包含时间和数据库迁移版本；迁移前的 `.pre-migration.bak` 不属于这里的备份记录。

备份仅包含数据库，漫画 PDF 与 `.env`、`option.yml` 需另行保管。操作失败会打印原因并以非零状态退出。

## 扫描漫画并补全信息

扫描 `MANGA_DOWNLOAD_PATH` **顶层**的 PDF，根据文件名识别漫画 ID。支持 `漫画ID-标题(章节数章).pdf`、`漫画ID-标题.pdf` 和 `漫画ID.pdf`，不能识别的文件名会记录并跳过。

```bash
# 查看将登记或修改的内容
uv run --no-dev python scripts/scan_mangas.py --dry-run

# 扫描并登记文件
uv run --no-dev python scripts/scan_mangas.py

# 预览在线详情补全和本地实际页数
uv run --no-dev python scripts/scan_mangas.py --dry-run --enrich --read-pages

# 实际补全，并逐章查询在线图片数
uv run --no-dev python scripts/scan_mangas.py --enrich --read-pages --check-chapters
```

| 参数 | 行为 |
|---|---|
| `--dry-run` | 展示字段旧值、新值与来源，不写本次漫画、文件、扫描任务及统计 |
| `--enrich` | 查询标题、全部作者、标签、简介、在线章节列表和站点总页数，不下载图片；与预览合用仍会联网 |
| `--read-pages` | 解析本地最终 PDF 的实际页数，不渲染图片；损坏、加密或无页文件明确报告并跳过该漫画 |
| `--check-chapters` | 必须同时启用 `--enrich`；逐章查询图片数量并检查各章之和，增加网络请求 |

站点当前章节数、页数和章节列表独立保存，不覆盖本地已下载章节数或 PDF 实际页数。扫描只有开启 `--read-pages` 才会纠正本地页数；阅读器打开 PDF 后也会同步实际页数。无效日期占位值不作为有效日期保存。

同 ID 有多个 PDF 时，保留已登记且仍在候选中的文件；没有明确候选的漫画会跳过并列出文件名，整理后重扫。不自动删除重复文件，也不以最后扫描到的文件覆盖登记。

结果包含新增、更新、无需更新、跳过、重复文件漫画数，以及在线详情成功/失败、PDF 读取失败和章节查询失败数量。单本联网失败会报告原因并继续其他漫画的处理；部分章节查询失败时不生成“完整逐章页数”。没有变化的文件保留既有校验信息。

扫描还会将数据库中有记录、磁盘已不存在的漫画标记为缺失；整个下载目录为空时，扫描不会批量标记缺失，可先核对目录配置，再使用修复预览。

## 修复资料记录

```bash
uv run --no-dev python scripts/repair_mangas.py --dry-run
uv run --no-dev python scripts/repair_mangas.py
```

预览列出待标记缺失的漫画 ID 和待清理的孤儿标签，核对后去掉 `--dry-run` 执行。修复只更新资料记录，不删除漫画 PDF，也不补登新文件；新增文件使用扫描功能。

下载目录配置错误也会影响差异判断，执行前确认该目录可访问。原有已删除漫画记录保留，供漫画库的“已删除”筛选查看。

## 校验文件登记信息

```bash
uv run --no-dev python scripts/verify_mangas.py
uv run --no-dev python scripts/verify_mangas.py --id 350234
uv run --no-dev python scripts/verify_mangas.py --id 350234 --id 350235
```

缺省校验全部登记文件，`--id` 可多次指定。结果包含正常、缺失、损坏、路径异常和读取错误；校验不会自动删除或重新下载漫画。

| 文件状态 | 含义 / 处理 |
|---|---|
| `ready` | 本次校验通过 |
| `missing` | 登记文件不存在，核对目录或重新下载 |
| `corrupted` | 文件大小、修改时间未变化，但已登记 SHA-256 与实际摘要不符；保留旧摘要，检查文件或重新下载 |
| `invalid_path` | 路径越界、类型不符合要求等，核对文件登记和下载目录 |

首次校验没有摘要时会登记当前摘要。文件大小或修改时间变化时，当前实现会重新登记摘要，不把这两种变化单独判为损坏。此操作校验登记信息，不能证明 PDF 内容完整或可阅读；读取页数使用扫描的 `--read-pages`，实际阅读可在 WebUI 检查。

## 重置 WebUI 管理员

忘记密码时，先停止机器人，再执行：

```bash
uv run --no-dev python scripts/reset_web_admin.py --yes
```

没有 `--yes` 时只显示提示并以退出码 2 退出。确认执行后清除管理员、管理员关联 QQ 信息及登录会话；漫画数据和下载文件保留。重启机器人，再从本机打开 WebUI 完成首次设置，并按需重新关联 QQ。

## 记录保留

当前 `CleanupService` 的默认行为：

- 任务记录保留 180 天，审计事件保留 365 天。
- 数据库备份最多保留最近 10 份、总计 512 MiB；始终保留最新一份，超限时从最旧文件开始清理。
- 被清理的备份文件记录标记为 `deleted`；迁移前备份不参与这一保留清理。

清理由机器人常规维护流程触发。当前 `.env` 和 WebUI 没有提供这些保留参数的配置入口。

## 常见问题

- **`option.yml` 缺失**：联网扫描和漫画下载需要它，首次部署从 `option_example.yml` 复制；仅本地扫描不需要联网客户端。
- **数据库尚不存在**：脚本会初始化数据库。已有数据库不需要删除，先核对 `DB_PATH`；备份可用上面的备份脚本创建。
- **扫描后页面没更新**：刷新 WebUI，确认机器人和脚本读取同一个 `.env`、下载目录与数据库。
- **站点数量与本地数量不同**：可能是站点新增章节或本地仅有部分内容，查看扫描差异；不会用在线数值覆盖本地实际值。
- **提示重复 PDF**：按结果列出的候选整理文件后重扫。扫描不会猜测哪个文件应覆盖现有漫画。
