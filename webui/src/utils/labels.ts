/** 后端枚举值到中文字段与展示色调的映射。 */

export const MANGA_STATUS_LABELS: Record<string, string> = {
  downloaded: '已下载',
  favorited: '已收藏未下载',
  missing_file: '文件缺失',
  invalid: '无效记录',
  deleted: '已删除',
  blacklisted: '已拉黑',
}

export const MANGA_STATUS_COLORS: Record<string, string> = {
  downloaded: 'success',
  favorited: 'info',
  missing_file: 'warning',
  invalid: 'error',
  deleted: 'medium-emphasis',
  blacklisted: 'error',
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
  blacklist: '黑名单',
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

export const PERMISSION_SCOPE_LABELS: Record<string, string> = {
  group_whitelist: '群白名单',
  private_whitelist: '私聊白名单',
  global_blacklist: '全局黑名单',
  delete_permission_user: '删除与拉黑权限用户',
}

export const PERMISSION_SCOPE_HINTS: Record<string, string> = {
  group_whitelist: '允许在这些群聊中使用机器人（需 @机器人）',
  private_whitelist: '允许与机器人私聊的用户',
  global_blacklist: '这些用户或群在任何情况下都会被忽略',
  delete_permission_user: '拥有漫画删除与拉黑命令权限的 QQ 用户；拉黑权限与删除权限共用此名单',
}

/** 配置项补充说明，未列出的配置项不显示额外帮助文案。 */
export const SETTING_HELP_TEXTS: Record<string, string> = {
  BLACKLIST_DELETE_BINDING: '默认关闭。开启后拉黑漫画时同步执行删除，删除漫画时同步加入黑名单；修改后需重启机器人生效。',
}

export const SETTING_EFFECT_LABELS: Record<string, string> = {
  immediate: '立即生效',
  restart: '重启生效',
}

export const SETTING_EFFECT_COLORS: Record<string, string> = {
  immediate: 'success',
  restart: 'warning',
}

/** 启动项被同名环境变量覆盖时的统一提示。 */
export const SETTING_ENV_OVERRIDE_HELP =
  '检测到同名环境变量，当前值来自环境变量。修改后通过网页重启会清除该覆盖并以 .env 为准；手动启动时环境变量仍优先。'

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
