<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { useEventSubscription } from '@/api/eventStream'
import {
  createBackup,
  listBackups,
  repairLibrary,
  scanLibrary,
  verifyLibrary,
} from '@/api/maintenance'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { BackupRecord, OperationTask, ScanResultView, VerifyResult } from '@/types/api'
import { formatBytes, formatDateTime, parseMangaIds } from '@/utils/format'
import {
  BACKUP_STATUS_COLORS,
  BACKUP_STATUS_LABELS,
  colorOf,
  labelOf,
} from '@/utils/labels'

const { mobile } = useDisplay()

const error = ref('')
const actionError = ref('')
const actionNotice = ref('')

const scanResult = ref<ScanResultView | null>(null)
const scanLoading = ref(false)
const verifyInput = ref('')
const verifyLoading = ref(false)
const verifyProgress = ref<number | null>(null)
const verifyResult = ref<VerifyResult | null>(null)

useEventSubscription((event) => {
  if (event.type !== 'task.updated' || !verifyLoading.value) return
  const task = event.data as OperationTask
  if (task.task_type === 'verify') verifyProgress.value = task.progress
})

async function runVerify(): Promise<void> {
  if (verifyLoading.value) return
  actionError.value = ''
  const ids = parseMangaIds(verifyInput.value)
  if (!ids.length || ids.length > 100) {
    actionError.value = '请输入 1 到 100 个漫画 ID'
    return
  }
  verifyLoading.value = true
  verifyProgress.value = null
  verifyResult.value = null
  try {
    verifyResult.value = await verifyLibrary(ids)
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    verifyLoading.value = false
  }
}

const repairDialog = ref(false)
const repairLoading = ref(false)
const repairedCount = ref<number | null>(null)

const backups = ref<BackupRecord[]>([])
const backupTotal = ref(0)
const backupPages = ref(0)
const backupPage = ref(1)
const backupsLoading = ref(false)

const createBackupDialog = ref(false)
const createBackupLoading = ref(false)

const backupPageSize = 10

function downloadUrl(backupId: number): string {
  return `/api/v1/maintenance/backups/${backupId}/download`
}

async function runScan(): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  scanLoading.value = true
  try {
    scanResult.value = await scanLibrary()
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    scanLoading.value = false
  }
}

async function confirmRepair(): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  repairLoading.value = true
  try {
    const result = await repairLibrary()
    repairedCount.value = result.cleaned_count
    repairDialog.value = false
  } catch (err) {
    actionError.value = errorMessage(err)
    repairDialog.value = false
  } finally {
    repairLoading.value = false
  }
}

async function loadBackups(): Promise<void> {
  backupsLoading.value = true
  error.value = ''
  try {
    const result = await listBackups({
      page: backupPage.value,
      page_size: backupPageSize,
    })
    backups.value = result.items
    backupTotal.value = result.total
    backupPages.value = result.pages
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    backupsLoading.value = false
  }
}

async function confirmCreateBackup(): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  createBackupLoading.value = true
  try {
    const result = await createBackup()
    actionNotice.value = `备份已创建：${result.filename}（${formatBytes(
      result.file_size_bytes,
    )}）`
    createBackupDialog.value = false
    backupPage.value = 1
    await loadBackups()
  } catch (err) {
    actionError.value = errorMessage(err)
    createBackupDialog.value = false
  } finally {
    createBackupLoading.value = false
  }
}

onMounted(() => {
  void loadBackups()
})
</script>

