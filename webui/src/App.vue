<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from 'vuetify'

import BlankLayout from '@/layouts/BlankLayout.vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import ReaderLayout from '@/layouts/ReaderLayout.vue'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const themeStore = useThemeStore()
const theme = useTheme()

const layout = computed(() => {
  if (route.meta.layout === 'blank') return BlankLayout
  if (route.meta.layout === 'reader') return ReaderLayout
  return DefaultLayout
})

watchEffect(() => {
  theme.global.name.value = themeStore.themeName
})
</script>

<template>
  <component :is="layout">
    <router-view />
  </component>
</template>

<style>
html,
body,
#app {
  height: 100%;
}

body {
  overflow-x: hidden;
  min-width: 320px;
}

/* 移动端操作按钮横向滚动，避免大量按钮堆叠换行 */
.action-scroll {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.action-scroll--mobile {
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
  scrollbar-width: thin;
  -webkit-overflow-scrolling: touch;
}

.action-scroll--mobile > * {
  flex: 0 0 auto;
}
</style>
