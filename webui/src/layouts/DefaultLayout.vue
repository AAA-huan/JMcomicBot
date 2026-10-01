<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useDisplay } from 'vuetify'
import { useRoute, useRouter } from 'vue-router'

import { EventClient } from '@/api/events'
import { emitEvent } from '@/api/eventStream'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import { useThemeStore } from '@/stores/theme'

interface NavItem {
  title: string
  to: string
  icon: string
}

const navItems: NavItem[] = [
  { title: '仪表盘', to: '/', icon: 'mdi-view-dashboard-outline' },
  { title: '漫画库', to: '/library', icon: 'mdi-bookshelf' },
  { title: '下载任务', to: '/tasks', icon: 'mdi-download-outline' },
  { title: '权限管理', to: '/permissions', icon: 'mdi-account-lock-outline' },
  { title: '配置', to: '/settings', icon: 'mdi-cog-outline' },
  { title: '维护', to: '/maintenance', icon: 'mdi-tools' },
]

const mobileNavItems = navItems.filter((item) =>
  ['/', '/library', '/tasks'].includes(item.to),
)

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()
const auth = useAuthStore()
const system = useSystemStore()
const theme = useThemeStore()

const drawer = ref(false)
let eventClient: EventClient | null = null

const pageTitle = (): string =>
  typeof route.meta.title === 'string' ? route.meta.title : 'JMcomicBot'

const activeSection = (): string => {
  const path = route.path
  if (path === '/') return '/'
  const match = mobileNavItems.find(
    (item) => path === item.to || path.startsWith(`${item.to}/`),
  )
  return match?.to ?? ''
}

const themeIcon = (): string => {
  if (theme.mode === 'dark') return 'mdi-weather-night'
  if (theme.mode === 'light') return 'mdi-white-balance-sunny'
  return 'mdi-theme-light-dark'
}

const themeLabel = (): string =>
  theme.mode === 'dark' ? '深色' : theme.mode === 'light' ? '浅色' : '跟随系统'

onMounted(async () => {
  await system.refresh()
  eventClient = new EventClient({
    onEvent: (event) => {
      system.applyEvent(event)
      emitEvent(event)
    },
    onOpen: () => {
      // 重连成功必须重新拉取完整 REST 快照
      system.eventsConnected = true
      void system.refresh()
    },
    onClose: () => {
      system.eventsConnected = false
    },
  })
  eventClient.connect()
})

onBeforeUnmount(() => {
  eventClient?.disconnect()
  eventClient = null
  system.eventsConnected = false
})

async function handleLogout(): Promise<void> {
  eventClient?.disconnect()
  system.eventsConnected = false
  try {
    await auth.logout()
  } catch {
    // 会话可能已过期，退出登录不需要阻断
    auth.clearSession()
  }
  await router.replace({ name: 'login' })
}
</script>

<template>
  <v-app>
    <v-navigation-drawer v-model="drawer" :permanent="!mobile" :temporary="mobile">
      <div class="d-flex align-center px-4 py-4">
        <v-icon color="primary" size="32">mdi-robot-happy-outline</v-icon>
        <div class="ml-3">
          <div class="text-subtitle-1 font-weight-medium">JMcomicBot</div>
          <div class="text-caption text-medium-emphasis">管理控制台</div>
        </div>
      </div>
      <v-divider />
      <v-list nav density="comfortable">
        <v-list-item
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="item.title"
          @click="drawer = false"
        />
      </v-list>
    </v-navigation-drawer>

    <v-app-bar flat border>
      <v-app-bar-nav-icon v-if="mobile" aria-label="打开菜单" @click="drawer = !drawer" />
      <v-app-bar-title class="text-truncate">{{ pageTitle() }}</v-app-bar-title>

      <v-tooltip :text="system.eventsConnected ? '实时推送已连接' : '实时推送已断开'">
        <template #activator="{ props }">
          <v-icon
            v-bind="props"
            :color="system.eventsConnected ? 'success' : 'warning'"
            class="mr-1"
            :aria-label="system.eventsConnected ? '实时推送已连接' : '实时推送已断开'"
          >
            {{ system.eventsConnected ? 'mdi-access-point' : 'mdi-access-point-off' }}
          </v-icon>
        </template>
      </v-tooltip>

      <v-chip
        v-if="!mobile"
        class="mr-2"
        size="small"
        variant="tonal"
        :color="system.status?.napcat_connected ? 'success' : 'error'"
      >
        NapCat {{ system.status?.napcat_connected ? '已连接' : '未连接' }}
      </v-chip>

      <v-tooltip :text="`主题：${themeLabel()}`">
        <template #activator="{ props }">
          <v-btn
            v-bind="props"
            :icon="themeIcon()"
            variant="text"
            aria-label="切换主题"
            @click="theme.cycleMode()"
          />
        </template>
      </v-tooltip>

      <v-menu location="bottom end">
        <template #activator="{ props }">
          <v-btn v-bind="props" icon="mdi-account-circle-outline" variant="text" aria-label="账户菜单" />
        </template>
        <v-list>
          <v-list-item title="管理员" subtitle="单管理员控制台" />
          <v-divider />
          <v-list-item
            prepend-icon="mdi-logout"
            title="退出登录"
            @click="handleLogout"
          />
        </v-list>
      </v-menu>
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-3 pa-md-6">
        <slot />
      </v-container>
    </v-main>

    <v-bottom-navigation v-if="mobile" :model-value="activeSection()" grow>
      <v-btn
        v-for="item in mobileNavItems"
        :key="item.to"
        :value="item.to"
        :to="item.to"
        :icon="item.icon"
        :text="item.title"
      />
      <v-btn value="more" icon="mdi-dots-horizontal" text="更多" @click="drawer = true" />
    </v-bottom-navigation>
  </v-app>
</template>
