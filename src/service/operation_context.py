"""QQ、Web 和系统操作的统一来源上下文。"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OperationContext:
    """仅保存审计所需身份，不包含原始命令、Cookie 或请求正文。"""

    source: str
    actor_user_id: Optional[str] = None
    actor_group_id: Optional[str] = None
    client_ip: Optional[str] = None

    @classmethod
    def qq(cls, user_id: str, group_id: Optional[str] = None) -> "OperationContext":
        """构造 QQ 操作身份上下文。"""
        return cls(source="qq", actor_user_id=user_id, actor_group_id=group_id)

    @classmethod
    def web(cls, admin_id: str, client_ip: str) -> "OperationContext":
        """构造包含直连 IP 的 Web 操作上下文。"""
        if not client_ip.strip():
            raise ValueError("Web 操作必须提供客户端 IP")
        return cls(source="web", actor_user_id=admin_id, client_ip=client_ip)

    @classmethod
    def system(cls) -> "OperationContext":
        """构造系统操作上下文。"""
        return cls(source="system")
