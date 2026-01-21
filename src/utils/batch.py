from typing import List, Tuple


def parse_batch_params(params: str) -> Tuple[List[str], bool]:
    """
    解析批量操作参数，支持逗号分隔的ID列表和--all标志

    Args:
        params: 原始参数字符串

    Returns:
        Tuple[List[str], bool]: (ID列表, 是否使用--all)

    Raises:
        ValueError: 当参数格式错误时
    """
    if not params or not params.strip():
        return [], False

    params = params.strip()

    if params == "--all":
        return [], True

    if params.startswith("--all"):
        remaining = params[5:].strip()
        if remaining:
            raise ValueError("❌ 参数错误！'--all' 参数不能与其他参数混用")
        return [], True

    if "," in params:
        ids = [id.strip() for id in params.split(",") if id.strip()]
        if not ids:
            raise ValueError("❌ 参数错误！未提供有效的漫画ID")
        return ids, False

    if params.isdigit():
        return [params], False

    raise ValueError("❌ 参数错误！请提供有效的漫画ID（纯数字）或使用逗号分隔多个ID")


def validate_manga_ids(ids: List[str]) -> List[str]:
    """
    验证漫画ID列表的有效性

    Args:
        ids: 漫画ID列表

    Returns:
        有效的漫画ID列表

    Raises:
        ValueError: 当ID格式无效时
    """
    valid_ids = []
    for manga_id in ids:
        if not manga_id.isdigit():
            raise ValueError(f"❌ 参数错误！漫画ID '{manga_id}' 不是有效的数字")
        valid_ids.append(manga_id)
    return valid_ids


def format_batch_response(command: str, results: List[Tuple[str, bool, str]]) -> str:
    """
    格式化批量操作的响应消息

    Args:
        command: 命令名称
        results: 结果列表，每个元素为 (manga_id, success, message)

    Returns:
        格式化的响应消息
    """
    if not results:
        return "❌ 没有执行任何操作"

    success_count = sum(1 for _, success, _ in results if success)
    total_count = len(results)

    response = f"📊 批量{command}操作完成\n\n"
    response += f"总计：{total_count} 个漫画\n"
    response += f"成功：{success_count} 个\n"
    response += f"失败：{total_count - success_count} 个\n\n"

    if success_count < total_count:
        response += "❌ 失败详情：\n"
        for manga_id, success, message in results:
            if not success:
                response += f"  • ID {manga_id}: {message}\n"

    return response
