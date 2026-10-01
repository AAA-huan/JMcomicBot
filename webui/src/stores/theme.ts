import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'jmbot_theme'

function readStoredMode(): ThemeMode {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

/** 主题模式：浅色/深色/跟随系统，持久化到本地存储。 */
export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredMode())
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const systemDark = ref(media.matches)

  media.addEventListener('change', (event) => {
    systemDark.value = event.matches
  })

  const isDark = computed(
    () => mode.value === 'dark' || (mode.value === 'system' && systemDark.value),
  )
  const themeName = computed(() => (isDark.value ? 'jmbotDark' : 'jmbotLight'))

  watch(mode, (value) => {
    window.localStorage.setItem(STORAGE_KEY, value)
  })

  function setMode(value: ThemeMode): void {
    mode.value = value
  }

  function cycleMode(): void {
    const order: ThemeMode[] = ['system', 'light', 'dark']
    const index = order.indexOf(mode.value)
    mode.value = order[(index + 1) % order.length]
  }

  return { mode, isDark, themeName, setMode, cycleMode }
})
