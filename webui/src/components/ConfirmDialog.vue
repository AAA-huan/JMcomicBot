<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    text?: string
    confirmText?: string
    confirmColor?: string
    loading?: boolean
  }>(),
  {
    text: '',
    confirmText: '确认',
    confirmColor: 'error',
    loading: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: []
}>()
</script>

<template>
  <v-dialog
    :model-value="modelValue"
    max-width="440"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card>
      <v-card-title class="text-wrap">{{ title }}</v-card-title>
      <v-card-text v-if="text || $slots.default" class="text-body-2">
        <slot>{{ text }}</slot>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="emit('update:modelValue', false)">
          取消
        </v-btn>
        <v-btn
          :color="confirmColor"
          :loading="loading"
          @click="emit('confirm')"
        >
          {{ confirmText }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
