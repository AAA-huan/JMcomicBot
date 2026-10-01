<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from 'vuetify'

import BlankLayout from '@/layouts/BlankLayout.vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const themeStore = useThemeStore()
const theme = useTheme()

const layout = computed(() =>
  route.meta.layout === 'blank' ? BlankLayout : DefaultLayout,
)

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
