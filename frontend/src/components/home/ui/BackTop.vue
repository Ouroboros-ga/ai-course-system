<script setup>
import { ArrowUp } from 'lucide-vue-next'
</script>

<template>
  <button
    class="back-top"
    aria-label="返回顶部"
    @click="$emit('go-top')"
  >
    <ArrowUp :size="22" />
  </button>
</template>

<style scoped>
.back-top {
  position: fixed;
  right: var(--space-6);
  bottom: var(--space-6);
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  color: var(--color-primary);
  cursor: pointer;
  box-shadow: var(--shadow-md);
  z-index: var(--z-fixed);
  transition: var(--transition-all);
}

.back-top:hover {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border-color: transparent;
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

@media (prefers-reduced-motion: reduce) {
  .back-top:hover {
    transform: none;
  }
}
</style>
