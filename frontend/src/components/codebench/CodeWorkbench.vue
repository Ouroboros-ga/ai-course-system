<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { BookOpen, Terminal, ListChecks, Lightbulb, GripHorizontal, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import CodeEditor from './CodeEditor.vue'
import CodeOutput from './CodeOutput.vue'
import CodeToolbar from './CodeToolbar.vue'
import CodeTestCases from './CodeTestCases.vue'
import { executeCourseCode } from '@/api/sandbox.js'
import {
  createExperimentAttempt,
  createExperimentRun,
  getExperimentRun,
  createCodingDiagnosis,
  getCodingRunExplanation,
  cancelExperimentRun,
} from '@/api/experiments.js'
import { getTask } from '@/api/tasks.js'
import { isTerminalTaskStatus } from '@/api/experimentRunContract.js'
import { renderContent } from '@/utils/markdownRenderer.js'

const props = defineProps({
  experiment: { type: Object, default: null },
  courseId: { type: [String, Number], required: true },
  languages: { type: Array, default: () => [] },
  mode: {
    type: String,
    default: 'formal',
    validator: (v) => ['free', 'formal', 'both'].includes(v),
  },
  initialCode: { type: String, default: '' },
  initialLanguage: { type: String, default: '' },
  problemCollapsed: { type: Boolean, default: false },
})

const emit = defineEmits([
  'code-change',
  'language-change',
  'run-start',
  'run-complete',
  'submit-start',
  'submit-complete',
  'submit-error',
  'update:problemCollapsed',
])

// 状态
const sourceCode = ref(props.initialCode || '')
const selectedLanguage = ref(props.initialLanguage || props.languages[0] || '')
const stdin = ref('')

// 题目描述面板收缩状态（参考 SfxLocalRail 设计模式）
const problemCollapsed = ref(props.problemCollapsed)
const STORAGE_KEY = 'sfx:workbench:problem-collapsed'

// 初始化从 localStorage 读取
try {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === '1') problemCollapsed.value = true
} catch { /* ignore */ }

watch(problemCollapsed, (val) => {
  emit('update:problemCollapsed', val)
  try { localStorage.setItem(STORAGE_KEY, val ? '1' : '0') } catch { /* ignore */ }
})

function toggleProblemPanel() {
  problemCollapsed.value = !problemCollapsed.value
}

// 自由运行状态
const freeRunState = ref('idle') // idle | running | success | error
const freeRunStdout = ref('')
const freeRunStderr = ref('')
const freeRunTime = ref(0)
const freeRunMemory = ref(0)
const freeRunExitCode = ref(null)

// 正式评测状态
const formalState = ref('idle') // idle | running | done | error
const formalRun = ref(null)
const formalTask = ref(null)
const formalTestCases = ref([])
const formalOutcome = ref('')
const formalProgress = ref(0)
const formalDiagnosis = ref(null)
const formalExplanation = ref(null)

// UI 状态
const activeTab = ref('input') // input | output | testcases | diagnosis
const bottomPanelHeight = ref(240) // px，默认调高
const isDragging = ref(false)

// 编辑器 ref
const editorRef = ref(null)

// 轮询控制
let pollGeneration = 0

// 计算属性
const experimentDescriptionHtml = computed(() => {
  if (!props.experiment?.description) return ''
  return renderContent(props.experiment.description)
})

const canRun = computed(() => {
  return sourceCode.value.trim().length > 0 && freeRunState.value !== 'running' && formalState.value !== 'running'
})

const canSubmit = computed(() => {
  return sourceCode.value.trim().length > 0
    && props.experiment
    && formalState.value !== 'running'
    && freeRunState.value !== 'running'
})

const outputStatus = computed(() => {
  if (freeRunState.value === 'running') return 'running'
  if (freeRunState.value === 'success') return 'success'
  if (freeRunState.value === 'error') return 'error'
  return 'idle'
})

