<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { deleteManga, getManga, patchManga } from '@/api/mangas'
import { requestDownloads } from '@/api/tasks'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { Manga } from '@/types/api'
import { formatBytes, formatDateTime, parseTags } from '@/utils/format'
import {
  colorOf,
  labelOf,
  FILE_STATUS_COLORS,
  FILE_STATUS_LABELS,
  MANGA_STATUS_COLORS,
  MANGA_STATUS_LABELS,
} from '@/utils/labels'

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()

const mangaId = String(route.params.mangaId ?? '')

const manga = ref<Manga | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const actionError = ref('')
const actionLoading = ref(false)

const editDialog = ref(false)
const editForm = reactive({ title: '', author: '', tags: '' })
const editError = ref('')
const editLoading = ref(false)

const deleteDialog = ref(false)
const deleteLoading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    manga.value = await getManga(mangaId)
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function openEdit(): void {
  if (!manga.value) return
  editForm.title = manga.value.title
  editForm.author = manga.value.author
  editForm.tags = manga.value.tags.join('，')
  editError.value = ''
  editDialog.value = true
}

async function submitEdit(): Promise<void> {
  const title = editForm.title.trim()
  if (!title) {
    editError.value = '标题不能为空'
    return
  }
  editLoading.value = true
  editError.value = ''
  try {
    manga.value = await patchManga(mangaId, {
      title,
      author: editForm.author.trim(),
      tags: parseTags(editForm.tags),
    })
    editDialog.value = false
    notice.value = '元数据已更新'
  } catch (err) {
    editError.value = errorMessage(err)
  } finally {
    editLoading.value = false
  }
}

function fileDownloadUrl(fileId: number): string {
  return `/api/v1/files/${fileId}/content`
}

async function handleDownload(): Promise<void> {
  actionError.value = ''
  notice.value = ''
  actionLoading.value = true
  try {
    const result = await requestDownloads([mangaId])
    if (result.duplicate_count > 0) {
      notice.value = '该漫画已有进行中的下载任务'
    } else {
      notice.value = '已加入下载队列'
    }
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    actionLoading.value = false
  }
}

