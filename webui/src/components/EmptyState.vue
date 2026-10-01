<script setup lang="ts">
withDefaults(
  defineProps<{
    icon?: string
    title: string
    description?: string
  }>(),
  {
    icon: 'mdi-inbox-outline',
    description: '',
  },
)
</script>

<template>
  <div class="text-center py-10">
    <v-icon size="56" color="medium-emphasis" class="mb-3">{{ icon }}</v-icon>
    <div class="text-subtitle-1">{{ title }}</div>
    <div v-if="description" class="text-body-2 text-medium-emphasis mt-1">
      {{ description }}
    </div>
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
  </div>
</template>
