<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { errorMessage } from '@/api/client'
import { getReaderSettings, updateReaderSettings } from '@/api/reader'
import { getOptionFile, listSettings, updateOptionFile, updateSetting } from '@/api/settings'
import EmptyState from '@/components/EmptyState.vue'
import { PREFETCH_OPTIONS, type ReadingSettings } from '@/reader/types'
import type { SettingValue, SettingView } from '@/types/api'
import {
  SETTING_EFFECT_COLORS,
  SETTING_EFFECT_LABELS,
  SETTING_ENV_OVERRIDE_HELP,
  SETTING_HELP_TEXTS,
} from '@/utils/labels'

const READING_MODE_OPTIONS = [
  { value: 'normal', title: '普通模式', description: '左→右阅读，左滑 / ArrowRight 翻下页' },
  { value: 'manga', title: '日漫模式', description: '右→左阅读，右滑 / ArrowLeft 翻下页' },
  { value: 'scroll', title: '滚动模式', description: '上→下阅读，下滑 / ArrowDown 翻下页' },
] as const

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

// 阅读器偏好设置状态，与阅读器工具栏共用同一份后端数据
const EMPTY_READER_SETTINGS: ReadingSettings = {
  reading_mode: 'normal',
  continuous: false,
  click_to_turn: false,
  reverse_click: false,
  dark_background: false,
  prefetch_pages: 1,
  updated_at: null,
}
const readerForm = ref<ReadingSettings>({ ...EMPTY_READER_SETTINGS })
const readerLoaded = ref<ReadingSettings | null>(null)
const readerLoading = ref(false)
const readerSaving = ref(false)
const readerError = ref('')
const readerNotice = ref('')

const readerDirty = computed(() => {
  const form = readerForm.value
  const loaded = readerLoaded.value
  if (!loaded) return false
  return (
    form.reading_mode !== loaded.reading_mode ||
    form.continuous !== loaded.continuous ||
    form.click_to_turn !== loaded.click_to_turn ||
    form.reverse_click !== loaded.reverse_click ||
    form.dark_background !== loaded.dark_background ||
    form.prefetch_pages !== loaded.prefetch_pages
  )
})

const selectedReadingMode = computed(
  () =>
    READING_MODE_OPTIONS.find(
      (option) => option.value === readerForm.value.reading_mode,
    ) ?? READING_MODE_OPTIONS[0],
)

// 关闭点击翻页时同步关闭反转，避免提交后端必然拒绝的组合
watch(
  () => readerForm.value.click_to_turn,
  (enabled) => {
    if (!enabled) readerForm.value.reverse_click = false
  },
)

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

async function loadReader(): Promise<void> {
  readerLoading.value = true
  readerError.value = ''
  try {
    const settings = await getReaderSettings()
    readerForm.value = { ...settings }
    readerLoaded.value = { ...settings }
  } catch (err) {
    readerError.value = errorMessage(err)
  } finally {
    readerLoading.value = false
  }
}

async function saveReader(): Promise<void> {
  const form = readerForm.value
  if (!form || !readerLoaded.value) return
  readerSaving.value = true
  readerError.value = ''
  readerNotice.value = ''
  try {
    const updated = await updateReaderSettings({
      reading_mode: form.reading_mode,
      continuous: form.continuous,
      click_to_turn: form.click_to_turn,
      reverse_click: form.reverse_click,
      dark_background: form.dark_background,
      prefetch_pages: form.prefetch_pages,
    })
    readerForm.value = { ...updated }
    readerLoaded.value = { ...updated }
    readerNotice.value = '阅读偏好已保存，进入阅读器立即生效（无需重启）'
  } catch (err) {
    readerError.value = errorMessage(err)
  } finally {
    readerSaving.value = false
  }
}

onMounted(() => {
  void load()
  void loadOption()
  void loadReader()
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

    <v-card class="mb-4">
      <v-card-title class="text-subtitle-1">阅读偏好</v-card-title>
      <v-divider />
      <v-card-text>
        <v-alert
          v-if="readerError"
          type="error"
          variant="tonal"
          density="comfortable"
          class="mb-3"
        >
          {{ readerError }}
          <template #append>
            <v-btn size="small" variant="text" @click="loadReader">重试</v-btn>
          </template>
        </v-alert>
        <v-alert
          v-if="readerNotice"
          type="success"
          variant="tonal"
          density="comfortable"
          closable
          class="mb-3"
          @click:close="readerNotice = ''"
        >
          {{ readerNotice }}
        </v-alert>
        <v-progress-linear v-if="readerLoading" indeterminate class="mb-3" />
        <p class="text-body-2 text-medium-emphasis mb-4">
          阅读偏好按管理员账户保存，与阅读器工具栏共用同一份设置，保存后立即生效且无需重启。
        </p>

        <div class="text-subtitle-2 mb-2">翻页方向</div>
        <v-btn-toggle
          v-model="readerForm.reading_mode"
          mandatory
          divided
          color="primary"
          variant="outlined"
          class="mb-2"
        >
          <v-btn
            v-for="option in READING_MODE_OPTIONS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.title }}
          </v-btn>
        </v-btn-toggle>
        <p class="text-caption text-medium-emphasis mb-4">
          {{ selectedReadingMode.description }}
        </p>

        <v-switch
          v-model="readerForm.continuous"
          label="连续翻页"
          color="primary"
          density="compact"
          hide-details
          class="mb-2"
        />
        <p class="text-caption text-medium-emphasis mb-4">
          关闭时一次一页；开启后普通/日漫模式水平连排，滚动模式垂直连排。
        </p>
        <v-switch
          v-model="readerForm.click_to_turn"
          label="点击翻页"
          color="primary"
          density="compact"
          hide-details
          class="mb-2"
        />
        <p class="text-caption text-medium-emphasis mb-4">
          开启后点击屏幕左右两大区翻页，中间区域不响应。
        </p>
        <v-switch
          v-model="readerForm.reverse_click"
          label="反转点击翻页"
          color="primary"
          density="compact"
          hide-details
          :disabled="!readerForm.click_to_turn"
          class="mb-2"
        />
        <p class="text-caption text-medium-emphasis mb-4">
          仅在开启点击翻页后可用；反转只影响点击方向，不改变滑动与键盘方向。
        </p>
        <v-switch
          v-model="readerForm.dark_background"
          label="深色背景"
          color="primary"
          density="compact"
          hide-details
        />
        <v-select
          v-model="readerForm.prefetch_pages"
          :items="PREFETCH_OPTIONS"
          label="预加载页数"
          color="primary"
          density="compact"
          variant="outlined"
          hide-details
          class="mt-2"
        />
        <p class="text-caption text-medium-emphasis mt-1 mb-0">
          连续模式当前页前后保留的页数，越大越流畅但更耗内存；手机建议 1-2
        </p>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn
          color="primary"
          :disabled="readerLoading || !readerLoaded || !readerDirty"
          :loading="readerSaving"
          @click="saveReader"
        >
          保存阅读偏好
        </v-btn>
      </v-card-actions>
    </v-card>

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
        <p class="text-caption text-medium-emphasis mb-2">
          如果在下载漫画时感觉到阅读器打开或封面预览卡顿，可以尝试调低 jmcomic 的并发下载量，具体数值请按设备性能与体感调整。
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
