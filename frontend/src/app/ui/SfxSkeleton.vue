<script setup>
/**
 * 骨架屏（page-design §22.1）：首次加载使用骨架，不用旋转图标遮住整个壳。
 */
defineProps({
  lines: { type: Number, default: 3 },
  block: { type: Boolean, default: false },
})
</script>

<template>
  <div class="sfx-skeleton" aria-hidden="true">
    <div v-if="block" class="sfx-skeleton-block" />
    <div v-for="i in lines" :key="i" class="sfx-skeleton-line" :style="{ width: i === lines ? '62%' : '100%' }" />
  </div>
</template>

<style scoped>
.sfx-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) 0;
}

.sfx-skeleton-block {
  height: 160px;
  border-radius: var(--radius-lg);
  background: var(--surface-soft);
  animation: sfx-skeleton-pulse 1.4s ease-in-out infinite;
}

.sfx-skeleton-line {
  height: 14px;
  border-radius: var(--radius-xs);
  background: var(--surface-soft);
  animation: sfx-skeleton-pulse 1.4s ease-in-out infinite;
}

@keyframes sfx-skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>
