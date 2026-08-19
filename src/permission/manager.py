"""权限管理模块，负责用户与群组的权限检查"""

from typing import List, Optional

from src.logging.logger_config import logger


class PermissionManager:
    """权限管理器，负责用户权限检查"""

    def __init__(
        self,
        group_whitelist: List[str],
        private_whitelist: List[str],
        global_blacklist: List[str],
        delete_permission_user: List[str],
    ) -> None:
        """
        初始化权限管理器

        Args:
            group_whitelist: 群组白名单
            private_whitelist: 私信白名单
            global_blacklist: 全局黑名单
            delete_permission_user: 删除权限用户名单
        """
        self.group_whitelist = group_whitelist
        self.private_whitelist = private_whitelist
        self.global_blacklist = global_blacklist
        self.delete_permission_user = delete_permission_user
        self.logger = logger

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

    def update_whitelist(
        self,
        group_whitelist: Optional[List[str]] = None,
        private_whitelist: Optional[List[str]] = None,
        global_blacklist: Optional[List[str]] = None,
    ) -> None:
        """
        更新白名单和黑名单

        Args:
            group_whitelist: 新的群组白名单
            private_whitelist: 新的私信白名单
            global_blacklist: 新的全局黑名单
        """
        if group_whitelist is not None:
            self.group_whitelist = group_whitelist
            self.logger.info(f"群组白名单已更新: {len(group_whitelist)}个")
        if private_whitelist is not None:
            self.private_whitelist = private_whitelist
            self.logger.info(f"私信白名单已更新: {len(private_whitelist)}个")
        if global_blacklist is not None:
            self.global_blacklist = global_blacklist
            self.logger.info(f"全局黑名单已更新: {len(global_blacklist)}个")

    def check_delete_permission(self, user_id: str) -> bool:
        """
        检查用户是否有删除漫画的权限

        删除权限规则：
        1. 删除权限用户名单必须且只能有一个用户
        2. 用户必须在删除权限用户名单中

        Args:
            user_id: 用户ID

        Returns:
            bool: 用户是否有删除权限

        Raises:
            ValueError: 当删除权限用户名单为空或包含多个用户时
        """
        if len(self.delete_permission_user) == 0:
            error_msg = "删除功能不可用：未配置删除权限用户"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        if len(self.delete_permission_user) != 1:
            error_msg = "删除功能不可用：删除权限用户名单必须且只能有一个用户"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        if user_id not in self.delete_permission_user:
            error_msg = f"用户 {user_id} 没有删除漫画的权限"
            self.logger.warning(error_msg)
            raise ValueError(error_msg)

        self.logger.debug(f"用户 {user_id} 删除权限检查通过")
        return True
