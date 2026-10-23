<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

const props = withDefaults(defineProps<{
  page: number
  pages: number
  pageSize?: number | null
  pageSizeOptions?: number[]
  loading?: boolean
}>(), {
  pageSize: null,
  pageSizeOptions: () => [],
  loading: false,
})

const emit = defineEmits<{
  'update:page': [page: number]
  'update:pageSize': [pageSize: number]
}>()

const { mobile } = useDisplay()
const scrollContainer = ref<HTMLElement | null>(null)

/** 首尾页固定展示，中间页全部放入可横向滚动区域，避免省略号折叠。 */
const middlePages = computed(() => {
  const result: number[] = []
  for (let value = 2; value < props.pages; value += 1) result.push(value)
  return result
})

/** 分页栏始终展示分页大小选择器；没有分页时仅展示选择器。 */
const visible = computed(() => props.pages > 1 || props.pageSizeOptions.length > 0)

async function centerCurrentPage(): Promise<void> {
  await nextTick()
  if (props.page <= 1 || props.page >= props.pages) return
  const target = scrollContainer.value?.querySelector<HTMLElement>(
    `[data-page="${props.page}"]`,
  )
  // 浏览器支持时把当前页滚到中间，jsdom 等环境没有该方法时直接跳过
  target?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'center' })
}

watch(
  () => [props.page, props.pages],
  () => { void centerCurrentPage() },
  { immediate: true },
)

/** 跳转前做边界约束，越界或重复点击不产生事件。 */
function goTo(target: number): void {
  const bounded = Math.min(Math.max(target, 1), Math.max(props.pages, 1))
  if (bounded !== props.page) emit('update:page', bounded)
}

function changePageSize(value: number): void {
  emit('update:pageSize', value)
}
</script>

<template>
  <div v-if="visible">
    <div v-if="mobile" class="pagination-bar-spacer" />
    <div
      class="pagination-bar"
      :class="{ 'pagination-bar--mobile': mobile }"
      role="navigation"
      aria-label="分页"
    >
      <div v-if="pages > 1" class="pagination-pages">
        <v-btn
          class="pagination-arrow"
          icon="mdi-chevron-left"
          size="small"
          variant="text"
          :disabled="loading || page <= 1"
          aria-label="上一页"
          @click="goTo(page - 1)"
        />
        <v-btn
          class="pagination-page pagination-page--edge"
          :class="{ 'pagination-page--active': page === 1 }"
          :color="page === 1 ? 'primary' : undefined"
          :variant="page === 1 ? 'flat' : 'text'"
          size="small"
          :disabled="loading"
          data-page="1"
          @click="goTo(1)"
        >
          1
        </v-btn>
        <div ref="scrollContainer" class="pagination-scroll">
          <v-btn
            v-for="value in middlePages"
            :key="value"
            class="pagination-page"
            :class="{ 'pagination-page--active': page === value }"
            :color="page === value ? 'primary' : undefined"
            :variant="page === value ? 'flat' : 'text'"
            size="small"
            :disabled="loading"
            :data-page="value"
            @click="goTo(value)"
          >
            {{ value }}
          </v-btn>
        </div>
        <v-btn
          class="pagination-page pagination-page--edge"
          :class="{ 'pagination-page--active': page === pages }"
          :color="page === pages ? 'primary' : undefined"
          :variant="page === pages ? 'flat' : 'text'"
          size="small"
          :disabled="loading"
          :data-page="pages"
          @click="goTo(pages)"
        >
          {{ pages }}
        </v-btn>
        <v-btn
          class="pagination-arrow"
          icon="mdi-chevron-right"
          size="small"
          variant="text"
          :disabled="loading || page >= pages"
          aria-label="下一页"
          @click="goTo(page + 1)"
        />
      </div>
      <v-select
        v-if="pageSizeOptions.length"
        class="pagination-size"
        :model-value="pageSize"
        :items="pageSizeOptions"
        label="每页"
        hide-details
        density="compact"
        :disabled="loading"
        @update:model-value="changePageSize"
      />
    </div>
  </div>
</template>

<style scoped>
.pagination-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px;
}

.pagination-pages {
  display: flex;
  align-items: center;
  gap: 2px;
  max-width: min(100%, 640px);
  min-width: 0;
}

.pagination-scroll {
  display: flex;
  flex: 1 1 auto;
  gap: 2px;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}

.pagination-scroll::-webkit-scrollbar {
  display: none;
}

.pagination-page {
  flex: 0 0 auto;
  min-width: 36px;
  padding: 0 6px;
}

.pagination-page--active {
  font-weight: 600;
}

.pagination-arrow {
  flex: 0 0 auto;
}

.pagination-size {
  flex: 0 0 auto;
  max-width: 112px;
}

.pagination-bar-spacer {
  height: 64px;
}

/* 移动端固定在底部导航上方，翻页无需滑到列表末尾 */
.pagination-bar--mobile {
  position: fixed;
  right: 0;
  bottom: 56px;
  left: 0;
  z-index: 100;
  flex-wrap: nowrap;
  padding: 6px 8px;
  background: rgb(var(--v-theme-surface));
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.12);
}

.pagination-bar--mobile .pagination-pages {
  flex: 1 1 auto;
  max-width: none;
}

.pagination-bar--mobile .pagination-page,
.pagination-bar--mobile .pagination-arrow {
  min-width: 32px;
  width: 32px;
  padding: 0;
}

.pagination-bar--mobile .pagination-size {
  width: 92px;
  max-width: 92px;
}
</style>
