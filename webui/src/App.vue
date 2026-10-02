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
</style>
