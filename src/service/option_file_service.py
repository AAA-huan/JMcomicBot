"""option.yml 网页编辑服务：读取、校验、原子保存并记录审计。

jmcomic 下载器在每个任务开工时重新读取 option.yml（见
``src.download.manager._process_download_task``），因此保存即对后续任务
生效，无需重启。img2pdf 与进度插件由程序自动注入并覆盖关键项，编辑器
只维护用户可见的下载参数。
"""

import os
import tempfile
from typing import Optional

import yaml

from src.database.repositories import AuditEventRepository
from src.service.operation_context import OperationContext

# option.yml 内容大小上限，防止误传大文件
OPTION_FILE_MAX_BYTES = 256 * 1024


class OptionFileService:
    """读取与保存项目根的 option.yml，保存时原子替换并写审计。"""

    def __init__(
        self,
        option_file_path: str,
        audit_repository: AuditEventRepository,
    ) -> None:
        self.option_file_path = os.path.abspath(option_file_path)
        self.audit_repository = audit_repository

    def read(self) -> str:
        """返回当前 option.yml 内容；文件不存在时返回空串。"""
        if not os.path.exists(self.option_file_path):
            return ""
        with open(self.option_file_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def write(self, text: str, context: Optional[OperationContext] = None) -> None:
        """校验并原子保存 option.yml。

        Raises:
            ValueError: 内容为空、超过大小上限或不是合法 YAML 字典时
        """
        if text is None:
            raise ValueError("option.yml 内容不能为空")
        encoded = text.encode("utf-8")
        if len(encoded) > OPTION_FILE_MAX_BYTES:
            raise ValueError(
                f"option.yml 超过大小上限（{OPTION_FILE_MAX_BYTES // 1024} KB）"
            )
        # 必须解析为字典：jmcomic 的 option.yml 顶层是映射
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(f"option.yml 不是合法 YAML: {error}") from error
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError("option.yml 顶层必须是字典（键值对）")

        # 原子替换：先写同目录临时文件再 os.replace，避免半写状态
        directory = os.path.dirname(self.option_file_path) or "."
        fd, temp_path = tempfile.mkstemp(prefix=".option.yml-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temp_path, self.option_file_path)
        except Exception:
            # 清理临时文件，不留下垃圾
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        operation_context = context or OperationContext.system()
        self.audit_repository.record(
            event_type="setting.changed",
            source=operation_context.source,
            result="succeeded",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="setting",
            target_id="option.yml",
            metadata={"changed_fields": ["option.yml"]},
        )
