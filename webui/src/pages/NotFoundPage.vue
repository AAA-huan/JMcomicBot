<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <v-card class="pa-8 text-center" variant="tonal">
    <v-icon size="56" color="warning" class="mb-4">mdi-map-marker-question-outline</v-icon>
    <h2 class="text-h6 mb-2">页面不存在</h2>
    <p class="text-body-2 text-medium-emphasis mb-4">请求的地址没有对应的页面。</p>
    <v-btn color="primary" prepend-icon="mdi-home" @click="router.replace('/')">
      返回仪表盘
    </v-btn>
  </v-card>
</template>
