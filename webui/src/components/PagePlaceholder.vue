<script setup lang="ts">
defineProps<{
  title: string
  description: string
  icon: string
}>()
</script>

<template>
  <v-card class="pa-8 text-center" variant="tonal">
    <v-icon size="56" color="primary" class="mb-4">{{ icon }}</v-icon>
    <h2 class="text-h6 mb-2">{{ title }}</h2>
    <p class="text-body-2 text-medium-emphasis mb-0">{{ description }}</p>
  </v-card>
</template>
