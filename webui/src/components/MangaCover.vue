<script setup lang="ts">
/** 漫画封面预览：直接加载服务端抽出的首页缩略图，不再经过 PDF.js。 */

import { computed, ref } from 'vue'

import { fileCoverUrl } from '@/api/files'

const props = defineProps<{ fileId: number }>()

const src = computed(() => fileCoverUrl(props.fileId))
const error = ref('')

/** 非图片型或损坏 PDF 的封面接口返回 404，改为文字占位。 */
function onImageError(): void {
  error.value = '封面不可用'
}
</script>

<template>
  <div class="mb-4">
    <div class="text-subtitle-2 mb-2">封面预览 · 第一页</div>
    <v-img
      v-if="!error"
      :src="src"
      max-width="320"
      cover
      loading="lazy"
      class="cover-preview"
      @error="onImageError"
    />
    <v-alert v-if="error" type="warning" variant="tonal" density="compact">
      {{ error }}
    </v-alert>
  </div>
</template>

<style scoped>
.cover-preview {
  width: 320px;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.18);
}
</style>
