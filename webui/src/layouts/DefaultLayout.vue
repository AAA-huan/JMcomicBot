<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'
import { useRoute, useRouter } from 'vue-router'

import { EventClient } from '@/api/events'
import { emitConnection, emitEvent } from '@/api/eventStream'
import { errorMessage } from '@/api/client'
import {
  getRecoveryStatus,
  resolveRecovery,
  type RecoveryStatus,
} from '@/api/system'
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
  { title: '漫画下载', to: '/download', icon: 'mdi-cloud-download-outline' },
  { title: 'JM 收藏导入', to: '/jm-favorites', icon: 'mdi-bookmark-plus-outline' },
  { title: '任务管理', to: '/tasks', icon: 'mdi-download-outline' },
  { title: '权限管理', to: '/permissions', icon: 'mdi-account-lock-outline' },
  { title: '配置', to: '/settings', icon: 'mdi-cog-outline' },
  { title: '文档', to: '/documents', icon: 'mdi-book-open-outline' },
  { title: '维护', to: '/maintenance', icon: 'mdi-tools' },
  { title: '操作审计', to: '/audit', icon: 'mdi-history' },
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

// 启动恢复询问：仅在有待处理任务时显示横幅，任一渠道操作后消失
const recovery = ref<RecoveryStatus | null>(null)
const recoveryRemaining = ref(0)
const recoveryBusy = ref(false)
const recoveryError = ref('')
let recoveryPollTimer: number | null = null
let recoveryTickTimer: number | null = null

// 桌面端侧栏常驻展开，移动端默认收起并按需打开
watch(
  mobile,
  (isMobile) => {
    drawer.value = !isMobile
  },
  { immediate: true },
)

/** 移动端点击导航后关闭抽屉；桌面端侧栏保持展开。 */
function closeDrawerOnMobile(): void {
  if (mobile.value) drawer.value = false
}
let eventClient: EventClient | null = null
let hasConnectedOnce = false

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
  startRecoveryPolling()
  eventClient = new EventClient({
    onEvent: (event) => {
      system.applyEvent(event)
      emitEvent(event)
    },
    onOpen: () => {
      // 重连成功必须重新拉取完整 REST 快照，并通知页面补齐断线期间的数据
      const reconnected = hasConnectedOnce
      hasConnectedOnce = true
      system.eventsConnected = true
      void system.refresh()
      if (reconnected) emitConnection()
    },
    onClose: () => {
      system.eventsConnected = false
    },
  })
  eventClient.connect()
})

onBeforeUnmount(() => {
  stopRecoveryPolling()
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

/** 轮询启动恢复询问状态，本地每秒递减倒计时避免界面停滞。 */
function startRecoveryPolling(): void {
  void refreshRecoveryStatus()
  recoveryPollTimer = window.setInterval(refreshRecoveryStatus, 3000)
  recoveryTickTimer = window.setInterval(() => {
    if (recovery.value !== null && recoveryRemaining.value > 0) {
      recoveryRemaining.value -= 1
      if (recoveryRemaining.value <= 0) recovery.value = null
    }
  }, 1000)
}

function stopRecoveryPolling(): void {
  if (recoveryPollTimer !== null) {
    clearInterval(recoveryPollTimer)
    recoveryPollTimer = null
  }
  if (recoveryTickTimer !== null) {
    clearInterval(recoveryTickTimer)
    recoveryTickTimer = null
  }
}

async function refreshRecoveryStatus(): Promise<void> {
  try {
    const status = await getRecoveryStatus()
    if (status.pending) {
      recovery.value = status
      recoveryRemaining.value = status.remaining_seconds
    } else {
      recovery.value = null
    }
  } catch {
    // 状态查询失败不应干扰主界面，下次轮询继续尝试
  }
}

/** 提交恢复决定，失败时在横幅内提示中文错误。 */
async function decideRecovery(action: 'continue' | 'cancel'): Promise<void> {
  recoveryBusy.value = true
  recoveryError.value = ''
  try {
    await resolveRecovery(action)
    recovery.value = null
  } catch (err) {
    recoveryError.value = errorMessage(err)
  } finally {
    recoveryBusy.value = false
  }
}

/** 将剩余秒数格式化为 mm:ss。 */
function formatRecoveryRemaining(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remaining = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`
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
          @click="closeDrawerOnMobile"
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
          <v-list-item prepend-icon="mdi-lock-reset" title="修改密码" to="/password" />
          <v-list-item
            prepend-icon="mdi-logout"
            title="退出登录"
            @click="handleLogout"
          />
        </v-list>
      </v-menu>
    </v-app-bar>

    <v-main>
      <v-alert
        v-if="recovery"
        type="warning"
        variant="tonal"
        prominent
        density="comfortable"
        class="mb-0"
      >
        <div class="d-flex flex-wrap align-center ga-2">
          <v-icon>mdi-progress-alert</v-icon>
          <span>
            检测到 {{ recovery.task_count }} 个中断下载任务，是否继续？剩余
            {{ formatRecoveryRemaining(recoveryRemaining) }}
          </span>
          <v-spacer />
          <v-btn
            size="small"
            color="primary"
            variant="tonal"
            :loading="recoveryBusy"
            @click="decideRecovery('continue')"
          >
            继续
          </v-btn>
          <v-btn
            size="small"
            variant="text"
            :disabled="recoveryBusy"
            @click="decideRecovery('cancel')"
          >
            取消
          </v-btn>
        </div>
        <div v-if="recoveryError" class="text-caption mt-1">{{ recoveryError }}</div>
      </v-alert>
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
