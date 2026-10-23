<script setup lang="ts">
import { reactive, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { useEventSubscription } from '@/api/eventStream'
import {
  applyDataImport,
  exportData,
  repairLibrary,
  scanLibrary,
  validateDataImport,
  verifyLibrary,
} from '@/api/maintenance'
import type { ImportPreview, RepairResult } from '@/api/maintenance'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import IdScrollWindow from '@/components/IdScrollWindow.vue'
import type { OperationTask, ScanResultView, VerifyResult } from '@/types/api'
import { formatDateTime, parseMangaIds } from '@/utils/format'

const TABLE_LABELS: Record<string, string> = {
  manga: '漫画',
  manga_file: '漫画文件',
  manga_favorite: '收藏',
  reading_progress: '阅读进度',
  reading_setting: '阅读设置',
  manga_blacklist: '黑名单',
  operation_task: '操作任务',
  audit_event: '审计事件',
}

const actionError = ref('')
const actionNotice = ref('')

const scanOptions = reactive({ dry_run: false, enrich: false, read_pages: false, check_chapters: false })
const repairPreview = ref(false)
const repairResult = ref<RepairResult | null>(null)
const verifyScope = ref('selected')
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
  if (verifyScope.value === 'selected' && (!ids.length || ids.length > 100)) {
    actionError.value = '请输入 1 到 100 个漫画 ID'
    return
  }
  verifyLoading.value = true
  verifyProgress.value = null
  verifyResult.value = null
  try {
    verifyResult.value = await verifyLibrary(verifyScope.value === 'all' ? null : ids)
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    verifyLoading.value = false
  }
}

const repairDialog = ref(false)
const repairLoading = ref(false)

async function runScan(): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  scanLoading.value = true
  try {
    scanResult.value = await scanLibrary({ ...scanOptions, check_chapters: scanOptions.enrich && scanOptions.check_chapters })
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
    const result = await repairLibrary(repairPreview.value)
    repairResult.value = result
    repairDialog.value = false
  } catch (err) {
    actionError.value = errorMessage(err)
    repairDialog.value = false
  } finally {
    repairLoading.value = false
  }
}

const exportLoading = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)
const importFile = ref<File | null>(null)
const importPreview = ref<ImportPreview | null>(null)
const importValidating = ref(false)
const importDialog = ref(false)
const importLoading = ref(false)
const importRestarting = ref(false)

async function runExport(): Promise<void> {
  if (exportLoading.value || importRestarting.value) return
  actionError.value = ''
  actionNotice.value = ''
  exportLoading.value = true
  try {
    const { blob, filename } = await exportData()
    const downloadName = filename ?? 'data-export.zip'
    const objectUrl = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = downloadName
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
    actionNotice.value = `数据已导出：${downloadName}`
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    exportLoading.value = false
  }
}

function pickImportFile(): void {
  if (importValidating.value || importLoading.value || importRestarting.value) return
  importFileInput.value?.click()
}

async function handleImportFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  // 清空原生输入，允许用户重新选择同一个文件
  input.value = ''
  importPreview.value = null
  importFile.value = null
  actionError.value = ''
  actionNotice.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    actionError.value = '请选择导出生成的 .zip 数据包'
    return
  }
  importFile.value = file
  importValidating.value = true
  try {
    importPreview.value = await validateDataImport(file)
  } catch (err) {
    importFile.value = null
    actionError.value = errorMessage(err)
  } finally {
    importValidating.value = false
  }
}

async function confirmImport(): Promise<void> {
  if (!importFile.value || importLoading.value || importRestarting.value) return
  actionError.value = ''
  actionNotice.value = ''
  importLoading.value = true
  try {
    // 使用与校验时相同的 File 对象再次上传，后端会重新校验后替换整库
    await applyDataImport(importFile.value)
    importDialog.value = false
    importPreview.value = null
    importRestarting.value = true
    actionNotice.value = '数据库导入完成，服务正在重启，请稍后刷新页面。'
  } catch (err) {
    actionError.value = errorMessage(err)
    importDialog.value = false
  } finally {
    importLoading.value = false
  }
}
</script>

