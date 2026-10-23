"""数据库维护操作的进程内互斥锁。

导出与导入都会复制或替换 `main.db`，必须串行执行避免读到半替换文件。
锁独立成模块，保证不同维护服务取得同一把锁。
"""

from threading import Lock

DATABASE_MAINTENANCE_LOCK = Lock()
