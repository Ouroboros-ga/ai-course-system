<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import {
  cancelExperimentRun,
  createCodingDiagnosis,
  createExperimentAttempt,
  createExperimentRun,
  getCodingRunExplanation,
  getExperimentRun,
  listPublishedExperiments,
} from '@/api/experiments.js'
import { isTerminalTaskStatus, shouldOfferFormalRunRetry } from '@/api/experimentRunContract.js'
import { getTask, retryTask } from '@/api/tasks.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import TeacherExperimentPanel from '@/app/components/course/TeacherExperimentPanel.vue'

const courseContext = inject('courseContext')
const counter = useCounterStore()
const isTeacher = computed(() => Boolean(courseContext.allowed.value['course.edit']))
const sandboxStatus = ref('loading')
const sandbox = ref(null)
const languages = ref([])
const experiments = ref([])
const selectedExperiment = ref(null)
const attempt = ref(null)
const sourceCode = ref('')
const selectedLanguage = ref('')
const run = ref(null)
const task = ref(null)
const diagnosis = ref(null)
const explanation = ref(null)
const codeStatus = ref('idle')
const codeError = ref('')
const codeRunStorageKey = computed(
  () => `teaching-agent-code-run:${courseContext.courseId.value}:${counter.userData?.id ?? 'anonymous'}`,
)

