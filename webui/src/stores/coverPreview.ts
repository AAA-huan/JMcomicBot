import { ref, watch } from 'vue'

// 两个页面共享开关，并保存到当前浏览器，刷新后保持用户选择。
const coverPreview = ref(window.localStorage.getItem('jmbot_cover_preview') === 'true')
watch(coverPreview, (enabled) => {
  window.localStorage.setItem('jmbot_cover_preview', String(enabled))
})

export function useCoverPreview() {
  return { coverPreview }
}
