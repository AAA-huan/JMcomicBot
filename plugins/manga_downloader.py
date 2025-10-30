from nonebot import on_command, on_message
from nonebot.typing import T_State
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message
import asyncio
import os
import jmcomic
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取下载路径
DOWNLOAD_PATH = os.getenv("MANGA_DOWNLOAD_PATH", "./downloads")

# 创建下载目录
if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

# 创建命令响应器
download_manga = on_command("manga", aliases={"漫画下载", "下载漫画"}, priority=5)

# 帮助命令
help_cmd = on_command("manga_help", aliases={"漫画帮助", "帮助漫画"}, priority=5)

@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    help_text = """
    漫画下载机器人使用说明：
    1. 命令格式：/漫画下载 [漫画ID]
    2. 例如：/漫画下载 422866
    3. 支持的命令：
       - 漫画下载 [ID]：下载指定ID的漫画
       - 漫画帮助：查看帮助信息
    """
    await bot.send(event, help_text.strip())

@download_manga.handle()
async def handle_first_receive(bot: Bot, event: MessageEvent, state: T_State, args: Message = CommandArg()):
    manga_id = args.extract_plain_text().strip()
    if manga_id:
        state["manga_id"] = manga_id

@download_manga.got("manga_id", prompt="请输入要下载的漫画ID")
async def handle_manga_id(bot: Bot, event: MessageEvent, state: T_State):
    manga_id = state["manga_id"]
    
    # 发送开始下载消息
    await bot.send(event, f"开始下载漫画 ID: {manga_id}，请稍候...")
    
    try:
        # 创建配置对象
        class DownloadOption:
            def __init__(self):
                self.download_path = DOWNLOAD_PATH
                self.timeout = 30
        
        option = DownloadOption()
        
        # 使用异步执行同步下载任务
        def download_sync():
            try:
                # 调用jmcomic库下载漫画
                jmcomic.download_album(manga_id)
                return True, f"漫画 {manga_id} 下载完成！"
            except Exception as e:
                return False, f"下载过程中出错: {str(e)}"
        
        # 执行下载并等待完成
        success, message = await asyncio.to_thread(download_sync)
        
        await bot.send(event, message)
        
    except Exception as e:
        await bot.send(event, f"发生未知错误: {str(e)}")

# 监听消息，提供简单的交互
welcome_msg = on_message(priority=100)

@welcome_msg.handle()
async def handle_welcome(bot: Bot, event: MessageEvent):
    message = event.get_plaintext()
    if any(keyword in message for keyword in ["漫画", "manga", "本子"]):
        await welcome_msg.finish("您好！我是漫画下载机器人，请输入 /漫画帮助 查看使用说明。")