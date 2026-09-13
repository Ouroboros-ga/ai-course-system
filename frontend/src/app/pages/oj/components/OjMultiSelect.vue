<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown, X } from 'lucide-vue-next'

/**
 * OJ 多选下拉（算法标签筛选用）。
 * 用 span[role=button] 而非原生 <button> —— design.md 硬约束，
 * 且 apiContracts.test.cjs 对若干页面直接断言 `doesNotMatch(src, /<button[\s>]/)`。
 *
 * options 同时接受 ['贪心', …] 与 [{ value, label }] 两种形态，
 * 后者留给后端补上「来源 / 年份」结构化字段后直接接。
 */
const props = defineProps({
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  emptyText: { type: String, default: '暂无可选项' },
  /** 收起时是否展示已选项的标签名（单选场景更易读）。 */
  showSingleLabel: { type: Boolean, default: true },
})

const model = defineModel({ type: Array, default: () => [] })

const open = ref(false)
const root = ref(null)

const normalized = computed(() => (Array.isArray(props.options) ? props.options : []).map((option) => (
  typeof option === 'string' || typeof option === 'number'
    ? { value: String(option), label: String(option) }
    : { value: String(option?.value ?? ''), label: String(option?.label ?? option?.value ?? '') }
)).filter((option) => option.value !== ''))

const selectedValues = computed(() => (Array.isArray(model.value) ? model.value.map(String) : []))

const summary = computed(() => {
  const count = selectedValues.value.length
  if (!count) return props.placeholder
  if (count === 1 && props.showSingleLabel) {
    const hit = normalized.value.find((option) => option.value === selectedValues.value[0])
    return hit ? hit.label : selectedValues.value[0]
  }
  return `已选 ${count} 项`
})

function isSelected(value) {
  return selectedValues.value.includes(String(value))
}

function toggle(value) {
  const key = String(value)
  const next = selectedValues.value.filter((item) => item !== key)
  if (next.length === selectedValues.value.length) next.push(key)
  model.value = next
}

function clearAll() {
  model.value = []
}

function handleClickOutside(event) {
  if (root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onBeforeUnmount(() => document.removeEventListener('click', handleClickOutside))
</script>

<template>
  <div ref="root" class="oj-ms" :class="{ 'is-open': open, 'has-value': selectedValues.length }">
    <span
      role="button"
      tabindex="0"
      class="oj-ms-trigger"
      :aria-expanded="open ? 'true' : 'false'"
      aria-haspopup="listbox"
      @click="open = !open"
      @keyup.enter="open = !open"
      @keyup.space.prevent="open = !open"
    >
      <span class="oj-ms-summary">{{ summary }}</span>
      <span
        v-if="selectedValues.length"
        role="button"
        tabindex="0"
        class="oj-ms-clear"
        aria-label="清空已选"
        @click.stop="clearAll"
        @keyup.enter.stop="clearAll"
      ><X :size="12" /></span>
      <ChevronDown :size="14" class="oj-ms-caret" />
    </span>

    <div v-if="open" class="oj-ms-panel" role="listbox" aria-multiselectable="true">
      <p v-if="!normalized.length" class="oj-ms-empty">{{ emptyText }}</p>
      <!-- v-if/v-else 不能与 v-for 同元素（Vue 3 里 v-if 优先级更高） → 用 template 分组 -->
      <span
        v-for="option in (normalized.length ? normalized : [])"
        :key="option.value"
        role="option"
        tabindex="0"
        class="oj-ms-option"
        :class="{ 'is-selected': isSelected(option.value) }"
        :aria-selected="isSelected(option.value) ? 'true' : 'false'"
        @click="toggle(option.value)"
        @keyup.enter="toggle(option.value)"
      >
        <span class="oj-ms-check"><Check v-if="isSelected(option.value)" :size="12" /></span>
        <span class="oj-ms-option-label">{{ option.label }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.oj-ms { position: relative; }
.oj-ms-trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-primary);
  font-size: var(--ui-md-size);
  cursor: pointer;
  user-select: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.oj-ms-trigger:hover { border-color: var(--border-strong); }
.oj-ms.is-open .oj-ms-trigger { border-color: var(--color-focus); box-shadow: 0 0 0 2px var(--ink-100); }
.oj-ms-summary { white-space: nowrap; }
.oj-ms-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  color: var(--text-muted);
}
.oj-ms-clear:hover { background: var(--ink-100); color: var(--ink-900); }
.oj-ms-caret { color: var(--text-secondary); transition: transform var(--duration-fast) var(--ease-out); }
.oj-ms.is-open .oj-ms-caret { transform: rotate(180deg); }

.oj-ms-panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 60;
  min-width: 200px;
  max-height: 280px;
  overflow-y: auto;
  padding: var(--space-1);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
}
.oj-ms-option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-xs);
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  cursor: pointer;
}
.oj-ms-option:hover { background: var(--surface-cool); }
.oj-ms-option.is-selected { color: var(--ink-900); font-weight: var(--ui-md-weight); }
.oj-ms-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  color: var(--surface-panel);
}
.oj-ms-option.is-selected .oj-ms-check { background: var(--ink-900); border-color: var(--ink-900); }
.oj-ms-option-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.oj-ms-empty {
  margin: 0;
  padding: var(--space-3);
  font-size: var(--ui-sm-size);
  color: var(--text-muted);
}
</style>
