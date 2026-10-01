"""权限管理模块，负责用户与群组的权限检查"""

from typing import List, Optional

from src.database.repositories import PermissionRepository
from src.logging.logger_config import logger


class PermissionManager:
    """权限管理器，负责用户权限检查

    白名单/黑名单/删除权限用户均持久化在数据库 permission 表中。
    首次启动时若权限表为空，会将 .env 中配置的名单作为种子数据导入；
    此后以数据库内容为准，并支持通过动态增删接口实时变更。
    """

    # 数据库 permission 表中的名单类型（scope）
    SCOPE_GROUP_WHITELIST = "group_whitelist"
    SCOPE_PRIVATE_WHITELIST = "private_whitelist"
    SCOPE_GLOBAL_BLACKLIST = "global_blacklist"
    SCOPE_DELETE_PERMISSION_USER = "delete_permission_user"

    # 全部合法名单类型，供 WebUI 与命令入口统一校验
    SCOPES = (
        SCOPE_GROUP_WHITELIST,
        SCOPE_PRIVATE_WHITELIST,
        SCOPE_GLOBAL_BLACKLIST,
        SCOPE_DELETE_PERMISSION_USER,
    )

    def __init__(
        self,
        permission_repo: PermissionRepository,
        seed_group_whitelist: Optional[List[str]] = None,
        seed_private_whitelist: Optional[List[str]] = None,
        seed_global_blacklist: Optional[List[str]] = None,
        seed_delete_permission_user: Optional[List[str]] = None,
    ) -> None:
        """
        初始化权限管理器

        Args:
            permission_repo: 权限名单仓储
            seed_group_whitelist: 首次启动时的群组白名单种子数据（来自.env）
            seed_private_whitelist: 首次启动时的私信白名单种子数据（来自.env）
            seed_global_blacklist: 首次启动时的全局黑名单种子数据（来自.env）
            seed_delete_permission_user: 首次启动时的删除权限用户种子数据（来自.env）
        """
        self.permission_repo = permission_repo
        self.logger = logger

        seed_data = [
            (self.SCOPE_GROUP_WHITELIST, seed_group_whitelist or []),
            (self.SCOPE_PRIVATE_WHITELIST, seed_private_whitelist or []),
            (self.SCOPE_GLOBAL_BLACKLIST, seed_global_blacklist or []),
            (self.SCOPE_DELETE_PERMISSION_USER, seed_delete_permission_user or []),
        ]
        self._seed_if_empty(seed_data)
        self._reload_scopes()

        self.logger.info(
            f"黑白名单配置加载完成 - "
            f"群组白名单: {len(self.group_whitelist)}个, "
            f"私信白名单: {len(self.private_whitelist)}个, "
            f"全局黑名单: {len(self.global_blacklist)}个, "
            f"删除权限用户: {len(self.delete_permission_user)}个"
        )

    def _seed_if_empty(self, seed_data: List[tuple[str, List[str]]]) -> None:
        """
        权限表为空时将种子数据导入数据库，实现 .env → 数据库的一次性迁移

        Args:
            seed_data: (scope, id列表) 列表
        """
        existing_scopes = self.permission_repo.get_all_scopes()
        if existing_scopes:
            return

        for scope, values in seed_data:
            if values:
                self.permission_repo.replace_scope(scope, values)
                self.logger.info(f"已从.env导入 {scope} 种子数据: {len(values)}个")

    def _reload_scopes(self) -> None:
        """从数据库重新加载全部名单到内存"""
        scopes = self.permission_repo.get_all_scopes()
        self.group_whitelist: List[str] = scopes.get(self.SCOPE_GROUP_WHITELIST, [])
        self.private_whitelist: List[str] = scopes.get(self.SCOPE_PRIVATE_WHITELIST, [])
        self.global_blacklist: List[str] = scopes.get(self.SCOPE_GLOBAL_BLACKLIST, [])
        self.delete_permission_user: List[str] = scopes.get(
            self.SCOPE_DELETE_PERMISSION_USER, []
        )

    def check_user_permission(  # pylint: disable=too-many-arguments
        self,
        user_id: str,
        group_id: Optional[str] = None,
        private: bool = True,
        *,
        user_display: Optional[str] = None,
        group_display: Optional[str] = None,
    ) -> bool:
        """
        检查用户是否有权限使用机器人

        权限检查规则：
        1. 全局黑名单优先：如果用户在全局黑名单中，直接拒绝
        2. 白名单检查：
           - 私聊：检查用户是否在私信白名单中（如果白名单不为空）
           - 群聊：检查群组是否在群组白名单中（如果白名单不为空）
        3. 白名单为空表示不限制

        Args:
            user_id: 用户ID
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊
            user_display: 用户显示名（用于日志，缺省回退到 user_id）
            group_display: 群组显示名（用于日志，缺省回退到 group_id）

        Returns:
            bool: 用户是否有权限使用机器人

        Raises:
            ValueError: 当用户在黑名单中或权限不足时
        """
        # 日志显示优先使用名称，未提供时回退到原始ID
        user_label = user_display if user_display else user_id
        group_label = group_display if group_display else group_id

        if user_id in self.global_blacklist:
            error_msg = f"用户 {user_label} 在全局黑名单中，拒绝访问"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        if private:
            if self.private_whitelist and user_id not in self.private_whitelist:
                error_msg = f"用户 {user_label} 不在私信白名单中，拒绝访问"
                self.logger.warning(error_msg)
                raise ValueError(error_msg)
        else:
            if (
                group_id
                and self.group_whitelist
                and group_id not in self.group_whitelist
            ):
                error_msg = f"群组 {group_label} 不在群组白名单中，拒绝访问"
                self.logger.warning(error_msg)
                raise ValueError(error_msg)

        self.logger.debug(f"用户 {user_label} 权限检查通过")
        return True

    def add_to_scope(self, scope: str, value: str) -> bool:
        """
        向指定名单动态添加一个ID并立即生效

        Args:
            scope: 名单类型（使用 SCOPE_* 常量）
            value: 名单内ID

        Returns:
            bool: 是否为新插入
        """
        self.validate_scope(scope)
        added = self.permission_repo.add(scope, value)
        if added:
            self._reload_scopes()
        return added

    def remove_from_scope(self, scope: str, value: str) -> bool:
        """
        从指定名单动态移除一个ID并立即生效

        Args:
            scope: 名单类型（使用 SCOPE_* 常量）
            value: 名单内ID

        Returns:
            bool: 是否实际删除了记录
        """
        self.validate_scope(scope)
        removed = self.permission_repo.remove(scope, value)
        if removed:
            self._reload_scopes()
        return removed

    @classmethod
    def validate_scope(cls, scope: str) -> str:
        """
        校验名单类型是否受支持

        Args:
            scope: 名单类型

        Returns:
            str: 原样返回合法名单类型

        Raises:
            ValueError: 名单类型不在项目定义的四种类型中时
        """
        if scope not in cls.SCOPES:
            raise ValueError(f"不支持的权限类型: {scope}")
        return scope

    def get_scope(self, scope: str) -> List[str]:
        """
        返回指定名单当前的内存快照

        Args:
            scope: 名单类型

        Returns:
            List[str]: 名单内ID列表的副本

        Raises:
            ValueError: 名单类型不受支持时
        """
        self.validate_scope(scope)
        scope_values = {
            self.SCOPE_GROUP_WHITELIST: self.group_whitelist,
            self.SCOPE_PRIVATE_WHITELIST: self.private_whitelist,
            self.SCOPE_GLOBAL_BLACKLIST: self.global_blacklist,
            self.SCOPE_DELETE_PERMISSION_USER: self.delete_permission_user,
        }
        return list(scope_values[scope])

    def update_whitelist(
        self,
        group_whitelist: Optional[List[str]] = None,
        private_whitelist: Optional[List[str]] = None,
        global_blacklist: Optional[List[str]] = None,
    ) -> None:
        """
        整体更新白名单和黑名单（落库并立即生效）

        Args:
            group_whitelist: 新的群组白名单
            private_whitelist: 新的私信白名单
            global_blacklist: 新的全局黑名单
        """
        if group_whitelist is not None:
            self.permission_repo.replace_scope(
                self.SCOPE_GROUP_WHITELIST, group_whitelist
            )
            self.logger.info(f"群组白名单已更新: {len(group_whitelist)}个")
        if private_whitelist is not None:
            self.permission_repo.replace_scope(
                self.SCOPE_PRIVATE_WHITELIST, private_whitelist
            )
            self.logger.info(f"私信白名单已更新: {len(private_whitelist)}个")
        if global_blacklist is not None:
            self.permission_repo.replace_scope(
                self.SCOPE_GLOBAL_BLACKLIST, global_blacklist
            )
            self.logger.info(f"全局黑名单已更新: {len(global_blacklist)}个")
        self._reload_scopes()

    def check_delete_permission(self, user_id: str) -> bool:
        """
        检查用户是否有删除漫画的权限

        删除权限规则：
        1. 删除权限用户名单为空时删除功能不可用
        2. 用户必须在删除权限用户名单中

        Args:
            user_id: 用户ID

        Returns:
            bool: 用户是否有删除权限

        Raises:
            ValueError: 当删除权限用户名单为空或用户不在名单中时
        """
        if len(self.delete_permission_user) == 0:
            error_msg = "删除功能不可用：未配置删除权限用户"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        if user_id not in self.delete_permission_user:
            error_msg = f"用户 {user_id} 没有删除漫画的权限"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        self.logger.debug(f"用户 {user_id} 删除权限检查通过")
        return True
