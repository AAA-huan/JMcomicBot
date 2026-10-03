"""消息管理器，负责发送文本消息和文件"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import json
import os
import queue
import threading
import time

from src.database.repositories import TaskLogRepository
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

    def __init__(
        self,
        config: Dict[str, Any],
        ws_client: Optional[Any] = None,
        task_log_repo: Optional[TaskLogRepository] = None,
    ) -> None:
        """
        初始化消息管理器

        Args:
            config: 配置字典，包含NAPCAT_TOKEN等信息
            ws_client: WebSocket客户端实例
            task_log_repo: 任务日志仓储，记录文件发送任务
        """
        self.config = config
        self.ws_client = ws_client
        self.task_log_repo = task_log_repo
        self.logger = logger
        self._file_queue: queue.Queue = queue.Queue()
        self._queue_running: bool = True
        self._stop_event: threading.Event = threading.Event()
        self._file_thread: Optional[threading.Thread] = None
        # 保护所有ws.send，避免多线程并发写入连接
        self._ws_lock: threading.RLock = threading.RLock()
        # 等待文件发送结果的同步原语
        self._result_cond: threading.Condition = threading.Condition()
        # 连接中断期间未能送达的内容，待连接恢复后补发提醒
        self._pending_errors: List[Dict[str, Any]] = []
        self._pending_errors_lock: threading.Lock = threading.Lock()
        # 当前正在发送的文件名（供发送进度查询）
        self._current_sending_file: Optional[str] = None
        # 未完成的任务总数（队列中等待 + 正在处理的），替代 qsize()
        self._queue_count: int = 0
        self._queue_count_lock: threading.Lock = threading.Lock()
        # 发送参数独立保存，SettingsService 通过 update_send_settings 显式更新
        self.file_send_interval: float = float(config.get("FILE_SEND_INTERVAL", 1.8))
        self.send_retry_timeout: int = int(config.get("SEND_RETRY_TIMEOUT", 30))
        self.resend_confirm_timeout: int = int(
            config.get("RESEND_CONFIRM_TIMEOUT", 300)
        )
        self._start_file_queue_worker()

    def update_send_settings(
        self,
        send_interval: Optional[float] = None,
        retry_timeout: Optional[int] = None,
        resend_confirm_timeout: Optional[int] = None,
    ) -> None:
        """由 SettingsService 调用，显式更新发送参数并立即生效。"""
        if send_interval is not None:
            if send_interval <= 0:
                raise ValueError("文件发送间隔必须大于 0")
            self.file_send_interval = send_interval
            self.config["FILE_SEND_INTERVAL"] = send_interval
        if retry_timeout is not None:
            if retry_timeout < 1:
                raise ValueError("发送重试超时必须至少为 1 秒")
            self.send_retry_timeout = retry_timeout
            self.config["SEND_RETRY_TIMEOUT"] = retry_timeout
        if resend_confirm_timeout is not None:
            if resend_confirm_timeout < 1:
                raise ValueError("重发确认超时必须至少为 1 秒")
            self.resend_confirm_timeout = resend_confirm_timeout
            self.config["RESEND_CONFIRM_TIMEOUT"] = resend_confirm_timeout
        self.logger.info(
            "文件发送参数已更新: "
            f"发送间隔 {self.file_send_interval} 秒, "
            f"重试超时 {self.send_retry_timeout} 秒, "
            f"重发确认超时 {self.resend_confirm_timeout} 秒"
        )

    def get_send_queue_status(self) -> Dict[str, Any]:
        """获取当前文件发送队列状态

        queue_size 为任务总数（排队 + 正在发送），pending_count 为排队数，
        current_file 为正在发送的文件名。

        Returns:
            Dict[str, Any]: 包含 running、queue_size、pending_count、current_file 的状态字典
        """
        with self._queue_count_lock:
            qc = self._queue_count
        current_file = self._current_sending_file
        return {
            "running": self._queue_running,
            "queue_size": qc,
            "pending_count": max(0, qc - (1 if current_file else 0)),
            "current_file": current_file,
        }

    def is_manga_sending(self, manga_id: str) -> bool:
        """返回指定漫画是否有文件正在发送或排队发送。"""
        current = self._current_sending_file
        if current is not None and current.split("-", 1)[0] == manga_id:
            return True
        for task in list(self._file_queue.queue):
            if os.path.basename(task.file_path).split("-", 1)[0] == manga_id:
                return True
        return False

    def set_websocket_client(self, ws_client: Optional[Any]) -> None:
        """
        设置WebSocket客户端

        Args:
            ws_client: WebSocket客户端实例
        """
        self.ws_client = ws_client

    def stop(self, timeout: float = 1.0) -> bool:
        """停止文件发送队列并等待工作线程退出

        Args:
            timeout: 等待工作线程退出的最长秒数

        Returns:
            bool: 工作线程是否已退出
        """
        with self._queue_count_lock:
            self._queue_running = False
            self._stop_event.set()
            # 与入队共用锁，避免停止哨兵之后又插入新任务。
            self._file_queue.put(None)
        with self._result_cond:
            self._result_cond.notify_all()
        if self._file_thread is not None:
            self._file_thread.join(timeout=timeout)
            if self._file_thread.is_alive():
                self.logger.warning("文件发送队列未在限定时间内停止")
                return False
        with self._queue_count_lock:
            self._queue_count = 0
        self.logger.info("文件发送队列线程已停止")
        return True

    def _start_file_queue_worker(self) -> None:
        """启动文件发送队列后台线程，串行执行文件发送任务"""

        def process_queue() -> None:
            while not self._stop_event.is_set():
                try:
                    task = self._file_queue.get(timeout=1)
                except queue.Empty:
                    self._flush_pending_errors()
                    self._cleanup_expired_resends()
                    continue

                try:
                    if task is None or self._stop_event.is_set():
                        return
                    self._process_send_task(task)
                finally:
                    self._file_queue.task_done()

        self._file_thread = threading.Thread(target=process_queue, daemon=True)
        self._file_thread.start()
        self.logger.info("文件发送队列后台线程已启动")

    def _log_send_task(self, task: SendTask, status: str, message: str) -> None:
        """记录文件发送任务到数据库

        Args:
            task: 文件发送任务
            status: 任务状态
            message: 结果信息
        """
        if self.task_log_repo is None:
            return
        manga_id = os.path.basename(task.file_path).split("-", 1)[0]
        try:
            self.task_log_repo.add(
                task_type="send",
                status=status,
                manga_id=manga_id,
                user_id=task.user_id,
                group_id=task.group_id or "",
                private=task.private,
                message=f"{message} {task.file_path}".strip(),
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"记录发送任务日志失败: {e}")

    def _process_send_task(self, task: SendTask) -> None:
        """处理单个文件发送任务，发送结果通过条件变量通知等待线程"""
        self._current_sending_file = os.path.basename(task.file_path)
        try:
            self._send_file_with_retry(task)
            task.status = "done"
            self._log_send_task(task, "success", "")
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"发送文件失败: {task.file_path}, {e}")
            task.status = "failed"
            task.error = str(e)
            self._log_send_task(task, "failed", str(e))
            if not self._stop_event.is_set():
                self._store_pending_error(
                    user_id=task.user_id,
                    content_type="file",
                    content=task.file_path,
                    group_id=task.group_id,
                    private=task.private,
                )
        finally:
            self._current_sending_file = None
            with self._queue_count_lock:
                self._queue_count -= 1
            with self._result_cond:
                self._result_cond.notify_all()

    def _enqueue_file_task(self, task: SendTask) -> None:
        """登记并加入文件发送队列，确保所有入队路径使用相同计数规则"""
        with self._queue_count_lock:
            if self._stop_event.is_set():
                raise RuntimeError("文件发送队列已停止")
            self._queue_count += 1
            self._file_queue.put(task)

    def _send_file_with_retry(self, task: SendTask) -> None:
        """尝试发送文件，连接断开时等待重连并重试，超时抛出异常"""
        payload = self._build_file_payload(
            task.file_path, task.user_id, task.group_id, task.private
        )
        retry_timeout = self.send_retry_timeout
        deadline = time.time() + retry_timeout

        while time.time() < deadline and not self._stop_event.is_set():
            if self.ws_client is None or not self._is_websocket_connected():
                self._stop_event.wait(0.5)
                continue
            try:
                with self._ws_lock:
                    self.ws_client.ws.send(json.dumps(payload))
                self.logger.info(
                    f"文件已通过WS发送: {os.path.basename(task.file_path)}, "
                    f"目标: {'私聊' if task.private else '群聊'}, "
                    f"用户: {task.user_id}"
                )
                send_interval = self.file_send_interval
                self._stop_event.wait(send_interval)
                return
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.warning(f"发送文件时连接异常，重试中: {e}")
                self._stop_event.wait(0.5)

        if self._stop_event.is_set():
            raise RuntimeError("文件发送队列已停止")
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
        self._enqueue_file_task(task)

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
            "timestamp": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "awaiting_resend": False,
        }
        with self._pending_errors_lock:
            self._pending_errors.append(entry)

    def _flush_pending_errors(self) -> None:
        """连接恢复后，将留存的文本补发给用户，并提醒文件可确认重发"""
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
            text_entries = [e for e in entries if e["content_type"] == "message"]
            new_file_entries = [
                e
                for e in entries
                if e["content_type"] == "file" and not e.get("awaiting_resend")
            ]

            if not text_entries and not new_file_entries:
                continue

            notify = "⚠️ 上次 WebSocket 连接中断，以下内容未能及时送达：\n\n"
            if new_file_entries:
                by_manga: Dict[str, int] = {}
                for entry in new_file_entries:
                    manga_id = os.path.basename(entry["content"]).split("-", 1)[0]
                    by_manga[manga_id] = by_manga.get(manga_id, 0) + 1
                for manga_id, count in by_manga.items():
                    notify += f" • 漫画ID {manga_id}（{count} 个文件）\n"
                resend_timeout = self.resend_confirm_timeout
                notify += (
                    f"\n📬 回复「重发重发」确认重新发送，"
                    f"{int(resend_timeout / 60)} 分钟内未确认将自动放弃"
                )
            for entry in text_entries:
                notify += f"[{entry['timestamp']}] 消息：{entry['content'][:100]}\n"

            try:
                payload = self._build_message_payload(
                    user_id, notify, group_id, bool(private)
                )
                with self._ws_lock:
                    self.ws_client.ws.send(json.dumps(payload))
                time.sleep(0.3)
                now = time.time()
                text_ids = {id(e) for e in text_entries}
                new_file_ids = {id(e) for e in new_file_entries}
                with self._pending_errors_lock:
                    self._pending_errors = [
                        e for e in self._pending_errors if id(e) not in text_ids
                    ]
                    for entry in self._pending_errors:
                        if id(entry) in new_file_ids:
                            entry["awaiting_resend"] = True
                            entry["ts"] = now
                            entry["timestamp"] = time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime(now)
                            )
                self.logger.info(
                    f"已补发连接中断期间留存的 {len(text_entries)} 条文本，"
                    f"并提醒 {len(new_file_entries)} 个文件待重发"
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.error(f"补发留存消息失败: {e}")

    def resend_pending_files(
        self,
        user_id: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> int:
        """将指定用户连接中断期间留存的文件重新加入发送队列

        Args:
            user_id: 用户ID
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊

        Returns:
            int: 实际重新加入发送队列的文件数量
        """
        if not self._queue_running:
            self.logger.warning("文件发送队列已停止，无法重发")
            return 0

        resend_entries: List[Dict[str, Any]] = []
        with self._pending_errors_lock:
            remaining: List[Dict[str, Any]] = []
            for entry in self._pending_errors:
                match = (
                    entry.get("content_type") == "file"
                    and entry.get("awaiting_resend")
                    and entry.get("user_id") == user_id
                    and entry.get("group_id") == group_id
                    and entry.get("private") == private
                )
                if match:
                    if os.path.exists(entry["content"]):
                        resend_entries.append(entry)
                    else:
                        self.logger.warning(
                            f"待重发文件不存在，已丢弃: {entry['content']}"
                        )
                else:
                    remaining.append(entry)
            self._pending_errors = remaining

        count = 0
        for entry in resend_entries:
            self.logger.info(f"重发文件: {entry['content']}")
            self._enqueue_file_task(
                SendTask(
                    user_id=entry["user_id"],
                    file_path=entry["content"],
                    group_id=entry["group_id"],
                    private=entry["private"],
                )
            )
            count += 1
        return count

    def _cleanup_expired_resends(self) -> None:
        """清理等待用户确认重发但已超时的文件，防止残留"""
        timeout = self.resend_confirm_timeout
        now = time.time()
        expired: List[Dict[str, Any]] = []
        with self._pending_errors_lock:
            remaining: List[Dict[str, Any]] = []
            for entry in self._pending_errors:
                if (
                    entry.get("content_type") == "file"
                    and entry.get("awaiting_resend")
                    and now - entry.get("ts", 0) > timeout
                ):
                    expired.append(entry)
                else:
                    remaining.append(entry)
            self._pending_errors = remaining
        for entry in expired:
            self.logger.info(
                f"等待重发的文件已超时放弃: {os.path.basename(entry['content'])}"
            )

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
