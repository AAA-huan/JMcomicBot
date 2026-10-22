<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { getOptionFile, listSettings, updateOptionFile, updateSetting } from '@/api/settings'
import EmptyState from '@/components/EmptyState.vue'
import type { SettingValue, SettingView } from '@/types/api'
import {
  SETTING_EFFECT_COLORS,
  SETTING_EFFECT_LABELS,
  SETTING_ENV_OVERRIDE_HELP,
  SETTING_HELP_TEXTS,
} from '@/utils/labels'

const items = ref<SettingView[]>([])
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const actionNotice = ref('')

const editDialog = ref(false)
const editKey = ref('')
const editTitle = ref('')
const editValueType = ref('')
const editEffect = ref('')
const editSensitive = ref(false)
const editValue = ref<SettingValue>(null)
const editError = ref('')
const editOverriddenByEnv = ref(false)
const saving = ref(false)

// option.yml 编辑器状态
const optionContent = ref('')
const optionLoading = ref(false)
const optionSaving = ref(false)
const optionError = ref('')
const optionNotice = ref('')
const optionDirty = ref(false)

/** 按注册表顺序分组，保持后端返回的分组顺序。 */
const groups = computed(() => {
  const map = new Map<string, SettingView[]>()
  for (const item of items.value) {
    const bucket = map.get(item.group)
    if (bucket) bucket.push(item)
    else map.set(item.group, [item])
  }
  return [...map.entries()].map(([name, entries]) => ({ name, entries }))
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    items.value = (await listSettings()).items
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function loadOption(): Promise<void> {
  optionLoading.value = true
  optionError.value = ''
  try {
    const result = await getOptionFile()
    optionContent.value = result.content
    optionDirty.value = false
  } catch (err) {
    optionError.value = errorMessage(err)
  } finally {
    optionLoading.value = false
  }
}

async function saveOption(): Promise<void> {
  optionSaving.value = true
  optionError.value = ''
  optionNotice.value = ''
  try {
    const result = await updateOptionFile(optionContent.value)
    optionContent.value = result.content
    optionDirty.value = false
    optionNotice.value = 'option.yml 已保存，下一个下载任务即生效（无需重启）'
  } catch (err) {
    optionError.value = errorMessage(err)
  } finally {
    optionSaving.value = false
  }
}

function displayValue(item: SettingView): string {
  if (item.value === null || item.value === undefined || item.value === '') {
    return item.sensitive ? '未设置' : '—'
  }
  if (item.value_type === 'bool') return item.value ? '开启' : '关闭'
  return String(item.value)
}

function openEdit(item: SettingView): void {
  editKey.value = item.key
  editTitle.value = item.title
  editValueType.value = item.value_type
  editEffect.value = item.effect
  editSensitive.value = item.sensitive
  editValue.value = item.value
  editError.value = ''
  editOverriddenByEnv.value = Boolean(item.overridden_by_env)
  editDialog.value = true
}

async function saveSetting(): Promise<void> {
  editError.value = ''
  let payload: SettingValue
  if (editValueType.value === 'bool') {
    payload = Boolean(editValue.value)
  } else if (editValueType.value === 'int') {
    const parsed = Number(editValue.value)
    if (!Number.isInteger(parsed)) {
      editError.value = '请输入整数'
      return
    }
    payload = parsed
  } else if (editValueType.value === 'float') {
    const parsed = Number(editValue.value)
    if (Number.isNaN(parsed)) {
      editError.value = '请输入数字'
      return
    }
    payload = parsed
  } else {
    payload = String(editValue.value ?? '')
  }

  saving.value = true
  try {
    const view = await updateSetting(editKey.value, payload)
    actionNotice.value = `${view.title} 已更新（${
      SETTING_EFFECT_LABELS[view.effect] ?? view.effect
    }）`
    editDialog.value = false
    await load()
  } catch (err) {
    editError.value = errorMessage(err)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
  void loadOption()
})
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

    <EmptyState
      v-if="!loading && items.length === 0"
      icon="mdi-cog-outline"
      title="没有可展示的配置"
      description="配置注册表为空，请检查后端配置。"
    />

    <v-card v-for="group in groups" :key="group.name" class="mb-4">
      <v-card-title class="text-subtitle-1">{{ group.name }}</v-card-title>
      <v-divider />
      <v-list lines="two">
        <template v-for="(item, index) in group.entries" :key="item.key">
          <v-divider v-if="index > 0" />
          <v-list-item>
            <v-list-item-title class="text-wrap">
              {{ item.title }}
              <v-icon
                v-if="item.sensitive"
                size="16"
                class="ml-1"
                color="warning"
                aria-label="敏感配置"
              >
                mdi-shield-lock-outline
              </v-icon>
              <v-icon
                v-else-if="!item.editable"
                size="16"
                class="ml-1"
                color="medium-emphasis"
                aria-label="只读配置"
              >
                mdi-lock-outline
              </v-icon>
            </v-list-item-title>
            <v-list-item-subtitle class="text-wrap">
              {{ item.key }} · {{ item.apply_target }}
              <div
                v-if="SETTING_HELP_TEXTS[item.key]"
                class="text-caption text-medium-emphasis mt-1"
              >
                {{ SETTING_HELP_TEXTS[item.key] }}
              </div>
              <div
                v-if="item.overridden_by_env"
                class="text-caption text-warning mt-1"
              >
                {{ SETTING_ENV_OVERRIDE_HELP }}
              </div>
            </v-list-item-subtitle>
            <template #append>
              <div class="d-flex align-center ga-2">
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="SETTING_EFFECT_COLORS[item.effect] ?? 'medium-emphasis'"
                >
                  {{ item.restart_required ? '待重启' : (SETTING_EFFECT_LABELS[item.effect] ?? item.effect) }}
                </v-chip>
                <span class="text-body-2 text-no-wrap" style="min-width: 72px; text-align: right">
                  {{ displayValue(item) }}
                </span>
                <v-btn
                  v-if="item.editable"
                  size="small"
                  variant="text"
                  color="primary"
                  :aria-label="`修改${item.title}`"
                  @click="openEdit(item)"
                >
                  修改
                </v-btn>
              </div>
            </template>
          </v-list-item>
        </template>
      </v-list>
    </v-card>

    <v-card class="mb-4">
      <v-card-title class="text-subtitle-1">下载器配置（option.yml）</v-card-title>
      <v-divider />
      <v-card-text>
        <v-alert
          v-if="optionError"
          type="error"
          variant="tonal"
          density="comfortable"
          class="mb-3"
        >
          {{ optionError }}
        </v-alert>
        <v-alert
          v-if="optionNotice"
          type="success"
          variant="tonal"
          density="comfortable"
          closable
          class="mb-3"
          @click:close="optionNotice = ''"
        >
          {{ optionNotice }}
        </v-alert>
        <p class="text-body-2 text-medium-emphasis mb-2">
          jmcomic 下载器配置；保存后下一个下载任务即生效，无需重启。img2pdf 与进度插件由程序自动注入并覆盖关键项。
        </p>
        <v-textarea
          v-model="optionContent"
          :loading="optionLoading"
          rows="14"
          auto-grow
          spellcheck="false"
          class="font-monospace"
          :style="{ fontFamily: 'monospace' }"
          placeholder="download:\n  image:\n    suffix: .jpg"
          @update:model-value="optionDirty = true"
        />
        <div v-if="optionDirty" class="text-caption text-medium-emphasis">
          有未保存的改动
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="optionSaving" @click="loadOption">重新加载</v-btn>
        <v-btn color="primary" :loading="optionSaving" :disabled="!optionDirty" @click="saveOption">
          保存
        </v-btn>
      </v-card-actions>
    </v-card>

    <v-dialog v-model="editDialog" max-width="480">
      <v-card>
        <v-card-title>修改「{{ editTitle }}」</v-card-title>
        <v-card-text>
          <v-alert
            v-if="editError"
            type="error"
            variant="tonal"
            density="comfortable"
            class="mb-3"
          >
            {{ editError }}
          </v-alert>
          <v-alert
            v-if="editOverriddenByEnv"
            type="warning"
            variant="tonal"
            density="comfortable"
            class="mb-3"
          >
            {{ SETTING_ENV_OVERRIDE_HELP }}
          </v-alert>
          <v-switch
            v-if="editValueType === 'bool'"
            v-model="editValue"
            label="开启"
            color="primary"
            hide-details
          />
          <v-text-field
            v-else-if="editValueType === 'int' || editValueType === 'float'"
            v-model="editValue"
            type="number"
            label="新值"
            hint="保存时由后端校验取值范围"
            persistent-hint
          />
          <v-text-field
            v-else
            v-model="editValue"
            type="text"
            hint="令牌留空可清除（NAPCAT_TOKEN、WEBUI_DEV_ORIGINS 允许空值）"
            persistent-hint
            label="新值"
          />
          <div class="text-caption text-medium-emphasis mt-3">
            <div v-if="editKey === 'DB_PATH' || editKey === 'MANGA_DOWNLOAD_PATH'">更改目录不会自动迁移已有数据库或漫画文件。</div>
            生效方式：{{ SETTING_EFFECT_LABELS[editEffect] ?? editEffect }}
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="saving" @click="saveSetting">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
