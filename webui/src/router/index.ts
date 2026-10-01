import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/pages/SetupPage.vue'),
      meta: { public: true, layout: 'blank', title: '首次设置' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/LoginPage.vue'),
      meta: { public: true, layout: 'blank', title: '登录' },
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
      meta: { title: '仪表盘' },
    },
    {
      path: '/library',
      name: 'library',
      component: () => import('@/pages/LibraryPage.vue'),
      meta: { title: '漫画库' },
    },
    {
      path: '/library/:mangaId',
      name: 'manga-detail',
      component: () => import('@/pages/MangaDetailPage.vue'),
      meta: { title: '漫画详情' },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('@/pages/TasksPage.vue'),
      meta: { title: '下载任务' },
    },
    {
      path: '/permissions',
      name: 'permissions',
      component: () => import('@/pages/PermissionsPage.vue'),
      meta: { title: '权限管理' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
      meta: { title: '配置' },
    },
    {
      path: '/maintenance',
      name: 'maintenance',
      component: () => import('@/pages/MaintenancePage.vue'),
      meta: { title: '维护' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/pages/NotFoundPage.vue'),
      meta: { title: '页面不存在' },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    try {
      await auth.refresh()
    } catch {
      // 后端不可用时仍进入登录页，由页面展示错误并提供重试
    }
  }
  if (!auth.initialized && to.name !== 'setup') {
    return { name: 'setup' }
  }
  if (auth.initialized && (to.name === 'login' || to.name === 'setup')) {
    return { name: 'dashboard' }
  }
  if (auth.initialized && !auth.authenticated && !to.meta.public) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} - JMcomicBot 控制台` : 'JMcomicBot 控制台'
})

export default router
