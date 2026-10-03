<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { errorMessage } from '@/api/client'
import { getDocument, listDocuments } from '@/api/documents'
import type { DocumentEntry } from '@/api/documents'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const documents = ref<DocumentEntry[]>([])
const search = ref<string | null>('')
const content = ref('')
const error = ref('')
const loading = ref(false)
const selectedPath = computed(() => typeof route.query.doc === 'string' ? route.query.doc : '')
const selectedTitle = computed(() => documents.value.find((doc) => doc.path === selectedPath.value)?.title ?? '项目文档')
const visibleDocuments = computed(() => documents.value.filter((doc) =>
  `${doc.title} ${doc.path}`.toLocaleLowerCase().includes((search.value ?? '').trim().toLocaleLowerCase()),
))
// Markdown 可能包含 HTML，展示前清理脚本、事件属性及危险链接。
const renderedContent = computed(() => DOMPurify.sanitize(marked.parse(content.value, { async: false })))
let requestId = 0

async function loadContent(): Promise<void> {
  const currentRequest = ++requestId
  content.value = ''
  error.value = ''
  if (!selectedPath.value) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const result = await getDocument(selectedPath.value)
    if (currentRequest === requestId) content.value = result.content
  } catch (err) {
    if (currentRequest === requestId) error.value = errorMessage(err)
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

async function loadList(): Promise<void> {
  error.value = ''
  try {
    documents.value = await listDocuments()
    if (!selectedPath.value && documents.value.length) {
      await router.replace({ query: { ...route.query, doc: documents.value[0].path } })
    } else if (selectedPath.value) {
      await loadContent()
    }
  } catch (err) {
    error.value = errorMessage(err)
  }
}

/** 文档内的相对 Markdown 链接在本页打开，保留浏览器前进后退行为。 */
function openDocumentLink(event: MouseEvent): void {
  const anchor = (event.target as HTMLElement).closest('a')
  const href = anchor?.getAttribute('href')
  if (!href || href.startsWith('#') || /^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith('//')) return
  const url = new URL(href, `https://documents.invalid/${selectedPath.value}`)
  if (url.pathname.endsWith('.md')) {
    event.preventDefault()
    void router.push({ query: { ...route.query, doc: decodeURIComponent(url.pathname.slice(1)) } })
  }
}

watch(selectedPath, loadContent)
onMounted(loadList)
</script>

<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      {{ error }}
      <template #append><v-btn variant="text" @click="loadList">重试</v-btn></template>
    </v-alert>
    <v-row>
      <v-col cols="12" md="3">
        <v-card>
          <v-card-title class="text-subtitle-1">文档目录</v-card-title>
          <v-card-text class="pb-0"><v-text-field v-model="search" label="搜索文档" prepend-inner-icon="mdi-magnify" hide-details clearable /></v-card-text>
          <v-list nav>
            <v-list-item
              v-for="doc in visibleDocuments" :key="doc.path"
              :title="doc.title" :subtitle="doc.path" :active="doc.path === selectedPath"
              :to="{ name: 'documents', query: { doc: doc.path } }" prepend-icon="mdi-file-document-outline"
            />
          </v-list>
        </v-card>
      </v-col>
      <v-col cols="12" md="9">
        <v-card>
          <v-card-title class="text-wrap">{{ selectedTitle }}</v-card-title>
          <v-progress-linear v-if="loading" indeterminate />
          <EmptyState v-if="!loading && !error && documents.length === 0" title="暂无项目文档" description="项目 docs 目录内尚无 Markdown 文档。" icon="mdi-file-document-outline" />
          <v-card-text @click="openDocumentLink">
            <!-- Markdown 已使用 DOMPurify 清理后再渲染。 -->
            <!-- eslint-disable-next-line vue/no-v-html -->
            <article class="document-content" v-html="renderedContent" />
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.document-content { overflow-wrap: anywhere; line-height: 1.8; }
.document-content :deep(h1), .document-content :deep(h2), .document-content :deep(h3) { margin: 1.2em 0 0.5em; line-height: 1.4; }
.document-content :deep(p), .document-content :deep(ul), .document-content :deep(ol), .document-content :deep(pre), .document-content :deep(table) { margin-bottom: 1em; }
.document-content :deep(ul), .document-content :deep(ol) { padding-left: 1.5em; }
.document-content :deep(pre) { overflow-x: auto; padding: 1em; background: rgba(var(--v-theme-on-surface), 0.06); border-radius: 6px; }
.document-content :deep(code) { font-family: monospace; }
.document-content :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; }
.document-content :deep(th), .document-content :deep(td) { padding: 0.5em 0.8em; border: 1px solid rgba(var(--v-theme-on-surface), 0.2); }
.document-content :deep(blockquote) { border-left: 3px solid rgb(var(--v-theme-primary)); padding-left: 1em; }
.document-content :deep(a) { color: rgb(var(--v-theme-primary)); }
.document-content :deep(img) { max-width: 100%; }
</style>
