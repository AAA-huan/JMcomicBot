"""仓储层抽象基类，定义统一的数据访问接口入口

所有仓储均继承 BaseRepository，持有 DatabaseManager 以获取会话。
未来 WebUI 可直接复用此仓储层进行数据读写，避免直接操作 SQL。
"""

from abc import ABC, abstractmethod
from typing import Any, List


class BaseRepository(ABC):
    """仓储抽象基类，所有具体仓储的公共父类"""

    def __init__(self, db_manager: Any) -> None:
        self.db_manager = db_manager

    def _get_session(self) -> Any:
        """获取一个新的数据库会话（调用方负责关闭）"""
        return self.db_manager.get_session()

    @abstractmethod
    def get(self, *args: Any, **kwargs: Any) -> Any:
        """根据主键获取单条记录"""

    @abstractmethod
    def list(self, *args: Any, **kwargs: Any) -> List[Any]:
        """查询记录列表"""
