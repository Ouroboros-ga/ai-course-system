<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: {
    type: Number,
    default: 0,
    validator: (v) => v >= 0 && v <= 100,
  },
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'success', 'warning', 'danger'].includes(v),
  },
  showLabel: {
    type: Boolean,
    default: false,
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})

const clampedValue = computed(() => Math.min(100, Math.max(0, props.value)))
const widthStyle = computed(() => ({ width: `${clampedValue.value}%` }))

const barHeight = computed(() => {
  const map = { sm: '4px', md: '8px', lg: '12px' }
  return map[props.size]
})
</script>

<template>
  <div class="ui-progress">
    <div
      class="ui-progress__track"
      :class="`ui-progress__track--${size}`"
      :style="{ height: barHeight }"
    >
      <div
        class="ui-progress__bar"
        :class="`ui-progress__bar--${variant}`"
        :style="widthStyle"
      />
    </div>
    <span v-if="showLabel" class="ui-progress__label">{{ clampedValue }}%</span>
  </div>
</template>

<style scoped>
.ui-progress {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  font-family: var(--font-sans);
}

.ui-progress__track {
  flex: 1;
  width: 100%;
  background: var(--color-surface-2);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.ui-progress__bar {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease);
}

/* ── 变体 ── */
.ui-progress__bar--primary {
  background: var(--gradient-primary);
}

.ui-progress__bar--success {
  background: var(--gradient-success);
}

.ui-progress__bar--warning {
  background: var(--gradient-warning);
}

.ui-progress__bar--danger {
  background: var(--gradient-danger);
}

.ui-progress__label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  min-width: 36px;
  text-align: right;
  line-height: var(--leading-normal);
}
</style>
