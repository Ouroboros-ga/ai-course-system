<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Code2, Play, Send, ChevronDown, RotateCcw, Copy, Check } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  languages: { type: Array, default: () => [] },
  selectedLanguage: { type: String, default: '' },
  /**
   * 呈现变体。默认 'course' = 原样（课程实验页在用）。
   * 'oj' = OJ 题目详情页的呈现：左侧多一个「代码」页签与「自测」入口，
   * 语言下拉右侧加一个只读的编译级别状态位。**默认值保证既有页面零变化。**
   */
  variant: { type: String, default: 'course', validator: (v) => ['course', 'oj'].includes(v) },
  runState: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'running', 'success', 'error'].includes(v),
  },
  submitState: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'running', 'success', 'error'].includes(v),
  },
  canRun: { type: Boolean, default: true },
  canSubmit: { type: Boolean, default: true },
  showReset: { type: Boolean, default: false },
  showCopy: { type: Boolean, default: false },
  /** OJ 变体下的运行/提交文案（截图为「自测」/「提交」）。 */
  runLabel: { type: String, default: '运行' },
  submitLabel: { type: String, default: '提交评测' },
})

const emit = defineEmits([
  'update:selectedLanguage',
  'run',
  'submit',
  'reset',
  'copy',
])

const langDropdownOpen = ref(false)
const copied = ref(false)

const displayLanguage = computed(() => {
  const lang = props.selectedLanguage
  const map = {
    python: 'Python',
    javascript: 'JavaScript',
    js: 'JavaScript',
    typescript: 'TypeScript',
    cpp: 'C++',
    'c++': 'C++',
    c: 'C',
    java: 'Java',
  }
  return map[lang?.toLowerCase()] || lang || '选择语言'
})

const isRunning = computed(() => props.runState === 'running')
const isSubmitting = computed(() => props.submitState === 'running')

function selectLanguage(lang) {
  emit('update:selectedLanguage', lang)
  langDropdownOpen.value = false
}

function handleRun() {
  emit('run')
}

function handleSubmit() {
  emit('submit')
}

function handleReset() {
  emit('reset')
}

function handleCopy() {
  emit('copy')
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 2000)
}

// 点击外部关闭下拉
const toolbarRef = ref(null)

function handleClickOutside(event) {
  if (toolbarRef.value && !toolbarRef.value.contains(event.target)) {
    langDropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="code-toolbar" :class="{ 'is-oj': variant === 'oj' }" ref="toolbarRef">
    <div class="toolbar-left">
      <!-- OJ 变体：静态「代码」页签（本系统只有一个代码视图，不做假页签切换） -->
      <span v-if="variant === 'oj'" class="oj-code-tab">
        <Code2 :size="14" />
        <span>代码</span>
      </span>

      <!-- 语言选择器 -->
      <div class="lang-selector" :class="{ 'is-open': langDropdownOpen }">
        <button
          class="lang-trigger"
          :disabled="!languages.length"
          @click="langDropdownOpen = !langDropdownOpen"
        >
          <span class="lang-label">{{ displayLanguage }}</span>
          <ChevronDown :size="14" :class="{ 'is-rotated': langDropdownOpen }" />
        </button>
        <div v-if="langDropdownOpen && languages.length" class="lang-dropdown">
          <button
            v-for="lang in languages"
            :key="lang"
            class="lang-option"
            :class="{ 'is-selected': selectedLanguage === lang }"
            @click="selectLanguage(lang)"
          >
            <span class="lang-option-name">
              {{ { python: 'Python', javascript: 'JavaScript', cpp: 'C++', c: 'C', java: 'Java' }[lang.toLowerCase()] || lang }}
            </span>
            <Check v-if="selectedLanguage === lang" :size="14" />
          </button>
        </div>
      </div>

      <!-- OJ 变体：编译优化级别状态位。
           ⚠️ 故意做成静态文本而不是下拉 —— 本系统判题环境没有"优化级别"这个可调维度，
           造一个点了没反应的控件比不显示更糟。 -->
      <span
        v-if="variant === 'oj'"
        class="oj-opt-chip"
        title="判题环境使用固定的编译参数，优化级别不可调"
      >O2</span>
    </div>

    <div class="toolbar-right">
      <!-- 复制按钮 -->
      <SfxButton
        v-if="showCopy"
        variant="secondary"
        size="sm"
        @click="handleCopy"
        :disabled="isRunning || isSubmitting"
      >
        <template #icon>
          <component :is="copied ? Check : Copy" :size="14" />
        </template>
        {{ copied ? '已复制' : '复制' }}
      </SfxButton>

      <!-- 重置按钮 -->
      <SfxButton
        v-if="showReset"
        variant="secondary"
        size="sm"
        @click="handleReset"
        :disabled="isRunning || isSubmitting"
      >
        <template #icon>
          <RotateCcw :size="14" />
        </template>
        重置
      </SfxButton>

      <!-- 运行按钮（自由测试）；OJ 变体下文案为「自测」 -->
      <SfxButton
        :variant="variant === 'oj' ? 'primary' : 'secondary'"
        size="sm"
        @click="handleRun"
        :disabled="!canRun || isSubmitting"
        :loading="isRunning"
      >
        <template #icon>
          <Play :size="14" :fill="'currentColor'" />
        </template>
        {{ runLabel }}
      </SfxButton>

      <!-- 提交按钮（正式评测） -->
      <SfxButton
        variant="primary"
        size="sm"
        @click="handleSubmit"
        :disabled="!canSubmit || isRunning"
        :loading="isSubmitting"
      >
        <template #icon>
          <Send :size="14" />
        </template>
        {{ submitLabel }}
      </SfxButton>
    </div>
  </div>
</template>

<style scoped>
.code-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--code-panel);
  border-bottom: 1px solid var(--code-border);
  gap: 12px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── OJ 变体（题目详情页）：只在这一支里出现截图里的「代码」页签与 O2 状态位 ── */
.oj-code-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--code-text);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.oj-opt-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border: 1px dashed var(--code-border);
  border-radius: 6px;
  color: var(--code-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: help;
  user-select: none;
  white-space: nowrap;
}

/* 语言选择器 */
.lang-selector {
  position: relative;
}

.lang-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: 6px;
  color: var(--code-text);
  font-size: 13px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.lang-trigger:hover:not(:disabled) {
  border-color: var(--ink-500);
}

.lang-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.lang-label {
  font-weight: 500;
}

.lang-trigger svg {
  transition: transform var(--duration-fast) var(--ease-out);
  color: var(--code-muted);
}

.lang-trigger svg.is-rotated {
  transform: rotate(180deg);
}

.lang-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  min-width: 160px;
  background: var(--code-panel);
  border: 1px solid var(--code-border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  z-index: 100;
  overflow: hidden;
  padding: 4px;
}

.lang-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--code-text);
  font-size: 13px;
  font-family: var(--font-mono);
  cursor: pointer;
  text-align: left;
  transition: background var(--duration-fast) var(--ease-out);
}

.lang-option:hover {
  background: rgba(255, 255, 255, 0.06);
}

.lang-option.is-selected {
  background: rgba(53, 92, 125, 0.25);
  color: var(--code-text);
}

.lang-option-name {
  font-weight: 500;
}
</style>