<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal" density="comfortable" class="mb-4">
      {{ error }}
      <template #append>
        <v-btn size="small" variant="text" @click="loadBackups">重试</v-btn>
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

    <v-row dense>
      <v-col cols="12" md="6">
        <v-card class="pa-4 h-100 d-flex flex-column">
          <div class="d-flex align-center mb-2">
            <v-icon class="mr-2">mdi-file-search-outline</v-icon>
            <span class="text-subtitle-2">扫描漫画目录</span>
          </div>
          <p class="text-body-2 text-medium-emphasis flex-grow-1">
            对比磁盘上的漫画文件与数据库记录，补录新文件并标记缺失记录。适合在手动增删文件后运行。
          </p>
          <div>
            <v-btn
              color="primary"
              prepend-icon="mdi-radar"
              :loading="scanLoading"
              @click="runScan"
            >
              开始扫描
            </v-btn>
          </div>
          <v-expand-transition>
            <v-sheet
              v-if="scanResult"
              class="mt-3 pa-3 rounded"
              color="surface-variant"
            >
              <div class="text-body-2">扫描文件：{{ scanResult.scanned_files }}</div>
              <div class="text-body-2">识别漫画：{{ scanResult.manga_count }}</div>
              <div class="text-body-2">新增：{{ scanResult.new_count }}，更新：{{ scanResult.updated_count }}</div>
              <div class="text-body-2">标记缺失：{{ scanResult.marked_missing_count }}</div>
            </v-sheet>
          </v-expand-transition>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card class="pa-4 h-100 d-flex flex-column">
          <div class="d-flex align-center mb-2">
            <v-icon class="mr-2">mdi-wrench-outline</v-icon>
            <span class="text-subtitle-2">修复资料库</span>
          </div>
          <p class="text-body-2 text-medium-emphasis flex-grow-1">
            清理数据库中的孤儿记录（数据库存在但磁盘文件已丢失）。操作只影响记录，不会删除现有文件。
          </p>
          <div>
            <v-btn
              variant="tonal"
              color="warning"
              prepend-icon="mdi-broom"
              @click="repairDialog = true"
            >
              开始修复
            </v-btn>
          </div>
          <v-expand-transition>
            <v-sheet
              v-if="repairedCount !== null"
              class="mt-3 pa-3 rounded"
              color="surface-variant"
            >
              <div class="text-body-2">已清理 {{ repairedCount }} 条孤儿记录</div>
            </v-sheet>
          </v-expand-transition>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="mt-4 pa-4">
      <div class="text-subtitle-2 mb-2">校验 PDF 文件</div>
      <p class="text-body-2 mb-3">检查登记文件的路径、存在性、大小、修改时间和 SHA-256。单次最多 100 个漫画，进度和结果会保存到任务列表。</p>
      <v-textarea v-model="verifyInput" label="待校验漫画 ID" rows="2" placeholder="例如：900001, 900002" :disabled="verifyLoading" />
      <v-btn color="primary" :loading="verifyLoading" @click="runVerify">开始校验</v-btn>
      <v-progress-linear v-if="verifyLoading" class="mt-3" :model-value="verifyProgress ?? 0" :indeterminate="verifyProgress === null" />
      <p v-if="verifyLoading" class="mt-2">正在校验{{ verifyProgress === null ? '' : `：${verifyProgress}%` }}，离开页面后可在任务列表查看结果。</p>
      <v-alert v-if="verifyResult" :type="verifyResult.error_count || verifyResult.invalid_path_count || verifyResult.missing_count || verifyResult.corrupted_count ? 'warning' : 'success'" variant="tonal" class="mt-3">
        校验完成：{{ verifyResult.file_count }} 个文件，就绪 {{ verifyResult.ready_count }}，缺失 {{ verifyResult.missing_count }}，摘要不符 {{ verifyResult.corrupted_count }}，非法路径 {{ verifyResult.invalid_path_count }}，读取错误 {{ verifyResult.error_count }}。
        <v-btn class="mt-2" variant="text" to="/tasks?task_type=verify">查看校验任务</v-btn>
      </v-alert>
    </v-card>

    <v-card class="mt-4">
      <v-card-title class="text-subtitle-1">
        数据库备份
        <span class="text-caption text-medium-emphasis ml-2">共 {{ backupTotal }} 个</span>
      </v-card-title>
      <v-card-subtitle class="text-wrap">
        使用 SQLite 一致性备份生成，记录校验和与创建时间。
      </v-card-subtitle>
      <v-card-actions class="flex-wrap">
        <v-spacer />
        <v-btn
          color="primary"
          prepend-icon="mdi-database-plus-outline"
          @click="createBackupDialog = true"
        >
          创建备份
        </v-btn>
        <v-btn icon="mdi-refresh" variant="text" aria-label="刷新" @click="loadBackups" />
      </v-card-actions>
      <v-divider />
      <v-progress-linear v-if="backupsLoading" indeterminate />

      <EmptyState
        v-if="!backupsLoading && backups.length === 0"
        icon="mdi-database-outline"
        title="还没有备份"
        description="创建备份后可在此查看文件大小与状态。"
      />

      <template v-else-if="!mobile">
        <v-table>
          <thead>
            <tr>
              <th>文件名</th>
              <th class="text-no-wrap">大小</th>
              <th>状态</th>
              <th class="text-no-wrap">结构版本</th>
              <th class="text-no-wrap">创建时间</th>
              <th class="text-no-wrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="backup in backups" :key="backup.id">
              <td class="text-wrap">{{ backup.filename }}</td>
              <td class="text-no-wrap">{{ formatBytes(backup.file_size_bytes) }}</td>
              <td>
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="colorOf(BACKUP_STATUS_COLORS, backup.status)"
                >
                  {{ labelOf(BACKUP_STATUS_LABELS, backup.status) }}
                </v-chip>
              </td>
              <td class="text-no-wrap">{{ backup.schema_version }}</td>
              <td class="text-no-wrap">{{ formatDateTime(backup.created_at) }}</td>
              <td class="text-no-wrap">
                <v-btn
                  v-if="backup.status === 'ready'"
                  icon="mdi-download"
                  size="small"
                  variant="text"
                  :href="downloadUrl(backup.id)"
                  aria-label="下载备份"
                />
              </td>
            </tr>
          </tbody>
        </v-table>
      </template>

      <v-list v-else lines="two">
        <v-list-item v-for="backup in backups" :key="backup.id">
          <v-list-item-title class="text-wrap">{{ backup.filename }}</v-list-item-title>
          <v-list-item-subtitle>
            {{ formatBytes(backup.file_size_bytes) }} · {{ formatDateTime(backup.created_at) }}
          </v-list-item-subtitle>
          <template #append>
            <div class="d-flex align-center ga-1">
              <v-chip
                size="small"
                variant="tonal"
                :color="colorOf(BACKUP_STATUS_COLORS, backup.status)"
              >
                {{ labelOf(BACKUP_STATUS_LABELS, backup.status) }}
              </v-chip>
              <v-btn
                v-if="backup.status === 'ready'"
                icon="mdi-download"
                size="small"
                variant="text"
                :href="downloadUrl(backup.id)"
                aria-label="下载备份"
              />
            </div>
          </template>
        </v-list-item>
      </v-list>

      <v-divider v-if="backupPages > 1" />
      <div v-if="backupPages > 1" class="d-flex justify-center pa-2">
        <v-pagination
          :model-value="backupPage"
          :length="backupPages"
          :total-visible="5"
          @update:model-value="
            (value: number) => {
              backupPage = value
              void loadBackups()
            }
          "
        />
      </div>
    </v-card>

    <ConfirmDialog
      v-model="repairDialog"
      title="确认修复资料库？"
      text="将清理数据库中文件已丢失的孤儿记录，不会删除磁盘上的现有文件。"
      confirm-text="确认修复"
      confirm-color="warning"
      :loading="repairLoading"
      @confirm="confirmRepair"
    />

    <ConfirmDialog
      v-model="createBackupDialog"
      title="创建数据库备份？"
      text="将使用 SQLite 一致性备份接口导出当前数据库快照，可能短暂占用少量磁盘空间。"
      confirm-text="创建备份"
      confirm-color="primary"
      :loading="createBackupLoading"
      @confirm="confirmCreateBackup"
    />
  </div>
</template>