// 自由运行
async function handleFreeRun() {
  if (!canRun.value) return

  freeRunState.value = 'running'
  freeRunStdout.value = ''
  freeRunStderr.value = ''
  freeRunExitCode.value = null
  freeRunTime.value = 0
  freeRunMemory.value = 0
  activeTab.value = 'output'

  emit('run-start')

  try {
    const result = await executeCourseCode(props.courseId, {
      language: selectedLanguage.value,
      source_code: sourceCode.value,
      stdin: stdin.value,
    })

    freeRunStdout.value = result.stdout || ''
    freeRunStderr.value = result.stderr || ''
    freeRunExitCode.value = result.exit_code ?? null
    freeRunTime.value = result.time_ms || 0
    freeRunMemory.value = result.memory_kb || 0

    if (result.status === 'success' || result.exit_code === 0) {
      freeRunState.value = 'success'
    } else {
      freeRunState.value = 'error'
    }

    emit('run-complete', result)
  } catch (error) {
    freeRunState.value = 'error'
    freeRunStderr.value = error?.message || '运行失败，请稍后重试'
  }
}

// 正式评测
function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `experiment-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function waitForPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, 1000))
}

async function loadTerminalRun(runId) {
  formalRun.value = await getExperimentRun(props.courseId, runId)
  formalOutcome.value = formalRun.value?.outcome || ''

  // 转换测试用例格式
  if (formalRun.value?.test_results?.length) {
    formalTestCases.value = formalRun.value.test_results.map((r, i) => ({
      case_name: r.case_name || `测试 ${i + 1}`,
      passed: r.passed === true,
      is_hidden: r.is_hidden === true,
      stdin: r.stdin,
      expected_stdout: r.expected_stdout,
      actual_stdout: r.actual_stdout,
      time_ms: r.time_ms,
      memory_kb: r.memory_kb,
      reason: r.reason,
    }))
  } else {
    formalTestCases.value = []
  }

  // 加载诊断和讲解
  try {
    formalDiagnosis.value = await createCodingDiagnosis(props.courseId, runId)
  } catch {
    formalDiagnosis.value = null
  }

  try {
    formalExplanation.value = await getCodingRunExplanation(props.courseId, runId)
  } catch {
    formalExplanation.value = null
  }

  formalState.value = 'done'
  formalProgress.value = 100
}

async function pollFormalRun(taskId, runId, generation) {
  while (generation === pollGeneration) {
    const nextTask = await getTask(taskId)
    formalTask.value = nextTask
    formalProgress.value = nextTask?.progress || 0

    if (isTerminalTaskStatus(nextTask?.status)) {
      await loadTerminalRun(runId)
      return
    }

    formalState.value = 'running'
    await waitForPoll()
  }
}

async function handleSubmit() {
  if (!canSubmit.value || !props.experiment) return

  formalState.value = 'running'
  formalTestCases.value = []
  formalOutcome.value = ''
  formalDiagnosis.value = null
  formalExplanation.value = null
  formalProgress.value = 0
  activeTab.value = 'testcases'

  emit('submit-start')

  try {
    const attempt = await createExperimentAttempt(
      props.experiment.experiment_id,
      props.courseId,
      {},
    )

    if (!attempt?.attempt_id) throw new Error('无法创建评测尝试')

    const createdRun = await createExperimentRun(
      attempt.attempt_id,
      props.courseId,
      { language: selectedLanguage.value, source_code: sourceCode.value },
      newIdempotencyKey(),
    )

    if (!createdRun?.run_id || !createdRun?.task_id) throw new Error('无法提交评测')

    formalRun.value = createdRun
    const generation = ++pollGeneration
    await pollFormalRun(createdRun.task_id, createdRun.run_id, generation)

    emit('submit-complete', formalRun.value)
  } catch (error) {
    formalState.value = 'error'
    emit('submit-error', error)
  }
}

// 取消评测
async function handleCancelSubmit() {
  if (!formalRun.value?.run_id || formalState.value !== 'running') return
  try {
    await cancelExperimentRun(props.courseId, formalRun.value.run_id)
    pollGeneration += 1
    formalState.value = 'idle'
    formalOutcome.value = 'cancelled'
  } catch {
    // ignore
  }
}

// 语言切换
function handleLanguageChange(lang) {
  selectedLanguage.value = lang
  emit('language-change', lang)
}

// 重置代码
function handleReset() {
  if (props.experiment?.starter_code) {
    sourceCode.value = props.experiment.starter_code
  } else {
    sourceCode.value = ''
  }
}

// 复制代码
async function handleCopy() {
  try {
    await navigator.clipboard.writeText(sourceCode.value)
  } catch {
    // ignore
  }
}

// 底部面板拖拽
let dragStartY = 0
let dragStartHeight = 0
let workbenchContainer = null

function startResize(e) {
  isDragging.value = true
  dragStartY = e.clientY
  dragStartHeight = bottomPanelHeight.value
  // 保存容器引用,用于计算最大高度
  workbenchContainer = e.currentTarget.closest('.wb-editor-area')

  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
}

function onResize(e) {
  if (!isDragging.value) return
  const delta = dragStartY - e.clientY
  let newHeight = dragStartHeight + delta
  // 限制高度范围：120 ~ 60%
  // 修复：使用保存的容器引用而非 e.currentTarget.parentElement (document.parentElement 是 null)
  const maxHeight = workbenchContainer
    ? Math.floor(workbenchContainer.offsetHeight * 0.6)
    : 600
  newHeight = Math.max(120, Math.min(newHeight, maxHeight))
  bottomPanelHeight.value = newHeight
}

function stopResize() {
  isDragging.value = false
  workbenchContainer = null
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// Tab 定义
const tabs = [
  { key: 'input', label: '自定义输入', icon: Terminal },
  { key: 'output', label: '输出结果', icon: Terminal },
  { key: 'testcases', label: '测试详情', icon: ListChecks },
  { key: 'diagnosis', label: '诊断讲解', icon: Lightbulb },
]

const visibleTabs = computed(() => {
  if (props.mode === 'free') {
    return tabs.filter(t => ['input', 'output'].includes(t.key))
  }
  return tabs
})

// 监听实验变化
watch(() => props.experiment, (newExp) => {
  if (newExp) {
    if (newExp.starter_code && !sourceCode.value) {
      sourceCode.value = newExp.starter_code
    }
    if (newExp.language_whitelist?.length) {
      selectedLanguage.value = newExp.language_whitelist[0]
    }
  }
  // 重置评测状态
  formalState.value = 'idle'
  formalTestCases.value = []
  formalRun.value = null
  formalDiagnosis.value = null
  formalExplanation.value = null
  freeRunState.value = 'idle'
  freeRunStdout.value = ''
  freeRunStderr.value = ''
}, { immediate: true })

watch(() => props.initialCode, (val) => {
  if (val) sourceCode.value = val
})

watch(() => props.initialLanguage, (val) => {
  if (val) selectedLanguage.value = val
})

onBeforeUnmount(() => {
  pollGeneration += 1
  stopResize()
})

// 暴露方法
defineExpose({
  run: handleFreeRun,
  submit: handleSubmit,
  getCode: () => sourceCode.value,
  setCode: (code) => { sourceCode.value = code },
})
</script>

<template>
  <div class="code-workbench" :class="{ 'is-problem-collapsed': problemCollapsed }">
    <!-- 左侧：题目描述（可收缩，参考 SfxLocalRail 设计） -->
    <aside class="wb-problem" :class="{ 'is-collapsed': problemCollapsed }">
      <!-- 收缩态：垂直标题条 -->
      <div v-if="problemCollapsed" class="problem-collapsed-bar">
        <div class="collapsed-icon">
          <BookOpen :size="18" :stroke-width="1.8" />
        </div>
        <div class="collapsed-title">
          {{ experiment?.title || '题目描述' }}
        </div>
      </div>

      <!-- 展开态：完整内容 -->
      <template v-else>
        <div class="problem-header">
          <BookOpen :size="16" :stroke-width="1.8" />
          <span class="problem-title">{{ experiment?.title || '题目描述' }}</span>
        </div>
        <div class="problem-body">
          <div v-if="experimentDescriptionHtml" class="problem-content markdown-body" v-html="experimentDescriptionHtml"></div>
          <div v-else class="problem-empty">
            <BookOpen :size="32" :stroke-width="1.5" />
            <p>暂无题目描述</p>
          </div>
        </div>
      </template>

      <!-- 收缩/展开切换按钮（参考 SfxLocalRail 的 sfx-rail-toggle） -->
      <button
        type="button"
        class="problem-toggle"
        :aria-expanded="!problemCollapsed"
        :aria-label="problemCollapsed ? '展开题目描述' : '收缩题目描述'"
        :title="problemCollapsed ? '展开题目描述' : '收缩题目描述'"
        @click="toggleProblemPanel"
      >
        <ChevronLeft v-if="!problemCollapsed" :size="14" />
        <ChevronRight v-else :size="14" />
      </button>
    </aside>

    <!-- 右侧：编辑器 + 底部面板 -->
    <div class="wb-editor-area">
      <!-- 工具栏 -->
      <CodeToolbar
        :languages="experiment?.language_whitelist || languages"
        :selected-language="selectedLanguage"
        :run-state="freeRunState"
        :submit-state="formalState === 'running' ? 'running' : 'idle'"
        :can-run="canRun"
        :can-submit="canSubmit && mode !== 'free'"
        :show-reset="true"
        :show-copy="true"
        @update:selected-language="handleLanguageChange"
        @run="handleFreeRun"
        @submit="handleSubmit"
        @reset="handleReset"
        @copy="handleCopy"
      />

      <!-- 代码编辑器 -->
      <div class="wb-editor-container">
        <CodeEditor
          ref="editorRef"
          v-model="sourceCode"
          :language="selectedLanguage"
          :readonly="freeRunState === 'running' || formalState === 'running'"
          @run-shortcut="handleFreeRun"
        />
      </div>

      <!-- 拖拽分隔条 -->
      <div class="wb-resizer" @mousedown="startResize">
        <GripHorizontal :size="16" />
      </div>

      <!-- 底部 Tab 面板 -->
      <div class="wb-bottom" :style="{ height: bottomPanelHeight + 'px' }">
        <!-- Tab 头部 -->
        <div class="wb-tabs">
          <div class="wb-tabs-left">
            <button
              v-for="tab in visibleTabs"
              :key="tab.key"
              class="wb-tab"
              :class="{ 'is-active': activeTab === tab.key }"
              @click="activeTab = tab.key"
            >
              <component :is="tab.icon" :size="14" />
              <span>{{ tab.label }}</span>
            </button>
          </div>

          <!-- 取消评测按钮 -->
          <div class="wb-tabs-right" v-if="formalState === 'running'">
            <button class="cancel-btn" @click="handleCancelSubmit">
              取消评测
            </button>
          </div>
        </div>

        <!-- Tab 内容 -->
        <div class="wb-tab-content">
          <!-- 自定义输入 -->
          <div v-show="activeTab === 'input'" class="tab-pane">
            <div class="pane-header">
              <span class="pane-title">自定义输入</span>
            </div>
            <textarea
              v-model="stdin"
              class="stdin-textarea"
              placeholder="在此输入测试数据，每行一个输入。使用 Ctrl+Enter 或 Cmd+Enter 快速运行"
              spellcheck="false"
              :disabled="freeRunState === 'running' || formalState === 'running'"
            />
          </div>

          <!-- 输出结果 -->
          <div v-show="activeTab === 'output'" class="tab-pane tab-pane-full">
            <CodeOutput
              :stdout="freeRunStdout"
              :stderr="freeRunStderr"
              :status="outputStatus"
              :execution-time="freeRunTime"
              :memory="freeRunMemory"
              :exit-code="freeRunExitCode"
              title="自由运行结果"
            />
          </div>

          <!-- 测试详情 -->
          <div v-show="activeTab === 'testcases'" class="tab-pane tab-pane-full">
            <CodeTestCases
              :test-cases="formalTestCases"
              :outcome="formalOutcome"
              :status="formalState === 'running' ? 'running' : (formalState === 'done' ? 'done' : 'idle')"
              :progress="formalProgress"
            />
          </div>

          <!-- 诊断讲解 -->
          <div v-show="activeTab === 'diagnosis'" class="tab-pane">
            <div v-if="formalDiagnosis || formalExplanation" class="diagnosis-content">
              <div v-if="formalDiagnosis" class="diag-section">
                <div class="diag-title">
                  <ListChecks :size="16" />
                  <span>规则诊断</span>
                </div>
                <div class="diag-body">
                  <p class="diag-class">
                    <strong>类型：</strong>{{ formalDiagnosis.error_class || formalDiagnosis.outcome || '已完成' }}
                  </p>
                  <p v-if="formalDiagnosis.summary" class="diag-summary">{{ formalDiagnosis.summary }}</p>
                  <ul v-if="formalDiagnosis.debug_steps?.length" class="diag-steps">
                    <li v-for="(step, i) in formalDiagnosis.debug_steps" :key="i">{{ step }}</li>
                  </ul>
                </div>
              </div>
              <div v-if="formalExplanation?.explanation" class="diag-section">
                <div class="diag-title">
                  <Lightbulb :size="16" />
                  <span>AI 讲解</span>
                </div>
                <div class="diag-body">
                  <p>{{ formalExplanation.explanation }}</p>
                  <ul v-if="formalExplanation.next_steps?.length" class="diag-steps">
                    <li v-for="(step, i) in formalExplanation.next_steps" :key="i">{{ step }}</li>
                  </ul>
                </div>
              </div>
            </div>
            <div v-else class="diagnosis-empty">
              <Lightbulb :size="32" :stroke-width="1.5" />
              <p>提交评测后，AI 诊断与讲解将显示在这里</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.code-workbench {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: grid-template-columns var(--duration-normal) var(--ease-out);
}

.code-workbench.is-problem-collapsed {
  grid-template-columns: 56px minmax(0, 1fr);
}

/* 左侧题目描述面板（可收缩，参考 SfxLocalRail 设计模式） */
.wb-problem {
  position: relative;
  grid-column: 1;
  grid-row: 1 / -1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--border-default);
  background: var(--surface-canvas);
  transition: all var(--duration-normal) var(--ease-out);
  /* 不裁剪子元素：切换按钮骑跨面板右边界（right:-13px），overflow:hidden 会裁掉其右半（参考 SfxLocalRail） */
  overflow: visible;
}

.wb-problem.is-collapsed {
  background: var(--surface-soft);
}

/* 收缩态竖排标题条 */
.problem-collapsed-bar {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 16px;
  gap: 12px;
  color: var(--text-secondary);
}

.collapsed-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  color: var(--ink-700);
}

.collapsed-title {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: 2px;
  transform: rotate(180deg);
}

/* 展开态头部 */
.problem-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-panel);
}

.problem-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.problem-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}

.problem-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
}

.problem-content :deep(h1),
.problem-content :deep(h2),
.problem-content :deep(h3) {
  margin-top: 20px;
  margin-bottom: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.problem-content :deep(h1) { font-size: 20px; }
.problem-content :deep(h2) { font-size: 18px; }
.problem-content :deep(h3) { font-size: 16px; }

.problem-content :deep(p) {
  margin: 12px 0;
}

.problem-content :deep(pre) {
  background: var(--code-bg);
  color: var(--code-text);
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  margin: 12px 0;
}

.problem-content :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--surface-soft);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--ink-700);
}

.problem-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}

.problem-content :deep(ul),
.problem-content :deep(ol) {
  margin: 12px 0;
  padding-left: 24px;
}

.problem-content :deep(li) {
  margin: 6px 0;
}

.problem-content :deep(blockquote) {
  margin: 12px 0;
  padding: 8px 16px;
  border-left: 3px solid var(--ink-300);
  background: var(--surface-soft);
  color: var(--text-secondary);
}

.problem-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  gap: 8px;
}

.problem-empty p {
  margin: 0;
  font-size: 14px;
}

/* 收缩/展开切换按钮（参考 SfxLocalRail 的 sfx-rail-toggle） */
.problem-toggle {
  position: absolute;
  top: 16px;
  right: -13px;
  width: 28px;
  height: 40px;
  border-radius: var(--radius-full);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 5;
  transition: all var(--duration-fast) var(--ease-out);
}

.problem-toggle:hover {
  color: var(--ink-700);
  border-color: var(--border-strong);
  background: var(--surface-canvas);
}

.wb-problem.is-collapsed .problem-toggle {
  right: -13px;
}

/* 右侧编辑器区域 */
.wb-editor-area {
  grid-column: 2;
  grid-row: 1 / -1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--code-bg);
  position: relative;
  overflow: hidden;
}

.wb-editor-container {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
}

/* 拖拽分隔条 */
.wb-resizer {
  flex-shrink: 0;
  height: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  background: var(--code-panel);
  color: var(--code-muted);
  border-top: 1px solid var(--code-border);
  border-bottom: 1px solid var(--code-border);
  transition: background var(--duration-fast) var(--ease-out);
}

.wb-resizer:hover {
  background: rgba(53, 92, 125, 0.2);
  color: var(--code-text);
}

/* 底部面板 */
.wb-bottom {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--code-panel);
  overflow: hidden;
}

.wb-tabs {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid var(--code-border);
  padding: 0 8px;
}

.wb-tabs-left {
  display: flex;
  align-items: center;
}

.wb-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--code-muted);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  margin-bottom: -1px;
}

.wb-tab:hover {
  color: var(--code-text);
}

.wb-tab.is-active {
  color: var(--code-text);
  border-bottom-color: var(--ink-500);
}

.wb-tabs-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cancel-btn {
  padding: 4px 10px;
  background: transparent;
  border: 1px solid var(--red-500);
  border-radius: 4px;
  color: var(--red-500);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.cancel-btn:hover {
  background: rgba(184, 92, 92, 0.15);
}

.wb-tab-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.tab-pane {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.tab-pane-full {
  padding: 0;
}

.pane-header {
  flex-shrink: 0;
  padding: 8px 16px;
  border-bottom: 1px solid var(--code-border);
  background: rgba(0, 0, 0, 0.1);
}

.pane-title {
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
  padding: 12px 16px;
  background: transparent;
  border: none;
  color: var(--code-text);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  outline: none;
}

.stdin-textarea::placeholder {
  color: var(--code-muted);
  opacity: 0.5;
}

.stdin-textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 诊断面板 */
.diagnosis-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.diag-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diag-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--code-text);
}

.diag-body {
  padding: 12px;
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--code-text);
}

.diag-class {
  margin: 0 0 8px;
  color: var(--amber-500);
}

.diag-summary {
  margin: 0 0 8px;
}

.diag-steps {
  margin: 8px 0 0;
  padding-left: 20px;
  color: var(--code-text);
}

.diag-steps li {
  margin: 4px 0;
}

.diagnosis-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--code-muted);
  gap: 8px;
}

.diagnosis-empty p {
  margin: 0;
  font-size: 13px;
}

/* 滚动条美化 */
:deep(.cm-scroller::-webkit-scrollbar),
.problem-body::-webkit-scrollbar,
.stdin-textarea::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

:deep(.cm-scroller::-webkit-scrollbar-track),
.problem-body::-webkit-scrollbar-track {
  background: transparent;
}

:deep(.cm-scroller::-webkit-scrollbar-thumb) {
  background: var(--code-border);
  border-radius: 4px;
}

.problem-body::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 4px;
}

:deep(.cm-scroller::-webkit-scrollbar-thumb:hover) {
  background: var(--code-muted);
}

.problem-body::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}
</style>
