<script setup>
import { LoaderCircle } from 'lucide-vue-next'

const props = defineProps({
  variant: { type: String, default: 'primary', validator: (v) => ['primary', 'secondary', 'tertiary', 'danger'].includes(v) },
  size: { type: String, default: 'md', validator: (v) => ['md', 'sm'].includes(v) },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  type: { type: String, default: 'button' },
})

const emit = defineEmits(['click'])

function handleClick(event) {
  if (props.disabled || props.loading) return
  emit('click', event)
}
</script>

<template>
  <button :type="type" class="sfx-btn" :class="[`is-${variant}`, `is-${size}`]" :disabled="disabled || loading"
    @click="handleClick">
    <LoaderCircle v-if="loading" :size="16" class="sfx-btn-spinner" />
    <slot v-else name="icon" />
    <span class="sfx-btn-label">
      <slot />
    </span>
  </button>
</template>

<style scoped>
.sfx-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  /* min-height 而非 height：上下 padding 真实生效，避免 border-box 下被内容区压缩 */
  min-height: var(--control-height);
  padding: 8px 20px;
  min-width: 0;
  /* 允许在 flex 父容器中被压缩 */
  max-width: 100%;
  /* 不超出父容器，避免撑破布局 */
  border-radius: var(--radius-md);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  font-family: inherit;
  border: 1px solid transparent;
  cursor: pointer;
  overflow: hidden;
  /* 兜底：内容不溢出按钮边界 */
  transition: background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

/* 文本单行 + 超长省略，避免固定高度内内容换行溢出；行高收紧让文字在边距内舒展 */
.sfx-btn-label {
  min-width: 0;
  /* 允许收缩以触发省略号 */
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sfx-btn.is-sm {
  min-height: 32px;
  padding: 6px var(--space-3);
  font-size: var(--ui-sm-size);
}

.sfx-btn.is-primary {
  background: var(--color-brand);
  color: var(--text-inverse);
}

.sfx-btn.is-primary:hover:not(:disabled) {
  background: var(--color-brand-hover);
}

.sfx-btn.is-primary:active:not(:disabled) {
  transform: translateY(1px);
}

.sfx-btn.is-secondary {
  background: var(--surface-panel);
  border-color: var(--border-strong);
  color: var(--ink-700);
}

.sfx-btn.is-secondary:hover:not(:disabled) {
  background: var(--surface-cool);
}

.sfx-btn.is-tertiary {
  background: transparent;
  color: var(--text-link);
  padding: 0 var(--space-2);
}

.sfx-btn.is-tertiary:hover:not(:disabled) {
  background: var(--ink-100);
}

/* 危险操作默认白底红字红边，不做大红实心（design.md 4.3） */
.sfx-btn.is-danger {
  background: var(--surface-panel);
  border-color: var(--red-500);
  color: var(--red-700);
}

.sfx-btn.is-danger:hover:not(:disabled) {
  background: var(--red-100);
}

.sfx-btn:disabled {
  background: var(--border-strong);
  border-color: var(--border-strong);
  color: var(--text-muted);
  cursor: not-allowed;
  transform: none;
}

.sfx-btn.is-secondary:disabled,
.sfx-btn.is-tertiary:disabled,
.sfx-btn.is-danger:disabled {
  background: transparent;
  border-color: var(--border-default);
  color: var(--text-disabled);
}

.sfx-btn-spinner {
  animation: sfx-btn-spin 0.9s linear infinite;
}

@keyframes sfx-btn-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
