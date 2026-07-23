<script setup>
import { Inbox } from 'lucide-vue-next'

/**
 * 空状态（page-design §22.2）：说明 + 一个明确下一步。
 * 区分首次空 / 筛选空 / 权限不可见 / 尚未建设 —— 由调用方用文案表达。
 */
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="sfx-empty" role="status">
    <div class="sfx-empty-icon" aria-hidden="true">
      <slot name="icon"><Inbox :size="28" :stroke-width="1.8" /></slot>
    </div>
    <h3 class="sfx-empty-title sfx-t-title3">{{ title }}</h3>
    <p v-if="description" class="sfx-empty-desc sfx-t-ui sfx-t-secondary">{{ description }}</p>
    <div v-if="$slots.default" class="sfx-empty-action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.sfx-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-16) var(--space-6);
  gap: var(--space-3);
}

.sfx-empty-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-full);
  background: var(--surface-soft);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
}

.sfx-empty-title {
  color: var(--text-primary);
}

.sfx-empty-desc {
  max-width: 420px;
}

.sfx-empty-action {
  margin-top: var(--space-2);
}
</style>
