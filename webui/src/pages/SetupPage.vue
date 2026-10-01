<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { errorMessage } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
  if (password.value.length < 12) {
    error.value = '密码至少需要 12 个字符'
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  try {
    await auth.setup(password.value)
    await auth.login(password.value)
    await router.replace({ name: 'dashboard' })
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <v-card class="pa-4 pa-sm-6">
    <h2 class="text-h6 mb-1">首次设置管理员</h2>
    <p class="text-body-2 text-medium-emphasis mb-4">
      只能从本机（127.0.0.1）完成初始化。密码至少 12 个字符，请妥善保管。
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
        autocomplete="new-password"
        :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
        @click:append-inner="showPassword = !showPassword"
      />
      <v-text-field
        v-model="confirmPassword"
        label="确认密码"
        :type="showPassword ? 'text' : 'password'"
        autocomplete="new-password"
        @keyup.enter="submit"
      />
      <v-btn
        type="submit"
        color="primary"
        block
        size="large"
        :loading="submitting"
      >
        创建管理员并登录
      </v-btn>
    </v-form>
  </v-card>
</template>
