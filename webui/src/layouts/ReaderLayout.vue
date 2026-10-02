<script setup lang="ts">
/** 阅读器独立布局：无侧栏/底部导航，内容占满全屏。 */
</script>

<template>
  <v-app>
    <v-main class="reader-main">
      <slot />
    </v-main>
  </v-app>
</template>

<style scoped>
.reader-main {
  padding: 0;
}
</style>
