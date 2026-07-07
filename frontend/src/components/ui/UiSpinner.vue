<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  color: {
    type: String,
    default: 'var(--color-primary)',
  },
})

const dimension = computed(() => {
  const map = { sm: '16px', md: '24px', lg: '36px' }
  return map[props.size]
})
</script>

<template>
  <span
    class="ui-spinner"
    :style="{ width: dimension, height: dimension, borderTopColor: color }"
    role="status"
    aria-label="加载中"
  />
</template>

<style scoped>
.ui-spinner {
  display: inline-block;
  border: 2px solid var(--color-border);
  border-radius: var(--radius-full);
  animation: ui-spinner-spin 0.6s linear infinite;
}

@keyframes ui-spinner-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
