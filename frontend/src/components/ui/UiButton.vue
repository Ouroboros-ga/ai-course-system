<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'secondary', 'ghost', 'danger', 'success'].includes(v),
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  loading: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  block: {
    type: Boolean,
    default: false,
  },
  type: {
    type: String,
    default: 'button',
    validator: (v) => ['button', 'submit', 'reset'].includes(v),
  },
})

const emit = defineEmits(['click'])

const isDisabled = computed(() => props.disabled || props.loading)

function handleClick(e) {
  if (isDisabled.value) return
  emit('click', e)
}
</script>

<template>
  <button
    :type="type"
    :class="['ui-btn', `ui-btn--${variant}`, `ui-btn--${size}`, { 'is-block': block, 'is-loading': loading, 'is-disabled': isDisabled }]"
    :disabled="isDisabled"
    @click="handleClick"
  >
    <span v-if="loading" class="ui-btn__spinner" aria-hidden="true" />
    <span v-if="$slots.icon" class="ui-btn__icon">
      <slot name="icon" />
    </span>
    <span class="ui-btn__text">
      <slot />
    </span>
  </button>
</template>

<style scoped>
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: var(--font-sans);
  font-weight: var(--font-semibold);
  line-height: var(--leading-normal);
  cursor: pointer;
  border: none;
  outline: none;
  user-select: none;
  white-space: nowrap;
  transition:
    background var(--duration-normal) var(--ease),
    box-shadow var(--duration-normal) var(--ease),
    border-color var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease),
    transform var(--duration-normal) var(--ease);
}

.ui-btn:hover:not(.is-disabled) {
  transform: translateY(-1px);
}

.ui-btn:active:not(.is-disabled) {
  transform: translateY(0);
}

.ui-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* ── 尺寸 ── */
.ui-btn--sm {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  border-radius: var(--radius-sm);
}

.ui-btn--md {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-base);
  border-radius: var(--radius-md);
}

.ui-btn--lg {
  padding: var(--space-3) var(--space-5);
  font-size: var(--text-lg);
  border-radius: var(--radius-lg);
}

/* ── 变体：primary ── */
.ui-btn--primary {
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  box-shadow: var(--shadow-xs);
}

.ui-btn--primary:hover:not(.is-disabled) {
  background: var(--gradient-primary-hover);
  box-shadow: var(--shadow-primary);
}

/* ── 变体：secondary ── */
.ui-btn--secondary {
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-xs);
}

.ui-btn--secondary:hover:not(.is-disabled) {
  border-color: var(--color-border-hover);
  background: var(--color-surface-2);
}

/* ── 变体：ghost ── */
.ui-btn--ghost {
  background: transparent;
  color: var(--color-primary);
}

.ui-btn--ghost:hover:not(.is-disabled) {
  background: var(--color-primary-light);
}

/* ── 变体：danger ── */
.ui-btn--danger {
  background: var(--color-danger);
  color: var(--color-text-inverse);
  box-shadow: var(--shadow-xs);
}

.ui-btn--danger:hover:not(.is-disabled) {
  background: var(--color-danger-hover);
  box-shadow: var(--shadow-danger);
}

/* ── 变体：success ── */
.ui-btn--success {
  background: var(--color-success);
  color: var(--color-text-inverse);
  box-shadow: var(--shadow-xs);
}

.ui-btn--success:hover:not(.is-disabled) {
  background: var(--color-success-hover);
  box-shadow: var(--shadow-success);
}

/* ── 状态 ── */
.is-block {
  display: flex;
  width: 100%;
}

.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 加载 spinner ── */
.ui-btn__spinner {
  width: 1em;
  height: 1em;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: var(--radius-full);
  animation: ui-btn-spin 0.6s linear infinite;
}

@keyframes ui-btn-spin {
  to {
    transform: rotate(360deg);
  }
}

.ui-btn__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