async function confirmDelete(): Promise<void> {
  deleteLoading.value = true
  actionError.value = ''
  try {
    await deleteManga(mangaId)
    await router.replace({ name: 'library', query: route.query })
  } catch (err) {
    actionError.value = errorMessage(err)
    deleteDialog.value = false
  } finally {
    deleteLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4 ga-2">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        aria-label="返回漫画库"
        @click="router.push({ name: 'library', query: route.query })"
      />
      <h1 class="text-h6 text-truncate">{{ manga?.title ?? '漫画详情' }}</h1>
    </div>

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
      v-if="notice"
      type="success"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="notice = ''"
    >
      {{ notice }}
    </v-alert>

    <v-progress-linear v-if="loading" indeterminate class="mb-4" />

    <template v-if="manga">
      <v-card class="mb-4">
        <v-card-text>
          <div class="d-flex flex-wrap align-center ga-2 mb-3">
            <v-chip
              variant="tonal"
              size="small"
              :color="colorOf(MANGA_STATUS_COLORS, manga.status)"
            >
              {{ labelOf(MANGA_STATUS_LABELS, manga.status) }}
            </v-chip>
            <v-chip size="small" variant="outlined">ID: {{ manga.id }}</v-chip>
          </div>

          <v-row dense>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">标题</div>
              <div class="text-body-1">{{ manga.title }}</div>
            </v-col>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">作者</div>
              <div class="text-body-1">{{ manga.author || '—' }}</div>
            </v-col>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">章节 / 页数</div>
              <div class="text-body-1">{{ manga.chapter_count }} 章 / {{ manga.page_count }} 页</div>
            </v-col>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">下载时间</div>
              <div class="text-body-1">{{ formatDateTime(manga.downloaded_at) }}</div>
            </v-col>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">更新时间</div>
              <div class="text-body-1">{{ formatDateTime(manga.updated_at) }}</div>
            </v-col>
            <v-col cols="12" sm="6">
              <div class="text-caption text-medium-emphasis">标签</div>
              <div>
                <v-chip
                  v-for="tag in manga.tags"
                  :key="tag"
                  size="x-small"
                  variant="tonal"
                  class="mr-1"
                >
                  {{ tag }}
                </v-chip>
                <span v-if="manga.tags.length === 0">—</span>
              </div>
            </v-col>
            <v-col v-if="manga.description" cols="12">
              <div class="text-caption text-medium-emphasis">简介</div>
              <div class="text-body-2 text-pre-wrap">{{ manga.description }}</div>
            </v-col>
          </v-row>
        </v-card-text>
        <v-divider />
        <v-card-actions class="flex-wrap">
          <v-spacer />
          <v-btn
            variant="tonal"
            prepend-icon="mdi-pencil"
            @click="openEdit"
          >
            编辑元数据
          </v-btn>
          <v-btn
            variant="tonal"
            prepend-icon="mdi-download"
            :loading="actionLoading"
            @click="handleDownload"
          >
            请求下载
          </v-btn>
          <v-btn
            variant="tonal"
            color="error"
            prepend-icon="mdi-delete"
            @click="deleteDialog = true"
          >
            删除漫画
          </v-btn>
        </v-card-actions>
      </v-card>

      <v-card>
        <v-card-title class="text-subtitle-1">章节文件</v-card-title>
        <v-progress-linear v-if="loading" indeterminate />

        <EmptyState
          v-if="manga.files.length === 0"
          icon="mdi-file-pdf-box"
          title="没有章节文件"
          description="该漫画的记录存在，但尚未关联 PDF 文件。"
        />

        <template v-else-if="!mobile">
          <v-table>
            <thead>
              <tr>
                <th>文件名</th>
                <th>页数</th>
                <th>大小</th>
                <th>状态</th>
                <th class="text-no-wrap">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="file in manga.files" :key="file.id">
                <td>{{ file.display_name }}</td>
                <td>{{ file.page_count }}</td>
                <td>{{ formatBytes(file.file_size_bytes) }}</td>
                <td>
                  <v-chip
                    size="small"
                    variant="tonal"
                    :color="colorOf(FILE_STATUS_COLORS, file.status)"
                  >
                    {{ labelOf(FILE_STATUS_LABELS, file.status) }}
                  </v-chip>
                </td>
                <td class="text-no-wrap">
                  <v-btn
                    v-if="file.status === 'ready'"
                    icon="mdi-file-download-outline"
                    size="small"
                    variant="text"
                    :href="fileDownloadUrl(file.id)"
                    aria-label="下载 PDF"
                  />
                  <v-btn
                    v-else
                    icon="mdi-file-download-outline"
                    size="small"
                    variant="text"
                    disabled
                    aria-label="文件不可下载"
                  />
                </td>
              </tr>
            </tbody>
          </v-table>
        </template>

        <v-list v-else lines="two">
          <v-list-item v-for="file in manga.files" :key="file.id">
            <v-list-item-title class="text-wrap">{{ file.display_name }}</v-list-item-title>
            <v-list-item-subtitle>
              {{ file.page_count }} 页 · {{ formatBytes(file.file_size_bytes) }}
            </v-list-item-subtitle>
            <template #append>
              <div class="d-flex align-center ga-1">
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="colorOf(FILE_STATUS_COLORS, file.status)"
                >
                  {{ labelOf(FILE_STATUS_LABELS, file.status) }}
                </v-chip>
                <v-btn
                  v-if="file.status === 'ready'"
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  :href="fileDownloadUrl(file.id)"
                  aria-label="下载 PDF"
                />
                <v-btn
                  v-else
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  disabled
                  aria-label="文件不可下载"
                />
              </div>
            </template>
          </v-list-item>
        </v-list>

        <v-divider />
        <v-card-text class="text-caption text-medium-emphasis">
          可下载 PDF 到本地；在线阅读与阅读进度将在阶段 3 提供。
        </v-card-text>
      </v-card>
    </template>

    <v-dialog v-model="editDialog" max-width="520">
      <v-card>
        <v-card-title>编辑元数据</v-card-title>
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
          <v-text-field v-model="editForm.title" label="标题" maxlength="255" counter />
          <v-text-field v-model="editForm.author" label="作者" maxlength="255" />
          <v-text-field
            v-model="editForm.tags"
            label="标签（逗号分隔）"
            hint="例如：恋爱, 校园"
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="editLoading" @click="submitEdit">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteDialog"
      :title="`删除《${manga?.title ?? ''}》？`"
      text="将删除该漫画的数据库记录与全部章节文件，此操作不可撤销。"
      confirm-text="确认删除"
      :loading="deleteLoading"
      @confirm="confirmDelete"
    />
  </div>
</template>
