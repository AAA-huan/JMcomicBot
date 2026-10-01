<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { errorMessage } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const password = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')

/** 只接受站内路径，避免开放重定向。 */
function safeRedirect(value: unknown): string {
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) {
    return value
  }
  return '/'
}

async function submit(): Promise<void> {
  error.value = ''
  if (!password.value) {
    error.value = '请输入管理员密码'
    return
  }
  submitting.value = true
  try {
    await auth.login(password.value)
    await router.replace(safeRedirect(route.query.redirect))
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <v-card class="pa-4 pa-sm-6">
    <h2 class="text-h6 mb-1">登录</h2>
    <p class="text-body-2 text-medium-emphasis mb-4">
      单管理员控制台，请使用初始化时设置的密码登录。
    </p>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
    >
      {{ error }}
    </v-alert>

    <v-form @submit.prevent="submit">
      <v-text-field
        v-model="password"
        label="管理员密码"
        :type="showPassword ? 'text' : 'password'"
        autocomplete="current-password"
        :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
        @click:append-inner="showPassword = !showPassword"
      />
      <v-btn
        type="submit"
        color="primary"
        block
        size="large"
        :loading="submitting"
      >
        登录
      </v-btn>
    </v-form>
  </v-card>
</template>
