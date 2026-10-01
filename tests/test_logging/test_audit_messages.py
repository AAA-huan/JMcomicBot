"""审计事件业务语义日志测试。"""

from src.database.repositories import AuditEventRepository
from src.logging.audit_messages import format_audit_message


class TestFormatAuditMessage:
    """中文业务语义格式化测试"""

    def test_webui_operation_message(self) -> None:
        message = format_audit_message(
            event_type="manga.metadata_updated",
            source="web",
            result="succeeded",
            target_type="manga",
            target_id="516751",
            client_ip="127.0.0.1",
        )

        assert message == (
            "WebUI 操作：修改漫画元数据，漫画 516751，结果 成功，IP 127.0.0.1"
        )

    def test_failed_login_includes_error_code(self) -> None:
        message = format_audit_message(
            event_type="web.login_failed",
            source="web",
            result="failed",
            target_type="web_admin",
            client_ip="192.168.1.20",
            error_code="auth_failed",
        )

        assert "登录失败" in message
        assert "结果 失败" in message
        assert "错误 auth_failed" in message
        assert "IP 192.168.1.20" in message

    def test_unknown_event_falls_back_to_event_name(self) -> None:
        message = format_audit_message(
            event_type="custom.event", source="web", result="accepted"
        )

        assert "custom.event" in message
        assert "已受理" in message


class TestAuditRepositoryLogging:
    """审计仓储的日志行为测试"""

    @staticmethod
    def _capture_info(monkeypatch) -> list[str]:
        messages: list[str] = []
        monkeypatch.setattr(
            "src.database.repositories.audit_event_repository.logger.info",
            lambda message: messages.append(message),
        )
        return messages

    def test_web_source_writes_business_log(self, db_manager, monkeypatch) -> None:
        """WebUI 来源的审计事件同时输出一条中文业务日志。"""
        messages = self._capture_info(monkeypatch)
        repo = AuditEventRepository(db_manager)

        repo.record(
            event_type="setting.changed",
            source="web",
            result="succeeded",
            target_type="setting",
            target_id="FILE_SEND_INTERVAL",
            client_ip="127.0.0.1",
        )

        assert len(messages) == 1
        assert "修改配置" in messages[0]
        assert "FILE_SEND_INTERVAL" in messages[0]
        assert "IP 127.0.0.1" in messages[0]

    def test_qq_source_does_not_write_business_log(
        self, db_manager, monkeypatch
    ) -> None:
        """QQ 来源沿用各自模块日志，不重复输出业务日志。"""
        messages = self._capture_info(monkeypatch)
        repo = AuditEventRepository(db_manager)

        repo.record(
            event_type="download.requested",
            source="qq",
            result="accepted",
            target_type="manga",
            target_id="350234",
        )

        assert messages == []
