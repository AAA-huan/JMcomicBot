import json
import threading
import time
import os
import logging
import websocket
import requests
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv
import jmcomic

class MangaBot:
    def __init__(self):
        # 加载环境变量
        load_dotenv()
        
        # 初始化配置
        self.config = {
            'MANGA_DOWNLOAD_PATH': os.getenv('MANGA_DOWNLOAD_PATH', './downloads'),
            'NAPCAT_WS_URL': os.getenv('NAPCAT_WS_URL', 'ws://localhost:8080/qq'),
            'FLASK_HOST': os.getenv('FLASK_HOST', '0.0.0.0'),
            'FLASK_PORT': int(os.getenv('FLASK_PORT', '20010')),
            'API_TOKEN': os.getenv('API_TOKEN', '')
        }
        
        # 初始化属性
        self.app = Flask(__name__)
        self.ws = None  # WebSocket连接对象
        self.SELF_ID = None  # 存储机器人自身的QQ号
        self.downloading_mangas = {}  # 跟踪正在下载的漫画 {manga_id: True}
        
        # 配置日志
        self._setup_logger()
        
        # 创建下载目录
        os.makedirs(self.config['MANGA_DOWNLOAD_PATH'], exist_ok=True)
        
        # 注册Flask路由
        self._register_routes()
    
    def _setup_logger(self):
        # 创建logger对象
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        # 阻止日志消息向上传播到父logger，避免重复输出
        self.logger.propagate = False
        
        # 定义ANSI颜色代码
        class ColoredFormatter(logging.Formatter):
            # ANSI颜色代码
            COLORS = {
                'DEBUG': '\033[36m',  # 青色
                'INFO': '\033[34m',   # 蓝色
                'WARNING': '\033[33m', # 黄色
                'ERROR': '\033[31m',   # 红色
                'CRITICAL': '\033[41m\033[37m', # 红色背景白色文字
                'RESET': '\033[0m'     # 重置
            }
            
            def format(self, record):
                # 获取原始日志格式
                log_message = super().format(record)
                # 根据日志级别添加颜色
                color_start = self.COLORS.get(record.levelname, '')
                color_end = self.COLORS['RESET']
                # 返回带颜色的日志
                return f"{color_start}{log_message}{color_end}"
        
        # 创建文件格式化器（无颜色）
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # 创建控制台格式化器（有颜色）
        console_formatter = ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        
        # 创建文件处理器，每天一个日志文件
        log_dir = 'logs'
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'{time.strftime("%Y-%m-%d")}.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        
        # 清除已有的处理器
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # 添加处理器到logger
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        
        # 重新定义根logger以确保所有模块的日志也被捕获
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        if root_logger.handlers:
            root_logger.handlers.clear()
        # 为root logger创建新的处理器实例，避免与self.logger共享处理器
        root_console_handler = logging.StreamHandler()
        root_console_handler.setLevel(logging.INFO)
        root_console_handler.setFormatter(console_formatter)
        
        root_file_handler = logging.FileHandler(log_file, encoding='utf-8')
        root_file_handler.setLevel(logging.DEBUG)
        root_file_handler.setFormatter(file_formatter)
        
        root_logger.addHandler(root_console_handler)
        root_logger.addHandler(root_file_handler)
    
    def _register_routes(self):
        # Flask路由，用于接收HTTP事件（如果NapCat配置了HTTP上报）
        @self.app.route('/', methods=['POST'])
        @self._check_token()
        def handle_http_event():
            data = request.json
            self.logger.info(f"收到HTTP事件: {data}")
            self.handle_event(data)
            return jsonify({'status': 'ok'})
    
    def _check_token(self):
        # 检查Token的装饰器
        def decorator(f):
            def wrapper(*args, **kwargs):
                # 如果配置了Token验证
                if self.config['API_TOKEN']:
                    # 从请求头获取Token
                    token = request.headers.get('Authorization')
                    if token and token.startswith('Bearer '):
                        token = token[7:]  # 去掉 'Bearer ' 前缀
                    else:
                        token = request.headers.get('token')
                    
                    # 验证Token
                    if token != self.config['API_TOKEN']:
                        self.logger.warning("Token验证失败")
                        abort(401, description="Token验证失败")
                return f(*args, **kwargs)
            return wrapper
        return decorator
    
    def send_message(self, user_id, message, group_id=None, private=True):
        # 发送消息函数
        try:
            if private:
                # 发送私聊消息
                payload = {
                    "action": "send_private_msg",
                    "params": {
                        "user_id": user_id,
                        "message": message
                    }
                }
            else:
                # 发送群消息
                payload = {
                    "action": "send_group_msg",
                    "params": {
                        "group_id": group_id,
                        "message": message
                    }
                }
            
            # 如果配置了Token，添加到请求中
            if self.config['API_TOKEN']:
                payload['params']['access_token'] = self.config['API_TOKEN']
            
            # 通过WebSocket发送消息
            if self.ws and self.ws.sock and self.ws.sock.connected:
                message_json = json.dumps(payload)
                self.ws.send(message_json)
                self.logger.info(f"消息发送成功: {message[:20]}...")
            else:
                self.logger.warning("WebSocket连接未建立，消息发送失败")
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
    
    def send_file(self, user_id, file_path, group_id=None, private=True):
        # 发送文件函数
        try:
            # 添加详细调试日志
            self.logger.debug(f"准备发送文件: {file_path}, 用户ID: {user_id}, 群ID: {group_id}, 私聊模式: {private}")
            
            if not os.path.exists(file_path):
                self.logger.error(f"文件不存在: {file_path}")
                error_msg = f"❌ 文件不存在哦~，请让我下载之后再发送(｡•﹃•｡)"
                self.send_message(user_id, error_msg, group_id, private)
                return
            
            # 检查文件是否可读
            if not os.access(file_path, os.R_OK):
                self.logger.error(f"文件不可读: {file_path}")
                error_msg = f"❌ 文件不可读，叫主人帮我检查一下吧∑(O_O；)"
                self.send_message(user_id, error_msg, group_id, private)
                return
            
            # 获取文件名
            file_name = os.path.basename(file_path)
            self.logger.debug(f"文件名: {file_name}, 文件路径: {file_path}")
            
            # 直接使用消息段数组方式发送文件，这是NapCat支持的方式
            self.logger.info(f"使用消息段数组方式发送文件")
            
            # 构建消息段数组
            message_segments = [
                {
                    "type": "file",
                    "data": {
                        "file": file_path,
                        "name": file_name
                    }
                }
            ]
            
            # 发送消息
            if private:
                payload = {
                    "action": "send_private_msg",
                    "params": {
                        "user_id": user_id,
                        "message": message_segments
                    }
                }
            else:
                payload = {
                    "action": "send_group_msg",
                    "params": {
                        "group_id": group_id,
                        "message": message_segments
                    }
                }
            
            if self.config['API_TOKEN']:
                payload['params']['access_token'] = self.config['API_TOKEN']
            
            if self.ws and self.ws.sock and self.ws.sock.connected:
                message_json = json.dumps(payload)
                self.logger.debug(f"发送消息段数组文件: {message_json}")
                self.ws.send(message_json)
                self.logger.info(f"使用消息段数组发送文件请求已发送: {file_name}")
                # 等待一小段时间让API请求有机会返回结果
                time.sleep(1)
            else:
                self.logger.warning("WebSocket连接未建立，文件发送失败")
                raise Exception("WebSocket连接未建立")
                
        except Exception as e:
            self.logger.error(f"发送文件失败: {e}")
            error_msg = f"❌ 发送文件失败: {str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.send_message(user_id, error_msg, group_id, private)
    
    def on_message(self, ws, message):
        # WebSocket消息处理函数
        try:
            self.logger.info(f"收到WebSocket消息: {message[:100]}...")
            data = json.loads(message)
            # 处理接收到的消息
            self.handle_event(data)
        except Exception as e:
            self.logger.error(f"处理WebSocket消息出错: {e}")
    
    def on_close(self, ws, close_status_code, close_msg):
        # WebSocket连接关闭处理
        self.logger.info(f"WebSocket连接已关闭: {close_status_code} - {close_msg}")
    
    def on_error(self, ws, error):
        # WebSocket连接错误处理
        self.logger.error(f"WebSocket连接错误: {error}")
    
    def on_open(self, ws):
        # WebSocket连接打开处理
        self.logger.info("WebSocket连接已打开")
    
    def connect_websocket(self):
        # 连接WebSocket的函数
        try:
            self.logger.info(f"正在连接WebSocket: {self.config['NAPCAT_WS_URL']}")
            self.ws = websocket.WebSocketApp(
                self.config['NAPCAT_WS_URL'],
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # 启动WebSocket线程，添加重连选项
            threading.Thread(
                target=lambda: self.ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=5),
                daemon=True
            ).start()
            self.logger.info("WebSocket连接启动成功，将自动尝试重连")
        except Exception as e:
            self.logger.error(f"连接WebSocket失败: {e}")
    
    def websocket_reconnect_manager(self):
        # WebSocket重连管理线程
        while True:
            time.sleep(10)  # 每10秒检查一次连接状态
            
            if self.ws and (not self.ws.sock or not self.ws.sock.connected):
                self.logger.info("检测到WebSocket未连接，尝试重新连接...")
                try:
                    # 关闭现有连接
                    if self.ws:
                        self.ws.close()
                    # 重新连接
                    self.connect_websocket()
                except Exception as e:
                    self.logger.error(f"重连WebSocket失败: {e}")
    
    def handle_event(self, data):
        # 事件处理函数
        # 调试日志，记录所有收到的事件
        self.logger.debug(f"收到事件: {data.get('post_type')}, {data.get('meta_event_type') or data.get('message_type')}")
        
        # 直接从消息的根级别获取self_id
        if 'self_id' in data and data['self_id']:
            if not self.SELF_ID or self.SELF_ID != data['self_id']:
                self.SELF_ID = data['self_id']
                self.logger.info(f"从消息中获取到自身ID: {self.SELF_ID}")
        
        # 处理元事件
        if data.get('post_type') == 'meta_event':
            return
        
        # 处理私聊消息（私聊消息无需@）
        if data.get('post_type') == 'message' and data.get('message_type') == 'private':
            user_id = data.get('user_id')
            message = data.get('raw_message')
            self.logger.info(f"收到私聊消息 - 用户{user_id}: {message}")
            # 确保私聊消息始终被处理，不检查@
            try:
                self.handle_command(user_id, message, private=True)
                self.logger.debug(f"私聊消息处理完成 - 用户{user_id}")
            except Exception as e:
                self.logger.error(f"处理私聊消息时出错: {e}")
                # 即使出错也尝试通知用户
                try:
                    self.send_message(user_id, f"处理消息时出错: {str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ", private=True)
                except:
                    pass  # 避免嵌套异常
        # 处理群消息（需要被@才回应）
        elif data.get('post_type') == 'message' and data.get('message_type') == 'group':
            group_id = data.get('group_id')
            user_id = data.get('user_id')
            message = data.get('raw_message')
            message_content = data.get('message', '')
            
            self.logger.info(f"收到群消息 - 群{group_id} 用户{user_id}: {message}")
            
            # 检查是否被@
            at_self = False
            
            # 简化@检测逻辑
            if self.SELF_ID:
                # 方法1：检查raw_message中是否包含@机器人信息
                if f"@{self.SELF_ID}" in message or f"[CQ:at,qq={self.SELF_ID}]" in message:
                    at_self = True
                self.logger.debug(f"SELF_ID: {self.SELF_ID}, 被@状态: {at_self}")
            else:
                self.logger.warning("SELF_ID未初始化，无法检测@状态")
            
            # 如果没有被@，则不处理消息
            if not at_self:
                self.logger.debug("未被@，忽略消息")
                return
            
            # 如果被@，移除@部分，只保留命令内容
            # 移除CQ码格式的@
            message = message.replace(f"[CQ:at,qq={self.SELF_ID}]", "")
            # 移除纯文本格式的@
            message = message.replace(f"@{self.SELF_ID}", "")
            # 移除多余的空格
            message = message.strip()
            
            self.logger.info(f"收到群消息并被@ - 群{group_id} 用户{user_id}: {message}")
            self.handle_command(user_id, message, group_id=group_id, private=False)
    
    def handle_command(self, user_id, message, group_id=None, private=True):
        # 命令处理函数
        # 确保message不为None
        if message is None:
            self.logger.warning("收到空消息，忽略处理")
            self.send_message(user_id, "(｡•﹃•｡)叽里咕噜说什么呢，听不懂。\n发送漫画帮助看看我怎么用吧！", group_id, private)
            return
            
        # 提取命令和参数
        command_parts = message.strip().split(' ', 1)
        cmd = command_parts[0].lower() if command_parts else ''
        args = command_parts[1] if len(command_parts) > 1 else ''
        
        self.logger.debug(f"处理命令 - 用户{user_id}: 命令='{cmd}', 参数='{args}', 私聊={private}")
        
        # 帮助命令
        if cmd in ['manga_help', '漫画帮助', '帮助漫画']:
            self.send_help(user_id, group_id, private)
        # 漫画下载命令
        elif cmd in ['manga', '漫画下载', '下载漫画']:
            self.handle_manga_download(user_id, args, group_id, private)
        # 发送已下载漫画命令
        elif cmd in ['发送']:
            self.handle_manga_send(user_id, args, group_id, private)
        # 查询已下载漫画列表命令
        elif cmd in ['漫画列表', '列表漫画', 'list']:
            self.query_downloaded_manga(user_id, group_id, private)
        # 查询指定漫画ID是否已下载
        elif cmd in ['查询漫画', '漫画查询', 'checkmanga']:
            self.query_manga_existence(user_id, args, group_id, private)
        # 测试命令，显示当前SELF_ID状态
        elif cmd in ['测试id', 'testid', 'selfid']:
            # 测试命令，显示机器人当前的SELF_ID状态
            if self.SELF_ID:
                self.send_message(user_id, f"✅ 机器人ID: {self.SELF_ID}", group_id, private)
            else:
                self.send_message(user_id, "❌ 机器人ID未获取", group_id, private)
        elif cmd in ['测试文件', 'testfile']:
            # 测试文件发送功能
            self.send_message(user_id, "🔍 开始测试文件发送功能...", group_id, private)
            
            # 创建一个简单的测试文件
            test_file_path = os.path.join(os.getcwd(), "test_file.txt")
            try:
                with open(test_file_path, "w", encoding="utf-8") as f:
                    f.write("这是一个测试文件，用于验证机器人的文件发送功能。\n")
                    f.write(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"机器人ID: {self.SELF_ID or '未获取'}\n")
                
                self.send_message(user_id, f"📄 已创建测试文件: {test_file_path}", group_id, private)
                self.send_message(user_id, "🚀 开始发送测试文件...", group_id, private)
                
                # 发送测试文件
                self.send_file(user_id, test_file_path, group_id, private)
                
                # 清理测试文件
                if os.path.exists(test_file_path):
                    os.remove(test_file_path)
                    self.logger.debug(f"已清理测试文件: {test_file_path}")
                    
            except Exception as e:
                self.logger.error(f"创建测试文件失败: {e}")
                self.send_message(user_id, f"❌ 创建测试文件失败: {str(e)}", group_id, private)
        # 欢迎消息
        elif any(keyword in message.lower() for keyword in ['你好', 'hi', 'hello', '在吗']):
            response = "你好！我是高性能JM机器人૮₍♡>𖥦<₎ა，可以帮你下载JMComic的漫画哦~~~\n输入 '漫画帮助' 就可以查看我的使用方法啦~"
            self.send_message(user_id, response, group_id, private)
    
    def query_downloaded_manga(self, user_id, group_id, private):
        # 查询已下载的漫画
        try:
            # 检查下载目录是否存在
            if not os.path.exists(self.config['MANGA_DOWNLOAD_PATH']):
                self.send_message(user_id, "❌ 下载目录不存在！\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ", group_id, private)
                return
            
            # 查找所有PDF格式的文件
            pdf_files = []
            for file_name in os.listdir(self.config['MANGA_DOWNLOAD_PATH']):
                if file_name.endswith(".pdf"):
                    # 提取文件名（不含扩展名）
                    name_without_ext = os.path.splitext(file_name)[0]
                    pdf_files.append(name_without_ext)
            
            # 根据漫画ID进行排序
            pdf_files.sort()
            
            # 构建回复消息
            if not pdf_files:
                response = "📚↖(^ω^)↗ 目前没有已下载的漫画PDF文件！\n把你们珍藏的车牌号都统统交给我吧~~~"
            else:
                response = "📚 已下载的漫画列表：\n\n"
                # 每5个漫画为一组显示
                for i in range(0, len(pdf_files), 5):
                    group = pdf_files[i:i+5]
                    response += "\n".join([f"{j+1}. {name}" for j, name in enumerate(group, start=i)])
                    response += "\n\n"
                
                response += f"总计：{len(pdf_files)} 个漫画PDF文件"
            
            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"查询已下载漫画出错: {e}")
            self.send_message(user_id, f"❌ 查询失败了(｡•﹃•｡)：{str(e)}", group_id, private)
    
    def query_manga_existence(self, user_id, manga_id, group_id, private):
        # 查询指定漫画ID是否已下载或正在下载
        try:
            if not manga_id:
                self.send_message(user_id, "请输入漫画ID，例如：查询漫画 422866", group_id, private)
                return
                
            # 检查下载目录是否存在
            if not os.path.exists(self.config['MANGA_DOWNLOAD_PATH']):
                self.send_message(user_id, "❌ 下载目录不存在！快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ", group_id, private)
                return
            
            # 首先检查是否正在下载
            if manga_id in self.downloading_mangas:
                response = f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。"
                self.send_message(user_id, response, group_id, private)
                return
            
            # 查找是否存在对应的PDF文件
            found = False
            found_files = []
            
            # 遍历所有PDF文件
            for file_name in os.listdir(self.config['MANGA_DOWNLOAD_PATH']):
                if file_name.endswith(".pdf"):
                    # 检查文件名是否包含该漫画ID
                    name_without_ext = os.path.splitext(file_name)[0]
                    # 检查文件名是否以ID开头或包含ID-格式
                    if name_without_ext.startswith(manga_id + "-") or name_without_ext == manga_id:
                        found = True
                        found_files.append(name_without_ext)
            
            # 构建回复消息
            if found:
                response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 已经下载好啦！\n\n"
                response += "找到以下文件：\n"
                for i, file_name in enumerate(found_files, 1):
                    response += f"{i}. {file_name}\n"
            else:
                response = f"❌（｀Δ´）！ 漫画ID {manga_id} 还没有下载！"
            
            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"查询漫画存在性出错: {e}")
            self.send_message(user_id, f"❌ 查询失败：{str(e)}快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ", group_id, private)
    
    def send_help(self, user_id, group_id, private):
        # 发送帮助信息
        help_text = "📚 本小姐的帮助 📚\n\n"
        
        # 群聊中添加@说明
        if not private:
            help_text += "⚠️ 在群聊中请先@我再发送命令！\n\n"
        
        help_text += "💡 可用命令：\n"
        help_text += "- 漫画下载 <漫画ID>：下载指定ID的漫画\n"
        help_text += "- 发送 <漫画ID>：发送指定ID的已下载漫画（只支持PDF格式）\n"
        help_text += "- 查询漫画 <漫画ID>：查询指定ID的漫画是否已下载\n"
        help_text += "- 漫画列表：查询已下载的所有漫画\n"
        help_text += "- 漫画帮助：显示此帮助信息\n\n"
        help_text += "⚠️ 注意事项：\n"
        help_text += "- 命令与漫画ID之间记得加空格\n"
        help_text += "- 请确保输入正确的漫画ID\n"
        help_text += "- 下载过程可能需要一些时间，请耐心等待\n"
        help_text += "- 下载的漫画将保存在配置的目录中\n"
        help_text += "- 发送漫画前请确保该漫画已成功下载并转换为PDF格式\n"
        help_text += "- 当前版本只支持发送PDF格式的漫画文件"
        self.send_message(user_id, help_text, group_id, private)
    
    def handle_manga_download(self, user_id, manga_id, group_id, private):
        # 处理漫画下载
        if not manga_id:
            response = "请输入漫画ID，例如：漫画下载 422866"
            self.send_message(user_id, response, group_id, private)
            return
        
        # 在下载前先检查漫画是否已存在
        try:
            # 检查下载目录是否存在
            if not os.path.exists(self.config['MANGA_DOWNLOAD_PATH']):
                # 目录不存在，需要创建并继续下载
                os.makedirs(self.config['MANGA_DOWNLOAD_PATH'], exist_ok=True)
                self.logger.info(f"创建下载目录: {self.config['MANGA_DOWNLOAD_PATH']}")
            else:
                # 查找是否存在对应的PDF文件
                found = False
                found_files = []
                
                # 遍历所有PDF文件
                for file_name in os.listdir(self.config['MANGA_DOWNLOAD_PATH']):
                    if file_name.endswith(".pdf"):
                        # 检查文件名是否包含该漫画ID
                        name_without_ext = os.path.splitext(file_name)[0]
                        # 检查文件名是否以ID开头或包含ID-格式
                        if name_without_ext.startswith(manga_id + "-") or name_without_ext == manga_id:
                            found = True
                            found_files.append(name_without_ext)
                
                # 如果已存在，则通知用户
                if found:
                    response = f"✅૮₍ ˶•‸•˶₎ა 漫画ID {manga_id} 已经下载过了！\n\n"
                    response += "找到以下文件：\n"
                    for i, file_name in enumerate(found_files, 1):
                        response += f"{i}. {file_name}\n"
                    response += "\n你可以使用 '发送 {manga_id}' 命令获取该漫画哦~"
                    self.send_message(user_id, response, group_id, private)
                    return
        except Exception as e:
            self.logger.error(f"检查漫画是否已下载时出错: {e}")
            # 检查出错时继续下载，避免因检查失败而影响用户体验
        
        # 发送开始下载的消息
        response = f"开始下载漫画ID：{manga_id}啦~，请稍候..."
        self.send_message(user_id, response, group_id, private)
        
        # 在新线程中下载漫画，避免阻塞
        threading.Thread(target=self.download_manga, args=(user_id, manga_id, group_id, private)).start()
    
    def download_manga(self, user_id, manga_id, group_id, private):
        # 下载漫画函数
        try:
            # 标记该漫画正在下载中
            self.downloading_mangas[manga_id] = True
            
            # 使用jmcomic库下载漫画
            self.logger.info(f"开始下载漫画ID: {manga_id}")
            # 从配置文件创建下载选项对象
            option = jmcomic.create_option_by_file('C:/huan/JMBot/option_example.yml')
            # 确保使用环境变量中的下载路径
            option.dir_rule.base_dir = self.config['MANGA_DOWNLOAD_PATH']
            
            # 设置目录命名规则，将漫画ID和名称组合在同一个文件夹名中
            # 使用f-string格式的规则，这样会创建 {base_dir}/{album_id}-{album_title}/{photo_title} 的目录结构
            # 在jmcomic v2.5.36+版本支持这种语法
            new_rule = 'Bd / {Aid}-{Atitle}'
            from jmcomic.jm_option import DirRule
            # 创建新的DirRule对象并替换原有的
            option.dir_rule = DirRule(new_rule, base_dir=option.dir_rule.base_dir)
            
            jmcomic.download_album(manga_id, option=option)
            
            # 查找漫画文件夹 - 简化逻辑，只检查是否以漫画ID开头
            manga_dir = None
            # 直接在基础下载目录下查找
            if os.path.exists(self.config['MANGA_DOWNLOAD_PATH']):
                for dir_name in os.listdir(self.config['MANGA_DOWNLOAD_PATH']):
                    dir_path = os.path.join(self.config['MANGA_DOWNLOAD_PATH'], dir_name)
                    # 检查是否是目录且以漫画ID开头
                    if os.path.isdir(dir_path) and dir_name.startswith(f"{manga_id}-"):
                        manga_dir = dir_path
                        break
            
            # 如果在基础目录没找到，再尝试递归查找（兼容可能的其他情况）
            if not manga_dir:
                for root, dirs, files in os.walk(self.config['MANGA_DOWNLOAD_PATH']):
                    for dir_name in dirs:
                        if dir_name.startswith(f"{manga_id}-"):
                            manga_dir = os.path.join(root, dir_name)
                            break
                    if manga_dir:
                        break
            
            if manga_dir and os.path.exists(manga_dir):
                # 从manga_dir路径中提取文件夹名称
                folder_name = os.path.basename(manga_dir)
                pdf_path = os.path.join(self.config['MANGA_DOWNLOAD_PATH'], f"{folder_name}.pdf")
                import shutil
                import sys
                
                # 安装必要的依赖（如果没有的话）
                try:
                    from PIL import Image
                except ImportError:
                    self.logger.info("正在安装PIL库...")
                    import subprocess
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
                    from PIL import Image
                
                # 收集所有图片文件
                image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
                image_files = []
                
                for root, _, files in os.walk(manga_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in image_extensions):
                            image_files.append(os.path.join(root, file))
                
                # 按文件名排序
                image_files.sort()
                
                if not image_files:
                    self.logger.warning(f"在漫画文件夹中未找到图片文件: {manga_dir}")
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到图片文件，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件"
                    self.send_message(user_id, response, group_id, private)
                    return
                
                self.logger.info(f"找到 {len(image_files)} 个图片文件，开始转换为PDF")
                
                # 转换为PDF
                try:
                    # 打开第一张图片作为PDF的第一页
                    first_image = Image.open(image_files[0])
                    # 确保图片为RGB模式
                    if first_image.mode == 'RGBA':
                        first_image = first_image.convert('RGB')
                    
                    # 准备其他图片
                    other_images = []
                    for img_path in image_files[1:]:
                        img = Image.open(img_path)
                        # 确保图片为RGB模式
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        other_images.append(img)
                    
                    # 保存为PDF
                    first_image.save(pdf_path, save_all=True, append_images=other_images)
                    self.logger.info(f"成功将漫画 {manga_id} 转换为PDF: {pdf_path}")
                    
                    # 删除原漫画文件夹
                    self.logger.info(f"删除原漫画文件夹: {manga_dir}")
                    shutil.rmtree(manga_dir)
                    
                    response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 下载并转换为PDF完成！\n\n友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                except Exception as pdf_error:
                    self.logger.error(f"转换为PDF失败: {pdf_error}")
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成，但转换为PDF失败: {str(pdf_error)}\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"
            else:
                response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到漫画文件夹，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"
                
            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"下载漫画出错: {e}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.send_message(user_id, error_msg, group_id, private)
        finally:
            # 下载完成或失败后，移除正在下载的标记
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]
    
    def handle_manga_send(self, user_id, manga_id, group_id, private):
        # 处理漫画发送
        if not manga_id:
            response = "请输入漫画ID，例如：发送 422866"
            self.send_message(user_id, response, group_id, private)
            return
        
        # 发送开始发送的消息
        response = f"ฅ( ̳• ·̫ • ̳ฅ)正在查找并准备发送漫画ID：{manga_id}，请稍候..."
        self.send_message(user_id, response, group_id, private)
        
        # 在新线程中处理文件发送，避免阻塞
        threading.Thread(target=self.send_manga_files, args=(user_id, manga_id, group_id, private)).start()
    
    def send_manga_files(self, user_id, manga_id, group_id, private):
        # 发送漫画文件函数 - 只发送PDF文件
        try:
            # 首先检查是否正在下载
            if manga_id in self.downloading_mangas:
                response = f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。\n\n你可以使用 '查询漫画 {manga_id}' 命令检查下载状态。"
                self.send_message(user_id, response, group_id, private)
                return
                
            # 检查是否有PDF文件，查找以漫画ID开头的PDF文件
            pdf_path = None
            if os.path.exists(self.config['MANGA_DOWNLOAD_PATH']):
                for file_name in os.listdir(self.config['MANGA_DOWNLOAD_PATH']):
                    if file_name.startswith(f"{manga_id}-") and file_name.endswith(".pdf"):
                        pdf_path = os.path.join(self.config['MANGA_DOWNLOAD_PATH'], file_name)
                        break
            
            if pdf_path and os.path.exists(pdf_path):
                # 发送PDF文件
                self.logger.info(f"找到PDF文件: {pdf_path}")
                self.send_message(user_id, f"找到漫画PDF文件，开始发送...", group_id, private)
                self.send_file(user_id, pdf_path, group_id, private)
                self.send_message(user_id, "✅ฅ( ̳• ·̫ • ̳ฅ) 漫画PDF发送完成！", group_id, private)
                return
            else:
                # 未找到PDF文件的情况
                error_msg = f"❌( っ`-´c)ﾏ 未找到漫画ID {manga_id} 的PDF文件，请先下载该漫画并确保已转换为PDF格式"
                self.send_message(user_id, error_msg, group_id, private)
                return
            
        except Exception as e:
            self.logger.error(f"发送漫画出错: {e}")
            error_msg = f"❌ 发送失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.send_message(user_id, error_msg, group_id, private)
    
    def start_flask(self):
        # 启动Flask服务的函数
        self.app.run(host=self.config['FLASK_HOST'], port=self.config['FLASK_PORT'], debug=False)
    
    def run(self):
        # 运行机器人主函数
        self.logger.info("JMComic下载机器人启动中...")
        
        # 启动Flask服务线程
        threading.Thread(target=self.start_flask, daemon=True).start()
        
        # 连接WebSocket
        self.connect_websocket()
        
        # 启动WebSocket重连管理线程
        threading.Thread(target=self.websocket_reconnect_manager, daemon=True).start()
        
        # 保持主程序运行
        while True:
            time.sleep(1)

# 如果直接运行此文件
if __name__ == "__main__":
    # 创建机器人实例
    bot = MangaBot()
    # 运行机器人
    bot.run()