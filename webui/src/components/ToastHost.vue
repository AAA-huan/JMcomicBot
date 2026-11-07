<script setup lang="ts">
import { useToast } from '@/stores/toast'
import type { ToastType } from '@/stores/toast'

const toast = useToast()
const visible = toast.visible

const ICONS: Record<ToastType, string> = {
  success: 'mdi-check-circle',
  error: 'mdi-alert-circle',
  info: 'mdi-information-outline',
}
</script>

<template>
  <div class="toast-host">
    <TransitionGroup name="toast-slide">
      <div
        v-for="item in visible"
        :key="item.id"
        class="toast-item"
        :class="`toast-item--${item.type}`"
        role="status"
      >
        <v-icon size="small" class="toast-item__icon">{{ ICONS[item.type] }}</v-icon>
        <span class="toast-item__message">{{ item.message }}</span>
        <v-btn
          icon="mdi-close"
          size="x-small"
          variant="text"
          aria-label="关闭提示"
          @click="toast.dismiss(item.id)"
        />
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
/* 顶部居中悬浮，层级高于对话框遮罩（vuetify overlay z-index 约 2400） */
.toast-host {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10000;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: min(92vw, 560px);
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  pointer-events: auto;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
}

.toast-item--success {
  border-left: 4px solid rgb(var(--v-theme-success));
}

.toast-item--error {
  border-left: 4px solid rgb(var(--v-theme-error));
}

.toast-item--info {
  border-left: 4px solid rgb(var(--v-theme-info));
}

.toast-item__icon {
  flex: 0 0 auto;
}

.toast-item__message {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 0.875rem;
  line-height: 1.4;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 顶部滑入、自动滑出，形似短信通知横幅 */
.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: transform 0.22s ease, opacity 0.22s ease;
}

.toast-slide-enter-from,
.toast-slide-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}

.toast-slide-leave-to {
  position: absolute;
}

.toast-slide-move {
  transition: transform 0.22s ease;
}
</style>
