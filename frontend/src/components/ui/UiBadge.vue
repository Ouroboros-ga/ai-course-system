<script setup>
defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'success', 'warning', 'danger', 'info', 'neutral'].includes(v),
  },
  size: {
    type: String,
    default: 'sm',
    validator: (v) => ['sm', 'md'].includes(v),
  },
})
</script>

<template>
  <span :class="['ui-badge', `ui-badge--${variant}`, `ui-badge--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.ui-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-family: var(--font-sans);
  font-weight: var(--font-medium);
  line-height: var(--leading-normal);
  white-space: nowrap;
}

/* ── 尺寸 ── */
.ui-badge--sm {
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
  border-radius: var(--radius-full);
}

.ui-badge--md {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  border-radius: var(--radius-full);
}

/* ── 变体 ── */
.ui-badge--primary {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.ui-badge--success {
  background: var(--color-success-light);
  color: var(--color-success);
}

.ui-badge--warning {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.ui-badge--danger {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.ui-badge--info {
  background: var(--color-info-light);
  color: var(--color-info);
}

.ui-badge--neutral {
  background: var(--color-surface-2);
  color: var(--color-text-secondary);
}
</style>
