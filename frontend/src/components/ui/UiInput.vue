<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: [String, Number],
    default: '',
  },
  type: {
    type: String,
    default: 'text',
    validator: (v) => ['text', 'password', 'email', 'number'].includes(v),
  },
  placeholder: {
    type: String,
    default: '',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
  label: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['update:modelValue'])

const hasError = computed(() => Boolean(props.error))

function handleInput(e) {
  emit('update:modelValue', e.target.value)
}
</script>

<template>
  <div :class="['ui-input', { 'has-error': hasError, 'is-disabled': disabled }]">
    <label v-if="label" class="ui-input__label">{{ label }}</label>
    <input
      class="ui-input__field"
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-invalid="hasError"
      @input="handleInput"
    />
    <p v-if="hasError" class="ui-input__error">{{ error }}</p>
  </div>
</template>

<style scoped>
.ui-input {
  display: flex;
  flex-direction: column;
  width: 100%;
  font-family: var(--font-sans);
}

.ui-input__label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
  font-weight: var(--font-medium);
}

.ui-input__field {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-family: var(--font-sans);
  color: var(--color-text);
  line-height: var(--leading-normal);
  outline: none;
  transition:
    border-color var(--duration-normal) var(--ease),
    box-shadow var(--duration-normal) var(--ease);
}

.ui-input__field::placeholder {
  color: var(--color-text-muted);
}

.ui-input__field:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* ── 错误态 ── */
.has-error .ui-input__field {
  border-color: var(--color-danger);
}

.has-error .ui-input__field:focus {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 3px var(--color-danger-light);
}

.ui-input__error {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-danger);
  line-height: var(--leading-normal);
}

/* ── 禁用态 ── */
.is-disabled .ui-input__field {
  background: var(--color-surface-2);
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
