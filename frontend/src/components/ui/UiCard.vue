<script setup>
defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'glass', 'elevated'].includes(v),
  },
  hover: {
    type: Boolean,
    default: false,
  },
  padding: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})
</script>

<template>
  <div
    :class="['ui-card', `ui-card--${variant}`, `ui-card--p-${padding}`, { 'is-hover': hover }]"
  >
    <div v-if="$slots.header" class="ui-card__header">
      <slot name="header" />
    </div>
    <div class="ui-card__body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="ui-card__footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.ui-card {
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
  font-family: var(--font-sans);
}

/* ── 变体 ── */
.ui-card--default {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.ui-card--glass {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: var(--radius-lg);
}

.ui-card--elevated {
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
}

/* ── padding ── */
.ui-card--p-sm .ui-card__body {
  padding: var(--space-3);
}

.ui-card--p-md .ui-card__body {
  padding: var(--space-5);
}

.ui-card--p-lg .ui-card__body {
  padding: var(--space-6);
}

/* ── header / footer ── */
.ui-card__header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.ui-card__footer {
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
}

/* ── hover 效果 ── */
.is-hover {
  transition:
    transform var(--duration-normal) var(--ease),
    box-shadow var(--duration-normal) var(--ease);
}

.is-hover:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}
</style>
