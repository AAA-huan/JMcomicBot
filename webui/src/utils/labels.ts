/** 后端枚举值到中文字段与展示色调的映射。 */

export const MANGA_STATUS_LABELS: Record<string, string> = {
  downloaded: '已下载',
  missing_file: '文件缺失',
  invalid: '无效记录',
  deleted: '已删除',
}

export const MANGA_STATUS_COLORS: Record<string, string> = {
  downloaded: 'success',
  missing_file: 'warning',
  invalid: 'error',
  deleted: 'medium-emphasis',
}

export const FILE_STATUS_LABELS: Record<string, string> = {
  ready: '就绪',
  missing: '缺失',
  corrupted: '损坏',
  deleting: '删除中',
  deleted: '已删除',
  invalid_path: '路径异常',
}

export const FILE_STATUS_COLORS: Record<string, string> = {
  ready: 'success',
  missing: 'warning',
  corrupted: 'error',
  deleting: 'info',
  deleted: 'medium-emphasis',
  invalid_path: 'error',
}

export const TASK_TYPE_LABELS: Record<string, string> = {
  download: '下载',
  scan: '扫描',
  repair: '修复',
  delete: '删除',
  backup: '备份',
  verify: '校验',
}

export const TASK_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '进行中',
  succeeded: '成功',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
}

export const TASK_STATUS_COLORS: Record<string, string> = {
  queued: 'info',
  running: 'primary',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'warning',
  interrupted: 'warning',
}

export const TASK_SOURCE_LABELS: Record<string, string> = {
  qq: 'QQ',
  web: 'WebUI',
  system: '系统',
}

export const BACKUP_STATUS_LABELS: Record<string, string> = {
  creating: '创建中',
  ready: '就绪',
  failed: '失败',
  deleted: '已删除',
}

export const BACKUP_STATUS_COLORS: Record<string, string> = {
  creating: 'info',
  ready: 'success',
  failed: 'error',
  deleted: 'medium-emphasis',
}

export const PERMISSION_SCOPE_LABELS: Record<string, string> = {
  group_whitelist: '群白名单',
  private_whitelist: '私聊白名单',
  global_blacklist: '全局黑名单',
  delete_permission_user: '删除权限用户',
}

export const PERMISSION_SCOPE_HINTS: Record<string, string> = {
  group_whitelist: '允许在这些群聊中使用机器人（需 @机器人）',
  private_whitelist: '允许与机器人私聊的用户',
  global_blacklist: '这些用户或群在任何情况下都会被忽略',
  delete_permission_user: '拥有漫画删除命令权限的 QQ 用户',
}

export const SETTING_EFFECT_LABELS: Record<string, string> = {
  immediate: '立即生效',
  restart: '重启生效',
}

export const SETTING_EFFECT_COLORS: Record<string, string> = {
  immediate: 'success',
  restart: 'warning',
}

/** 通用：取映射值，缺省时回退原值并标注未知。 */
export function labelOf(
  mapping: Record<string, string>,
  value: string | null | undefined,
): string {
  if (!value) return '—'
  return mapping[value] ?? value
}

/** 通用：取色调，缺省回退中性色。 */
export function colorOf(
  mapping: Record<string, string>,
  value: string | null | undefined,
): string {
  if (!value) return 'medium-emphasis'
  return mapping[value] ?? 'medium-emphasis'
}
