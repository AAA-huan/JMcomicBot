<script setup lang="ts">
import { useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
</script>

<template>
  <v-app>
    <v-main>
      <v-container
        class="d-flex flex-column justify-center py-6"
        style="min-height: 100vh; max-width: 460px"
      >
        <div class="text-center mb-6">
          <v-icon color="primary" size="48">mdi-robot-happy-outline</v-icon>
          <h1 class="text-h5 mt-2">JMcomicBot 控制台</h1>
        </div>
        <slot />
        <div class="text-center mt-6">
          <v-btn
            variant="text"
            size="small"
            :prepend-icon="theme.mode === 'dark' ? 'mdi-weather-night' : 'mdi-white-balance-sunny'"
            @click="theme.cycleMode()"
          >
            主题：{{ theme.mode === 'dark' ? '深色' : theme.mode === 'light' ? '浅色' : '跟随系统' }}
          </v-btn>
        </div>
      </v-container>
    </v-main>
  </v-app>
</template>
