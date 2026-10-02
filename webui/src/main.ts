import { createPinia } from 'pinia'
import { createApp } from 'vue'

import { setUnauthorizedHandler } from '@/api/client'
import App from '@/App.vue'
import { vuetify } from '@/plugins/vuetify'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(vuetify)

// 会话过期统一回到登录页，避免在多个页面重复处理 401
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  auth.clearSession()
  const current = router.currentRoute.value
  if (current.name !== 'login') {
    void router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
})

app.mount('#app')
