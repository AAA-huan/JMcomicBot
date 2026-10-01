<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { addPermission, getPermissions, removePermission } from '@/api/permissions'
import EmptyState from '@/components/EmptyState.vue'
import type { CachedGroup, CachedUser } from '@/types/api'
import { formatDateTime } from '@/utils/format'
import {
  PERMISSION_SCOPE_HINTS,
  PERMISSION_SCOPE_LABELS,
} from '@/utils/labels'

const scopeOrder = [
  'group_whitelist',
  'private_whitelist',
  'global_blacklist',
  'delete_permission_user',
]

const scopes = ref<Record<string, string[]>>({})
const cachedUsers = ref<CachedUser[]>([])
const cachedGroups = ref<CachedGroup[]>([])
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const actionNotice = ref('')

const addInputs = reactive<Record<string, string>>({
  group_whitelist: '',
  private_whitelist: '',
  global_blacklist: '',
  delete_permission_user: '',
})
const adding = reactive<Record<string, boolean>>({
  group_whitelist: false,
  private_whitelist: false,
  global_blacklist: false,
  delete_permission_user: false,
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await getPermissions()
    scopes.value = data.scopes
    cachedUsers.value = data.cached_users
    cachedGroups.value = data.cached_groups
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function isValidId(value: string): boolean {
  return /^\d{1,64}$/.test(value)
}

async function addToScope(scope: string, rawValue: string): Promise<void> {
  const value = rawValue.trim()
  actionError.value = ''
  actionNotice.value = ''
  if (!value) {
    actionError.value = '请输入 QQ 号或群号'
    return
  }
  if (!isValidId(value)) {
    actionError.value = 'ID 必须是 1-64 位数字'
    return
  }
  adding[scope] = true
  try {
    const result = await addPermission(scope, value)
    actionNotice.value = result.changed
      ? `已添加到${PERMISSION_SCOPE_LABELS[scope] ?? scope}：${value}`
      : `${value} 已在该名单中`
    addInputs[scope] = ''
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    adding[scope] = false
  }
}

async function removeFromScope(scope: string, value: string): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await removePermission(scope, value)
    actionNotice.value = result.changed
      ? `已从${PERMISSION_SCOPE_LABELS[scope] ?? scope}移除：${value}`
      : `${value} 不在该名单中`
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal" density="comfortable" class="mb-4">
      {{ error }}
      <template #append>
        <v-btn size="small" variant="text" @click="load">重试</v-btn>
      </template>
    </v-alert>
    <v-alert
      v-if="actionError"
      type="error"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="actionError = ''"
    >
      {{ actionError }}
    </v-alert>
    <v-alert
      v-if="actionNotice"
      type="success"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="actionNotice = ''"
    >
      {{ actionNotice }}
    </v-alert>

    <v-progress-linear v-if="loading" indeterminate class="mb-4" />

    <v-row dense>
      <v-col v-for="scope in scopeOrder" :key="scope" cols="12" md="6">
        <v-card class="h-100 d-flex flex-column">
          <v-card-title class="text-subtitle-1">
            {{ PERMISSION_SCOPE_LABELS[scope] ?? scope }}
            <v-chip size="x-small" variant="tonal" class="ml-2">
              {{ scopes[scope]?.length ?? 0 }}
            </v-chip>
          </v-card-title>
          <v-card-subtitle class="text-wrap">
            {{ PERMISSION_SCOPE_HINTS[scope] ?? '' }}
          </v-card-subtitle>
          <v-card-text class="flex-grow-1">
            <div v-if="(scopes[scope]?.length ?? 0) === 0" class="text-caption text-medium-emphasis">
              名单为空
            </div>
            <v-chip
              v-for="value in scopes[scope] ?? []"
              :key="value"
              closable
              size="small"
              variant="tonal"
              class="mr-1 mb-1"
              @click:close="removeFromScope(scope, value)"
            >
              {{ value }}
            </v-chip>
          </v-card-text>
          <v-divider />
          <v-card-actions>
            <v-text-field
              v-model="addInputs[scope]"
              label="QQ 号 / 群号"
              density="compact"
              hide-details
              @keyup.enter="addToScope(scope, addInputs[scope])"
            />
            <v-btn
              color="primary"
              variant="tonal"
              :loading="adding[scope]"
              aria-label="添加"
              @click="addToScope(scope, addInputs[scope])"
            >
              添加
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <v-row dense class="mt-1">
      <v-col cols="12" md="6">
        <v-card class="h-100">
          <v-card-title class="text-subtitle-1">缓存的 QQ 用户</v-card-title>
          <v-card-subtitle>来自机器人最近处理过的消息</v-card-subtitle>
          <EmptyState
            v-if="cachedUsers.length === 0"
            icon="mdi-account-outline"
            title="暂无缓存用户"
            description="机器人收到消息后会自动缓存用户信息。"
          />
          <v-list v-else lines="two">
            <v-list-item v-for="user in cachedUsers" :key="user.id">
              <v-list-item-title>{{ user.nickname || user.id }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ user.id }} · 最近出现 {{ formatDateTime(user.last_seen_at) }}
              </v-list-item-subtitle>
              <template #append>
                <v-menu location="bottom end">
                  <template #activator="{ props }">
                    <v-btn
                      v-bind="props"
                      icon="mdi-account-plus-outline"
                      size="small"
                      variant="text"
                      aria-label="加入名单"
                    />
                  </template>
                  <v-list density="compact">
                    <v-list-item
                      v-for="scope in scopeOrder"
                      :key="scope"
                      :title="PERMISSION_SCOPE_LABELS[scope] ?? scope"
                      @click="addToScope(scope, user.id)"
                    />
                  </v-list>
                </v-menu>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
      <v-col cols="12" md="6">
        <v-card class="h-100">
          <v-card-title class="text-subtitle-1">缓存的 QQ 群</v-card-title>
          <v-card-subtitle>来自机器人最近处理过的消息</v-card-subtitle>
          <EmptyState
            v-if="cachedGroups.length === 0"
            icon="mdi-account-group-outline"
            title="暂无缓存群组"
            description="机器人收到群消息后会自动缓存群信息。"
          />
          <v-list v-else lines="two">
            <v-list-item v-for="group in cachedGroups" :key="group.id">
              <v-list-item-title>{{ group.group_name || group.id }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ group.id }} · 最近出现 {{ formatDateTime(group.last_seen_at) }}
              </v-list-item-subtitle>
              <template #append>
                <v-menu location="bottom end">
                  <template #activator="{ props }">
                    <v-btn
                      v-bind="props"
                      icon="mdi-account-plus-outline"
                      size="small"
                      variant="text"
                      aria-label="加入名单"
                    />
                  </template>
                  <v-list density="compact">
                    <v-list-item
                      v-for="scope in scopeOrder"
                      :key="scope"
                      :title="PERMISSION_SCOPE_LABELS[scope] ?? scope"
                      @click="addToScope(scope, group.id)"
                    />
                  </v-list>
                </v-menu>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>
