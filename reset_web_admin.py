"""WebUI 管理员重置脚本（忘记密码时的受控恢复）

删除 web_admin 与 web_session 表中的全部记录，使 WebUI 回到未初始化状态，
随后从本机访问 WebUI 会重新进入「首次设置」流程。只影响 WebUI 登录记录，
不影响漫画数据、下载文件与 QQ 功能。

建议先停止机器人再执行；必须显式传入 --yes 才会真正删除。

用法:
    uv run python reset_web_admin.py --yes
"""

import argparse
import sys

from sqlalchemy import delete

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.models import WebAdmin, WebSession
from src.logging.logger_config import logger


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="重置 WebUI 管理员：删除管理员与会话记录，重新进入首次设置"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行重置；缺省时只输出提示并退出",
    )
    return parser.parse_args()


def main() -> None:
    """执行 WebUI 管理员重置的主入口"""
    args = parse_args()
    if not args.yes:
        logger.warning("该操作会清除 WebUI 管理员与会话记录；确认后使用 --yes 执行")
        sys.exit(2)

    config_manager = ConfigManager()
    config_manager.load_config()
    db_path = str(config_manager.get("DB_PATH"))

    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    try:
        with db_manager.get_session() as session:
            session.execute(delete(WebSession))
            session.execute(delete(WebAdmin))
            session.commit()
        logger.info("WebUI 管理员与会话已清除")
        logger.info("重新启动机器人后，从本机访问 WebUI 即可重新完成首次设置")
    except Exception as error:
        logger.error(f"重置 WebUI 管理员失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
