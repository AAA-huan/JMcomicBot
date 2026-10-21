/** 剪贴板工具：安全上下文用 navigator.clipboard，局域网 http 回退 execCommand。 */

/**
 * 复制文本到剪贴板。
 *
 * 局域网 http 属非安全上下文（navigator.clipboard 不可用），必须走
 * 隐藏 textarea + document.execCommand('copy') 回退。
 *
 * @returns 是否复制成功
 */
export async function copyText(text: string): Promise<boolean> {
  // 安全上下文（https / localhost）优先用标准 Clipboard API
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限被拒或剪贴板不可用，回退到 execCommand
    }
  }
  return fallbackCopy(text)
}

/** 回退方案：隐藏 textarea + execCommand('copy')，兼容非安全上下文。 */
function fallbackCopy(text: string): boolean {
  const textarea = document.createElement('textarea')
  textarea.value = text
  // 隐藏在视口外，避免影响布局和滚动
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  textarea.setAttribute('readonly', '')
  document.body.appendChild(textarea)
  let succeeded = false
  try {
    textarea.select()
    succeeded = document.execCommand('copy')
  } catch {
    succeeded = false
  } finally {
    document.body.removeChild(textarea)
  }
  return succeeded
}
