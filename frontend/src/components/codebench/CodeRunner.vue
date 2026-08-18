<script setup>
import { computed, ref, watch } from 'vue'
import CodeEditor from './CodeEditor.vue'
import CodeOutput from './CodeOutput.vue'
import CodeToolbar from './CodeToolbar.vue'
import { executeCourseCode } from '@/api/sandbox.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  languages: { type: Array, default: () => [] },
  stdin: { type: String, default: '' },
  courseId: { type: [String, Number], required: true },
  showStdin: { type: Boolean, default: true },
  showOutput: { type: Boolean, default: true },
})

const emit = defineEmits([
  'update:modelValue',
  'update:language',
  'update:stdin',
  'run-start',
  'run-complete',
  'run-error',
])

const runState = ref('idle') // idle | running | success | error
const stdout = ref('')
const stderr = ref('')
const executionTime = ref(0)
const memory = ref(0)
const exitCode = ref(null)

const canRun = computed(() => {
  return props.modelValue?.trim().length > 0 && runState.value !== 'running'
})

const outputStatus = computed(() => {
  if (runState.value === 'running') return 'running'
  if (runState.value === 'success') return 'success'
  if (runState.value === 'error') return 'error'
  return 'idle'
})

async function handleRun() {
  if (!canRun.value) return

  runState.value = 'running'
  stdout.value = ''
  stderr.value = ''
  exitCode.value = null
  executionTime.value = 0
  memory.value = 0

  emit('run-start')

  try {
    const result = await executeCourseCode(props.courseId, {
      language: props.language,
      source_code: props.modelValue,
      stdin: props.stdin,
    })

    stdout.value = result.stdout || ''
    stderr.value = result.stderr || ''
    exitCode.value = result.exit_code ?? null
    executionTime.value = result.time_ms || 0
    memory.value = result.memory_kb || 0

    if (result.status === 'success' || result.exit_code === 0) {
      runState.value = 'success'
    } else {
      runState.value = 'error'
    }

    emit('run-complete', result)
  } catch (error) {
    runState.value = 'error'
    stderr.value = error?.message || '运行失败，请稍后重试'
    emit('run-error', error)
  }
}

function handleLanguageChange(lang) {
  emit('update:language', lang)
}

function handleCodeChange(code) {
  emit('update:modelValue', code)
}

function handleStdinChange(e) {
  emit('update:stdin', e.target.value)
}

// 暴露方法
defineExpose({
  run: handleRun,
  resetOutput: () => {
    runState.value = 'idle'
    stdout.value = ''
    stderr.value = ''
    exitCode.value = null
    executionTime.value = 0
    memory.value = 0
  },
})
</script>

<template>
  <div class="code-runner">
    <div class="runner-editor-section">
      <CodeToolbar
        :languages="languages"
        :selected-language="language"
        :run-state="runState"
        :can-run="canRun"
        :show-reset="false"
        :show-copy="false"
        @update:selected-language="handleLanguageChange"
        @run="handleRun"
      />
      <div class="editor-container">
        <CodeEditor
          :model-value="modelValue"
          :language="language"
          :readonly="runState === 'running'"
          @update:model-value="handleCodeChange"
          @run-shortcut="handleRun"
        />
      </div>
    </div>

    <!-- 自定义输入 -->
    <div v-if="showStdin" class="runner-stdin-section">
      <div class="stdin-header">
        <span class="stdin-label">自定义输入</span>
      </div>
      <textarea
        :value="stdin"
        @input="handleStdinChange"
        class="stdin-textarea"
        placeholder="在此输入测试数据，每行一个输入"
        spellcheck="false"
        :disabled="runState === 'running'"
      />
    </div>

    <!-- 输出结果 -->
    <div v-if="showOutput" class="runner-output-section">
      <CodeOutput
        :stdout="stdout"
        :stderr="stderr"
        :status="outputStatus"
        :execution-time="executionTime"
        :memory="memory"
        :exit-code="exitCode"
        title="运行结果"
      />
    </div>
  </div>
</template>

<style scoped>
.code-runner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--code-bg);
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--code-border);
}

.runner-editor-section {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.editor-container {
  flex: 1;
  min-height: 0;
  position: relative;
}

.runner-stdin-section {
  flex-shrink: 0;
  border-top: 1px solid var(--code-border);
  background: var(--code-panel);
  max-height: 140px;
  display: flex;
  flex-direction: column;
}

.stdin-header {
  flex-shrink: 0;
  padding: 6px 12px;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid var(--code-border);
}

.stdin-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--code-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stdin-textarea {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: var(--code-text);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.5;
  resize: none;
  outline: none;
}

.stdin-textarea::placeholder {
  color: var(--code-muted);
  opacity: 0.6;
}

.stdin-textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.runner-output-section {
  flex-shrink: 0;
  border-top: 1px solid var(--code-border);
  max-height: 200px;
  min-height: 120px;
}
</style>
