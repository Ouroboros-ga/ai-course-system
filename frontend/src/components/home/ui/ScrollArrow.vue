<script setup>
import { ChevronDown } from 'lucide-vue-next'
</script>

<template>
  <button
    class="scroll-arrow"
    aria-label="向下滚动"
    @click="$emit('go-next')"
  >
    <ChevronDown class="arrow-icon" :size="28" />
  </button>
</template>

<style scoped>
.scroll-arrow {
  position: fixed;
  bottom: var(--space-8);
  left: 50%;
  transform: translateX(-50%);
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-primary);
  cursor: pointer;
  box-shadow: var(--shadow-md);
  z-index: var(--z-fixed);
  transition: var(--transition-all);
}

.scroll-arrow:hover {
  color: var(--color-primary-hover);
  box-shadow: var(--shadow-lg);
  transform: translateX(-50%) translateY(-2px);
}

.arrow-icon {
  animation: bounce 2s var(--ease) infinite;
}

@keyframes bounce {
  0%,
  100% {
    transform: translateY(0);
    opacity: 1;
  }
  50% {
    transform: translateY(6px);
    opacity: 0.5;
  }
}

@media (prefers-reduced-motion: reduce) {
  .arrow-icon {
    animation: none;
  }
  .scroll-arrow:hover {
    transform: translateX(-50%);
  }
}
</style>
