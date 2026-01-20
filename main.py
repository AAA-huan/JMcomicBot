import sys
from src.bot import MangaBot
from src.logging.logger_config import logger


def main() -> None:
    """
    JMComic QQ机器人主入口函数
    
    负责初始化并启动MangaBot机器人，处理异常和安全关闭
    """
    try:
        # 创建机器人实例
        bot = MangaBot()
        
        # 设置信号处理器以实现安全关闭
        bot.handle_safe_close()
        
        # 启动机器人
        bot.run()
        
    except KeyboardInterrupt:
        # 用户手动中断程序
        logger.info("用户手动中断程序")
        print("\n程序被用户中断，正在退出...")
        sys.exit(0)
        
    except Exception as e:
        # 捕获并记录其他异常
        logger.error(f"程序运行时发生未捕获的异常: {e}", exc_info=True)
        print(f"程序运行时发生错误: {e}")
        print("请查看日志文件获取详细信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
