"""消息管理器，负责发送文本消息和文件"""

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.logging.logger_config import logger


@dataclass
class SendTask:
    """文件发送任务"""

    user_id: str
    file_path: str
    group_id: Optional[str]
    private: bool
    status: str = "pending"  # pending / done / failed
    error: Optional[str] = field(default=None)


class MessageManager:
    """消息管理器，负责发送文本消息和文件"""

    def __init__(self, config: Dict[str, Any], ws_client: Optional[Any] = None) -> None:
        """
        初始化消息管理器

        Args:
            config: 配置字典，包含NAPCAT_TOKEN等信息
            ws_client: WebSocket客户端实例
        """
        self.config = config
        self.ws_client = ws_client
        self.logger = logger
        self._file_queue: queue.Queue = queue.Queue()
        self._queue_running: bool = True
        self._file_thread: Optional[threading.Thread] = None
        # 保护所有ws.send，避免多线程并发写入连接
        self._ws_lock: threading.RLock = threading.RLock()
        # 等待文件发送结果的同步原语
        self._result_cond: threading.Condition = threading.Condition()
        # 连接中断期间未能送达的内容，待连接恢复后补发提醒
        self._pending_errors: List[Dict[str, Any]] = []
        self._pending_errors_lock: threading.Lock = threading.Lock()
        self._start_file_queue_worker()

    def set_websocket_client(self, ws_client: Optional[Any]) -> None:
        """
        设置WebSocket客户端

        Args:
            ws_client: WebSocket客户端实例
        """
        self.ws_client = ws_client

    def stop(self) -> None:
        """停止文件发送队列进程，释放资源"""
        self._queue_running = False
        with self._result_cond:
            self._result_cond.notify_all()
        if self._file_thread is not None:
            self._file_thread.join(timeout=2)
            self.logger.info("文件发送队列进程已停止")

    def _start_file_queue_worker(self) -> None:
        """启动文件发送队列后台线程，串行执行文件发送任务"""

        def process_queue() -> None:
            while self._queue_running:
                try:
                    task = self._file_queue.get(timeout=1)
                except queue.Empty:
                    self._flush_pending_errors()
                    continue

                self._process_send_task(task)
                self._file_queue.task_done()

        self._file_thread = threading.Thread(target=process_queue, daemon=True)
        self._file_thread.start()
        self.logger.info("文件发送队列后台线程已启动")

    def _process_send_task(self, task: SendTask) -> None:
        """处理单个文件发送任务，发送结果通过条件变量通知等待线程"""
        try:
            self._send_file_with_retry(task)
            task.status = "done"
        except Exception as e:
            self.logger.error(f"发送文件失败: {task.file_path}, {e}")
            task.status = "failed"
            task.error = str(e)
            self._store_pending_error(
                user_id=task.user_id,
                content_type="file",
                content=task.file_path,
                group_id=task.group_id,
                private=task.private,
            )
        finally:
            with self._result_cond:
                self._result_cond.notify_all()

    def _send_file_with_retry(self, task: SendTask) -> None:
        """尝试发送文件，连接断开时等待重连并重试，超时抛出异常"""
        payload = self._build_file_payload(
            task.file_path, task.user_id, task.group_id, task.private
        )
        retry_timeout = int(self.config.get("SEND_RETRY_TIMEOUT", 30))
        deadline = time.time() + retry_timeout

        while time.time() < deadline:
            if self.ws_client is None or not self._is_websocket_connected():
                time.sleep(0.5)
                continue
            try:
                with self._ws_lock:
                    self.ws_client.ws.send(json.dumps(payload))
                send_interval = int(self.config.get("FILE_SEND_INTERVAL", 3))
                time.sleep(send_interval)
                return
            except Exception as e:
                self.logger.warning(f"发送文件时连接异常，重试中: {e}")
                time.sleep(0.5)

        raise RuntimeError(
            f"WebSocket连接未建立，文件发送失败: {os.path.basename(task.file_path)}"
        )

    def send_message(
        self,
        user_id: str,
        message: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
        """
        发送文本消息（即时发送，不做文件队列；连接中断时留存等待补发）

        Args:
            user_id: 用户ID
            message: 要发送的消息内容
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊
        """
        self._flush_pending_errors()

        payload = self._build_message_payload(user_id, message, group_id, private)

        if self.ws_client is not None and self._is_websocket_connected():
            with self._ws_lock:
                self.ws_client.ws.send(json.dumps(payload))
            self.logger.info(f"发送成功: {message[:50]}...")
            return

        self.logger.warning("WebSocket连接未建立，消息已留存等待连接恢复后补发")
        self._store_pending_error(
            user_id=user_id,
            content_type="message",
            content=message,
            group_id=group_id,
            private=private,
        )

    def send_file(
        self,
        user_id: str,
        file_path: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
        """
        发送文件（进入文件发送队列串行执行，直到该文件发送完成或失败）

        Args:
            user_id: 用户ID
            file_path: 文件路径
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊

        Raises:
            FileNotFoundError: 当文件不存在时
            PermissionError: 当文件不可读时
            RuntimeError: 当WebSocket连接未建立或发送队列已停止时
        """
        if not self._queue_running:
            error_msg = "文件发送队列已停止"
            self.logger.warning(error_msg)
            raise RuntimeError(error_msg)

        self.logger.debug(
            f"准备发送文件: {file_path}, 用户ID: {user_id}, 群ID: {group_id}, 私聊模式: {private}"
        )

        if not os.path.exists(file_path):
            error_msg = f"文件不存在: {os.path.basename(file_path)}"
            self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        if not os.access(file_path, os.R_OK):
            error_msg = f"文件不可读: {os.path.basename(file_path)}"
            self.logger.error(error_msg)
            raise PermissionError(error_msg)

        task = SendTask(
            user_id=user_id,
            file_path=os.path.abspath(file_path),
            group_id=group_id,
            private=private,
        )
        self._file_queue.put(task)

        with self._result_cond:
            while task.status == "pending":
                self._result_cond.wait(timeout=1)
                if not self._queue_running:
                    break

        if task.status == "failed":
            raise RuntimeError(task.error or "文件发送失败")
        if task.status != "done":
            raise RuntimeError("WebSocket连接未建立，文件发送失败")

    def _build_message_payload(
        self,
        user_id: str,
        message: str,
        group_id: Optional[str],
        private: bool,
    ) -> Dict[str, Any]:
        """构建文本消息发送负载"""
        if private:
            payload: Dict[str, Any] = {
                "action": "send_private_msg",
                "params": {"user_id": user_id, "message": message},
            }
        else:
            payload = {
                "action": "send_group_msg",
                "params": {"group_id": group_id, "message": message},
            }

        if self.config.get("NAPCAT_TOKEN"):
            payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]
        return payload

    def _build_file_payload(
        self,
        file_path: str,
        user_id: str,
        group_id: Optional[str],
        private: bool,
    ) -> Dict[str, Any]:
        """构建文件发送负载"""
        file_name = os.path.basename(file_path)
        message_segments = [
            {"type": "file", "data": {"file": file_path, "name": file_name}}
        ]

        if private:
            payload: Dict[str, Any] = {
                "action": "send_private_msg",
                "params": {"user_id": user_id, "message": message_segments},
            }
        else:
            payload = {
                "action": "send_group_msg",
                "params": {"group_id": group_id, "message": message_segments},
            }

        if self.config.get("NAPCAT_TOKEN"):
            payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]
        return payload

    def _store_pending_error(
        self,
        user_id: str,
        content_type: str,
        content: str,
        group_id: Optional[str],
        private: bool,
    ) -> None:
        """留存未能送达的内容，等待连接恢复后补发提醒"""
        entry = {
            "user_id": user_id,
            "group_id": group_id,
            "private": private,
            "content_type": content_type,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self._pending_errors_lock:
            self._pending_errors.append(entry)

    def _flush_pending_errors(self) -> None:
        """连接恢复后，将中断期间留存的内容以提醒消息补发给用户"""
        if self.ws_client is None or not self._is_websocket_connected():
            return

        with self._pending_errors_lock:
            pending = self._pending_errors[:]
        if not pending:
            return

        grouped: Dict[Any, List[Dict[str, Any]]] = {}
        for entry in pending:
            key = (entry["user_id"], entry["group_id"], entry["private"])
            grouped.setdefault(key, []).append(entry)

        for (user_id, group_id, private), entries in grouped.items():
            notify = "⚠️ 上次 WebSocket 连接中断，以下内容未能及时送达：\n\n"
            for entry in entries:
                if entry["content_type"] == "file":
                    notify += f"[{entry['timestamp']}] 文件：{os.path.basename(entry['content'])}\n"
                else:
                    notify += f"[{entry['timestamp']}] 消息：{entry['content'][:100]}\n"

            try:
                payload = self._build_message_payload(
                    user_id, notify, group_id, bool(private)
                )
                with self._ws_lock:
                    self.ws_client.ws.send(json.dumps(payload))
                time.sleep(0.3)
                with self._pending_errors_lock:
                    for entry in entries:
                        if entry in self._pending_errors:
                            self._pending_errors.remove(entry)
                self.logger.info(f"已补发连接中断期间留存的 {len(entries)} 条内容")
            except Exception as e:
                self.logger.error(f"补发留存消息失败: {e}")

    def _is_websocket_connected(self) -> bool:
        """
        检查WebSocket是否已连接

        Returns:
            bool: WebSocket是否已连接
        """
        return (
            self.ws_client is not None
            and self.ws_client.ws is not None
            and self.ws_client.ws.sock is not None
            and self.ws_client.ws.sock.connected
        )
