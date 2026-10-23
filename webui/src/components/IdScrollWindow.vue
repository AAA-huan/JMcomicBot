<script setup lang="ts">
defineProps<{
  title: string
  items: string[]
}>()
</script>

<template>
  <div v-if="items.length" class="mt-3">
    <div class="text-body-2 mb-1">{{ title }}（{{ items.length }}）</div>
    <v-card variant="outlined" class="id-scroll-window">
      <div class="id-scroll-window__content">
        <v-chip
          v-for="item in items"
          :key="item"
          size="small"
          variant="tonal"
          label
        >
          {{ item }}
        </v-chip>
      </div>
    </v-card>
  </div>
</template>

<style scoped>
.id-scroll-window {
  height: 240px;
  overflow-y: auto;
}

.id-scroll-window__content {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
}
</style>