<template>
  <div>
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
          <v-checkbox v-model="scanOptions.dry_run" label="仅预览，不写入数据库" hide-details :disabled="scanLoading" />
          <v-checkbox v-model="scanOptions.enrich" label="联网补全漫画详情与站点章节/页数" hide-details :disabled="scanLoading" />
          <v-checkbox v-model="scanOptions.read_pages" label="读取本地 PDF 实际页数" hide-details :disabled="scanLoading" />
          <v-checkbox v-model="scanOptions.check_chapters" label="逐章查询在线图片数量（增加网络请求）" hide-details :disabled="scanLoading || !scanOptions.enrich" />
          <p v-if="scanOptions.enrich" class="text-caption text-medium-emphasis mb-3">联网补全会访问漫画站点，预览模式下也会读取网络元数据。</p>
          <div>
            <v-btn
              color="primary"
              prepend-icon="mdi-radar"
              :loading="scanLoading"
              @click="runScan"
            >
              {{ scanOptions.dry_run ? '预览扫描' : '开始扫描' }}
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
              <div class="text-body-2">无需更新：{{ scanResult.unchanged_count }}，跳过：{{ scanResult.skipped_count }}，重复文件漫画：{{ scanResult.duplicate_count }}</div>
              <div class="text-body-2">在线详情成功/失败：{{ scanResult.enrich_succeeded }}/{{ scanResult.enrich_failed }}，PDF 读取失败：{{ scanResult.page_read_failed }}，章节查询失败：{{ scanResult.chapter_errors }}</div>
              <details v-for="item in scanResult.details" :key="item.manga_id" class="mt-2">
                <summary>漫画 {{ item.manga_id }} · {{ item.file ?? '未选择文件' }} · {{ item.changes.length }} 项变化</summary>
                <p v-if="item.error">处理失败：{{ item.error }}</p>
                <p v-for="warning in item.warnings" :key="warning">{{ warning }}</p>
                <p v-for="change in item.changes" :key="change.field">{{ change.label }}：{{ JSON.stringify(change.old) }} → {{ JSON.stringify(change.new) }}（{{ change.source }}）</p>
              </details>
              <div v-if="scanResult.dry_run" class="text-body-2">预览完成，待标记缺失：{{ scanResult.pending_cleanup_count }}（未写入数据库）</div>
              <div v-else class="text-body-2">标记缺失：{{ scanResult.marked_missing_count }}</div>
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
            将文件已丢失的漫画标记为缺失，并清理无关联的孤儿标签。
          </p>
          <v-checkbox v-model="repairPreview" label="仅预览修复差异，不写入数据库" hide-details :disabled="repairLoading" />
          <div>
            <v-btn
              variant="tonal"
              color="warning"
              prepend-icon="mdi-broom"
              :loading="repairLoading"
              @click="repairPreview ? confirmRepair() : repairDialog = true"
            >
              {{ repairPreview ? '预览修复差异' : '开始修复' }}
            </v-btn>
          </div>
          <v-alert v-if="repairResult?.dry_run" type="info" variant="tonal" class="mt-3">
            预览完成，未写入数据库。待标记缺失漫画：{{ repairResult.orphan_manga_ids.length }}，孤儿标签：{{ repairResult.orphan_tag_names.length }}。
          </v-alert>
          <template v-if="repairResult?.dry_run">
            <IdScrollWindow title="待标记缺失" :items="repairResult.orphan_manga_ids" />
            <IdScrollWindow title="待清理标签" :items="repairResult.orphan_tag_names" />
          </template>
          <v-expand-transition>
            <div v-if="repairResult && !repairResult.dry_run" class="mt-3">
              <v-alert type="success" variant="tonal">
                已清理 {{ repairResult.cleaned_count }} 条孤儿记录
              </v-alert>
              <IdScrollWindow title="已标记缺失" :items="repairResult.processed_manga_ids" />
              <IdScrollWindow title="已清理标签" :items="repairResult.removed_tag_names" />
            </div>
          </v-expand-transition>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="mt-4 pa-4">
      <div class="text-subtitle-2 mb-2">校验 PDF 文件</div>
      <p class="text-body-2 mb-3">检查登记文件的路径、存在性、大小、修改时间和 SHA-256。指定漫画单次最多 100 个，也可选择校验全部漫画。进度和结果会保存到任务列表。</p>
      <v-radio-group v-model="verifyScope" inline label="校验范围" :disabled="verifyLoading">
        <v-radio label="指定漫画" value="selected" />
        <v-radio label="全部漫画" value="all" />
      </v-radio-group>
      <v-textarea v-if="verifyScope === 'selected'" v-model="verifyInput" label="待校验漫画 ID" rows="2" placeholder="例如：900001, 900002" :disabled="verifyLoading" />
      <v-btn color="primary" :loading="verifyLoading" @click="runVerify">开始校验</v-btn>
      <v-progress-linear v-if="verifyLoading" class="mt-3" :model-value="verifyProgress ?? 0" :indeterminate="verifyProgress === null" />
      <p v-if="verifyLoading" class="mt-2">正在校验{{ verifyProgress === null ? '' : `：${verifyProgress}%` }}，离开页面后可在任务列表查看结果。</p>
      <v-alert v-if="verifyResult" :type="verifyResult.error_count || verifyResult.invalid_path_count || verifyResult.missing_count || verifyResult.corrupted_count ? 'warning' : 'success'" variant="tonal" class="mt-3">
        校验完成：{{ verifyResult.file_count }} 个文件，就绪 {{ verifyResult.ready_count }}，缺失 {{ verifyResult.missing_count }}，摘要不符 {{ verifyResult.corrupted_count }}，非法路径 {{ verifyResult.invalid_path_count }}，读取错误 {{ verifyResult.error_count }}。
        <v-btn class="mt-2" variant="text" to="/tasks?task_type=verify">查看校验任务</v-btn>
      </v-alert>
    </v-card>

    <v-card class="mt-4 pa-4">
      <div class="d-flex align-center mb-2">
        <v-icon class="mr-2">mdi-database-sync-outline</v-icon>
        <span class="text-subtitle-2">数据导出与导入</span>
      </div>
      <p class="text-body-2 text-medium-emphasis">
        导出当前数据库为 zip（含一致性记录），或上传导出包替换整库。PDF 文件需手动拷贝；
        <code>.env</code> 启动配置不随数据库迁移。
      </p>
      <div class="d-flex flex-wrap ga-2">
        <v-btn
          color="primary"
          variant="tonal"
          prepend-icon="mdi-download"
          :loading="exportLoading"
          :disabled="importValidating || importLoading || importRestarting"
          @click="runExport"
        >
          导出数据
        </v-btn>
        <v-btn
          color="warning"
          variant="tonal"
          prepend-icon="mdi-upload"
          :disabled="importValidating || importLoading || importRestarting"
          @click="pickImportFile"
        >
          导入数据
        </v-btn>
        <input
          ref="importFileInput"
          type="file"
          accept=".zip,application/zip"
          class="d-none"
          aria-label="选择导入数据包"
          @change="handleImportFile"
        >
      </div>
      <p v-if="importValidating" class="mt-3 text-body-2">正在校验数据包…</p>
      <v-expand-transition>
        <v-sheet
          v-if="importPreview"
          class="mt-3 pa-3 rounded"
          color="surface-variant"
        >
          <div class="text-body-2">
            导出 schema：{{ importPreview.schema_revision }}，当前 schema：{{ importPreview.current_schema_revision }}
          </div>
          <div class="text-body-2">
            导出时间：{{ formatDateTime(importPreview.exported_at) }} · 数据库文件：{{ importPreview.db_filename }}
          </div>
          <div class="text-caption text-medium-emphasis text-break mb-2">
            SHA-256：{{ importPreview.db_sha256 }}
          </div>
          <v-table density="compact" class="bg-transparent">
            <tbody>
              <tr v-for="(count, table) in importPreview.table_counts" :key="table">
                <td>{{ TABLE_LABELS[table] ?? table }}</td>
                <td class="text-right">{{ count }}</td>
              </tr>
            </tbody>
          </v-table>
          <v-alert
            v-for="(warning, index) in importPreview.path_warnings"
            :key="index"
            type="warning"
            variant="tonal"
            density="comfortable"
            class="mt-2"
          >
            {{ warning }}
          </v-alert>
          <v-btn
            color="error"
            class="mt-3"
            prepend-icon="mdi-database-import-outline"
            :disabled="importLoading || importRestarting"
            @click="importDialog = true"
          >
            确认导入
          </v-btn>
        </v-sheet>
      </v-expand-transition>
      <v-alert
        v-if="importRestarting"
        type="info"
        variant="tonal"
        density="comfortable"
        class="mt-3"
      >
        导入已提交，机器人正在重启。重启完成后请刷新页面，必要时重新登录。
      </v-alert>
    </v-card>

    <ConfirmDialog
      v-model="repairDialog"
      title="确认修复资料库？"
      text="将文件已丢失的漫画标记为缺失，并删除无关联的孤儿标签。"
      confirm-text="确认修复"
      confirm-color="warning"
      :loading="repairLoading"
      @confirm="confirmRepair"
    />

    <ConfirmDialog
      v-model="importDialog"
      title="确认导入全部数据？"
      confirm-text="确认导入并重启"
      confirm-color="error"
      :loading="importLoading"
      @confirm="confirmImport"
    >
      <p>此操作将用上传的数据包替换当前全部数据库，并立即重启机器人。</p>
      <p class="mt-2">
        操作不可在线撤销。如需回滚，请手动恢复数据库目录下的
        <code>main.db.pre-import-*.bak</code>。
      </p>
      <p class="mt-2">
        PDF 文件不会随数据包迁移，请确保已拷贝到当前下载目录；<code>.env</code>
        中的启动配置不会迁移。
      </p>
    </ConfirmDialog>
  </div>
</template>
