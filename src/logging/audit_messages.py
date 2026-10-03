"""审计事件的中文业务语义日志格式化。

WebUI 操作与后台任务的完成情况通过审计事件集中输出到控制台，
让日志直接反映"谁在什么时候做了什么、结果如何"，而不是 URL 与状态码。
"""

from typing import Optional

# 审计事件名到中文动作的映射；未登记的事件名按原样展示，保证可读性
_EVENT_LABELS = {
    "download.requested": "创建下载任务",
    "download.completed": "下载任务完成",
    "download.failed": "下载任务失败",
    "manga.delete_requested": "请求删除漫画",
    "manga.deleted": "漫画删除完成",
    "manga.delete_failed": "漫画删除失败",
    "manga.metadata_updated": "修改漫画元数据",
    "database.backup_requested": "请求创建数据库备份",
    "database.backup_created": "数据库备份完成",
    "database.backup_failed": "数据库备份失败",
    "library.scan_requested": "请求扫描资料库",
    "library.scan_completed": "资料库扫描完成",
    "library.scan_failed": "资料库扫描失败",
    "library.repair_requested": "请求修复资料库",
    "library.repair_completed": "资料库修复完成",
    "library.repair_failed": "资料库修复失败",
    "library.verify_requested": "请求校验漫画文件",
    "library.verify_completed": "漫画文件校验完成",
    "library.verify_failed": "漫画文件校验失败",
    "web.login_succeeded": "登录成功",
    "web.login_failed": "登录失败",
    "web.logout": "退出登录",
    "setting.changed": "修改配置",
    "permission.changed": "修改权限名单",
    "favorite.changed": "修改漫画收藏",
    "admin.qq.changed": "修改管理员 QQ 关联",
    "napcat.reconnect_requested": "请求重连 NapCat",
    "maintenance.cleanup_completed": "清理过期数据",
    "bot.shutdown_requested": "请求关闭机器人",
}

# 审计结果到中文说明的映射
_RESULT_LABELS = {
    "accepted": "已受理",
    "succeeded": "成功",
    "failed": "失败",
    "cancelled": "已取消",
}

# 审计来源到中文来源的映射
_SOURCE_LABELS = {
    "web": "WebUI",
    "qq": "QQ",
    "system": "系统",
}

# 审计目标类型到中文目标的映射
_TARGET_LABELS = {
    "manga": "漫画",
    "setting": "配置",
    "permission": "权限名单",
    "napcat": "NapCat 连接",
    "database": "数据库",
    "web_admin": "管理员",
    "bot": "机器人",
    "download": "下载任务",
    "scan": "扫描任务",
    "repair": "修复任务",
    "delete": "删除任务",
    "backup": "备份任务",
    "verify": "校验任务",
}


def format_audit_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    event_type: str,
    source: str,
    result: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    error_code: Optional[str] = None,
) -> str:
    """把审计事件格式化为一条中文业务语义日志。

    示例：
        WebUI 操作：修改漫画元数据，漫画 516751，结果 成功，IP 127.0.0.1
    """
    source_label = _SOURCE_LABELS.get(source, source)
    action = _EVENT_LABELS.get(event_type, event_type)
    parts = [f"{source_label} 操作：{action}"]
    if target_id:
        target_label = _TARGET_LABELS.get(target_type or "", "目标")
        parts.append(f"{target_label} {target_id}")
    parts.append(f"结果 {_RESULT_LABELS.get(result, result)}")
    if error_code:
        parts.append(f"错误 {error_code}")
    if client_ip:
        parts.append(f"IP {client_ip}")
    return "，".join(parts)
