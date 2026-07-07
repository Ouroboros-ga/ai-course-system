<script setup>
defineProps({
  modelValue: {
    type: [String, Number],
    default: '',
  },
  tabs: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['update:modelValue'])

function selectTab(value) {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="ui-tabs">
    <div class="ui-tabs__nav" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        type="button"
        role="tab"
        :aria-selected="tab.value === modelValue"
        :class="['ui-tabs__item', { 'is-active': tab.value === modelValue }]"
        @click="selectTab(tab.value)"
      >
        <span v-if="tab.icon" class="ui-tabs__icon">{{ tab.icon }}</span>
        <span class="ui-tabs__label">{{ tab.label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.ui-tabs {
  font-family: var(--font-sans);
  width: 100%;
}

.ui-tabs__nav {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border);
  padding: 0 var(--space-1);
}

.ui-tabs__item {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  transition:
    color var(--duration-normal) var(--ease),
    background var(--duration-normal) var(--ease);
  line-height: var(--leading-normal);
}

.ui-tabs__item:hover {
  color: var(--color-text);
  background: var(--color-surface-2);
}

.ui-tabs__item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}

.ui-tabs__item.is-active {
  color: var(--color-primary);
  font-weight: var(--font-semibold);
}

.ui-tabs__item.is-active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--color-primary);
  border-radius: var(--radius-full);
}

.ui-tabs__icon {
  display: inline-flex;
  align-items: center;
}
</style>
