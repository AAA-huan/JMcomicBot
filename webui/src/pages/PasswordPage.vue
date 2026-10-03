<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { changePassword } from '@/api/auth'
import { errorMessage } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const oldPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const error = ref('')
const saving = ref(false)

async function submit(): Promise<void> {
  if (saving.value) return
  error.value = ''
  if (!oldPassword.value || newPassword.value.length < 6 || !newPassword.value.trim()) {
    error.value = '请填写旧密码，新密码至少需要 6 个字符且不能全为空白'
    return
  }
  if (newPassword.value !== confirmation.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  saving.value = true
  try {
    await changePassword(oldPassword.value, newPassword.value)
    oldPassword.value = ''
    newPassword.value = ''
    confirmation.value = ''
    auth.clearSession()
    await router.replace({ name: 'login', query: { password_changed: '1' } })
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-card class="mx-auto" max-width="520">
    <v-card-title>修改管理员密码</v-card-title>
    <v-card-text>
      <p class="mb-4">修改后所有设备的登录会话都会失效，请使用新密码重新登录。</p>
      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
      <v-form @submit.prevent="submit">
        <v-text-field v-model="oldPassword" label="旧密码" type="password" autocomplete="current-password" :disabled="saving" maxlength="1024" />
        <v-text-field v-model="newPassword" label="新密码" type="password" autocomplete="new-password" :disabled="saving" maxlength="1024" />
        <v-text-field v-model="confirmation" label="确认新密码" type="password" autocomplete="new-password" :disabled="saving" maxlength="1024" />
        <v-btn type="submit" color="primary" block :loading="saving">修改密码</v-btn>
      </v-form>
    </v-card-text>
  </v-card>
</template>