let pollGeneration = 0

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `experiment-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function isBusy() {
  return ['submitting', 'queued', 'running', 'cancelling'].includes(codeStatus.value)
}

function waitForPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, 1000))
}

async function loadSandbox() {
  sandboxStatus.value = 'loading'
  try {
    const [health, supported] = await Promise.all([
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
    ])
    sandbox.value = health
    languages.value = Array.isArray(supported?.languages) ? supported.languages : []
    sandboxStatus.value = 'ready'
  } catch {
    sandboxStatus.value = 'error'
  }
}

async function loadExperiments() {
  if (isTeacher.value) return
  try {
    const result = await listPublishedExperiments(courseContext.courseId.value)
    experiments.value = result?.items ?? []
    selectedExperiment.value = experiments.value[0] ?? null
    selectedLanguage.value = selectedExperiment.value?.language_whitelist?.[0] ?? languages.value[0] ?? ''
  } catch (error) {
    codeError.value = error?.message || 'Unable to load course experiments.'
  }
}

async function createAttempt() {
  const result = await createExperimentAttempt(
    selectedExperiment.value.experiment_id,
    courseContext.courseId.value,
    {},
  )
  attempt.value = result
  return result
}

async function loadTerminalRun(runId) {
  run.value = await getExperimentRun(courseContext.courseId.value, runId)
  if (run.value?.outcome === 'cancelled') {
    codeStatus.value = 'cancelled'
    return
  }
  if (run.value?.outcome === 'sandbox_unavailable') {
    codeStatus.value = 'retryable'
    return
  }
  diagnosis.value = await createCodingDiagnosis(courseContext.courseId.value, runId)
  explanation.value = await getCodingRunExplanation(courseContext.courseId.value, runId)
  codeStatus.value = 'done'
}

async function pollFormalRun(taskId, runId, generation) {
  while (generation === pollGeneration) {
    const nextTask = await getTask(taskId)
    task.value = nextTask
    if (isTerminalTaskStatus(nextTask?.status)) {
      await loadTerminalRun(runId)
      return
    }
    codeStatus.value = 'running'
    await waitForPoll()
  }
}

async function retryFormalRun() {
  if (!task.value?.task_id || !run.value?.run_id || !shouldOfferFormalRunRetry(task.value, run.value)) return
  codeStatus.value = 'queued'
  codeError.value = ''
  try {
    task.value = await retryTask(task.value.task_id)
    const generation = ++pollGeneration
    await pollFormalRun(task.value.task_id, run.value.run_id, generation)
  } catch (error) {
    codeError.value = error?.message || 'Unable to retry the assessment.'
    codeStatus.value = 'error'
  }
}

async function runCode() {
  if (!selectedExperiment.value || !sourceCode.value.trim() || isBusy()) return
  codeStatus.value = 'submitting'
  codeError.value = ''
  diagnosis.value = null
  explanation.value = null
  task.value = null
  run.value = null
  try {
    const currentAttempt = await createAttempt()
    if (!currentAttempt?.attempt_id) throw new Error('Unable to create a formal experiment attempt.')
    const createdRun = await createExperimentRun(
      currentAttempt.attempt_id,
      courseContext.courseId.value,
      { language: selectedLanguage.value, source_code: sourceCode.value },
      newIdempotencyKey(),
    )
    if (!createdRun?.run_id || !createdRun?.task_id) throw new Error('Unable to queue the formal assessment.')
    run.value = createdRun
    window.localStorage.setItem(codeRunStorageKey.value, String(createdRun.run_id))
    codeStatus.value = 'queued'
    const generation = ++pollGeneration
    await pollFormalRun(createdRun.task_id, createdRun.run_id, generation)
  } catch (error) {
    codeError.value = error?.message || 'Code assessment failed.'
    codeStatus.value = 'error'
  }
}

async function cancelRun() {
  if (!run.value?.run_id || !['queued', 'running'].includes(codeStatus.value)) return
  codeStatus.value = 'cancelling'
  codeError.value = ''
  try {
    run.value = await cancelExperimentRun(courseContext.courseId.value, run.value.run_id)
    pollGeneration += 1
    codeStatus.value = 'cancelled'
  } catch (error) {
    codeError.value = error?.message || 'Unable to cancel the assessment.'
    codeStatus.value = 'error'
  }
}

function changeExperiment() {
  attempt.value = null
  run.value = null
  task.value = null
  diagnosis.value = null
  explanation.value = null
  codeStatus.value = 'idle'
  selectedLanguage.value = selectedExperiment.value?.language_whitelist?.[0] ?? languages.value[0] ?? ''
}

onMounted(async () => {
  await loadSandbox()
  await loadExperiments()
})

onBeforeUnmount(() => {
  pollGeneration += 1
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程实验</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          {{ isTeacher ? '创建、验证并发布可信编程实验。' : '提交后由服务端异步评测，只有终结结果会写入实验记录。' }}
        </p>
      </div>
      <SfxCapabilityTag level="experimental" />
    </header>

    <section class="sfx-panel">
      <div class="sfx-exp-sandbox-head">
        <h2 class="sfx-panel-title">代码沙箱</h2>
        <SfxBadge v-if="sandboxStatus === 'ready' && sandbox?.available" tone="green">可用</SfxBadge>
        <SfxBadge v-else-if="sandboxStatus === 'ready'" tone="amber">暂不可用</SfxBadge>
        <SfxBadge v-else tone="neutral">检测中</SfxBadge>
      </div>
      <p v-if="sandboxStatus === 'ready'" class="sfx-t-ui sfx-t-secondary">
        支持语言：{{ languages.length ? languages.join(' / ') : '暂未获取' }}。自由运行与正式成绩相互隔离。
      </p>
      <p v-else-if="sandboxStatus === 'error'" class="sfx-t-ui sfx-t-secondary">沙箱服务暂时不可达，正式评测无法提交。</p>
    </section>

    <TeacherExperimentPanel v-if="isTeacher" />

    <section v-else-if="experiments.length" class="sfx-panel sfx-code-runner">
      <div class="sfx-exp-sandbox-head">
        <div>
          <h2 class="sfx-panel-title">正式编程评测</h2>
          <p class="sfx-t-ui sfx-t-secondary">采用 ACM/ICPC 规则：全部测试通过才获得通过记录。</p>
        </div>
        <SfxBadge v-if="run?.outcome" tone="ink">{{ run.outcome }}</SfxBadge>
      </div>

      <label class="sfx-code-label">
        实验任务
        <select v-model="selectedExperiment" class="sfx-code-select" :disabled="isBusy()" @change="changeExperiment">
          <option v-for="item in experiments" :key="item.experiment_id" :value="item">{{ item.title }}</option>
        </select>
      </label>
      <label class="sfx-code-label">
        编程语言
        <select v-model="selectedLanguage" class="sfx-code-select" :disabled="isBusy()">
          <option v-for="language in (selectedExperiment?.language_whitelist || languages)" :key="language" :value="language">{{ language }}</option>
        </select>
      </label>
      <label class="sfx-code-label">
        源码
        <textarea v-model="sourceCode" class="sfx-code-editor" rows="12" spellcheck="false" :disabled="isBusy()" placeholder="在这里编写代码" />
      </label>

      <div class="sfx-code-actions">
        <SfxButton variant="primary" :disabled="isBusy() || !sourceCode.trim() || !selectedExperiment" @click="runCode">
          {{ isBusy() ? '评测中…' : '提交正式评测' }}
        </SfxButton>
        <SfxButton v-if="['queued', 'running'].includes(codeStatus)" variant="secondary" :loading="codeStatus === 'cancelling'" @click="cancelRun">
          取消评测
        </SfxButton>
        <SfxButton v-if="shouldOfferFormalRunRetry(task, run)" variant="secondary" @click="retryFormalRun">
          重试评测
        </SfxButton>
      </div>

      <p v-if="task" class="sfx-t-caption sfx-t-secondary">任务 {{ task.task_id }}：{{ task.status }} · {{ task.progress }}%</p>
      <p v-if="codeStatus === 'cancelled'" class="sfx-t-ui sfx-t-secondary">本次评测已取消，未生成正式成绩或实验记录。</p>
      <p v-else-if="codeStatus === 'retryable'" class="sfx-t-ui sfx-t-secondary">评测机暂不可用；本次提交尚未形成成绩，可在恢复后重试。</p>
      <p v-if="codeError" class="sfx-code-error" role="alert">{{ codeError }}</p>

      <div v-if="diagnosis" class="sfx-code-diagnosis">
        <strong>规则诊断：{{ diagnosis.error_class || diagnosis.outcome || '已完成' }}</strong>
        <p v-if="diagnosis.summary">{{ diagnosis.summary }}</p>
        <ul v-if="diagnosis.debug_steps?.length">
          <li v-for="step in diagnosis.debug_steps" :key="step">{{ step }}</li>
        </ul>
      </div>
      <div v-if="explanation?.explanation" class="sfx-code-diagnosis">
        <strong>本次运行讲解</strong>
        <p>{{ explanation.explanation }}</p>
        <ul v-if="explanation.next_steps?.length">
          <li v-for="step in explanation.next_steps" :key="step">{{ step }}</li>
        </ul>
      </div>
    </section>

    <SfxEmpty v-else-if="!isTeacher" title="暂无已发布实验" description="教师完成版本、测试、参考解预览和锁定后，实验会显示在这里。">
      <template #icon><FlaskConical :size="20" :stroke-width="1.9" /></template>
    </SfxEmpty>
  </div>
</template>

<style scoped>
.sfx-exp-sandbox-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.sfx-code-runner { display: flex; flex-direction: column; gap: var(--space-3); }
.sfx-code-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.sfx-code-label { display: flex; flex-direction: column; gap: var(--space-1); color: var(--text-secondary); font-size: var(--ui-sm-size); }
.sfx-code-select, .sfx-code-editor { width: 100%; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--surface-panel); color: var(--ink-900); padding: var(--space-2) var(--space-3); }
.sfx-code-editor { min-height: 180px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.5; background: var(--ink-900); color: var(--surface-panel); }
.sfx-code-error { color: var(--red-700); }
.sfx-code-diagnosis { padding: var(--space-3); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--surface-soft); color: var(--ink-800); }
.sfx-code-diagnosis p { margin: var(--space-2) 0; }
.sfx-code-diagnosis ul { margin: 0; padding-left: 1.25rem; }
</style>
