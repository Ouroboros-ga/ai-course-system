<script setup>
/**
 * 表单字段行（design.md 4.4 + page-design §22.7 校验语义）。
 * label + 控件 + 说明/错误；错误必须同时有图标和文案（design.md 4.4）。
 */
import { CircleAlert } from 'lucide-vue-next'

defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  required: { type: Boolean, default: false },
  forId: { type: String, default: '' },
})
</script>

<template>
  <div class="sfx-field" :class="{ 'has-error': error }">
    <label class="sfx-field-label sfx-t-ui" :for="forId || undefined">
      {{ label }}
      <span v-if="required" class="sfx-field-required" aria-hidden="true">*</span>
    </label>
    <div class="sfx-field-control">
      <slot />
    </div>
    <p v-if="error" class="sfx-field-error sfx-t-caption" role="alert">
      <CircleAlert :size="13" aria-hidden="true" /> {{ error }}
    </p>
    <p v-else-if="hint" class="sfx-field-hint sfx-t-caption">{{ hint }}</p>
  </div>
</template>

<style scoped>
.sfx-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-field-label {
  color: var(--text-primary);
}

.sfx-field-required { color: var(--red-500); margin-left: 2px; }

.sfx-field-hint { color: var(--text-muted); }

.sfx-field-error {
  color: var(--red-700);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-field.has-error :deep(.sfx-input),
.sfx-field.has-error :deep(.sfx-select),
.sfx-field.has-error :deep(.sfx-textarea) {
  border-color: var(--red-500);
}
</style>
