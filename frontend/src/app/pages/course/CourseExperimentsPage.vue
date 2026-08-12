<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import {
  createExperimentAttempt,
  createExperimentRun,
  cancelTask,
  getCodingFeedback,
  getExperimentAttempt,
  getExperimentRun,
  getTask,
  listPublishedExperiments,
} from '@/api/experiments.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import TeacherExperimentPanel from '@/app/components/course/TeacherExperimentPanel.vue'

const courseContext = inject('courseContext')
const isTeacher = computed(() => Boolean(courseContext.allowed.value['course.edit']))
const courseId = computed(() => courseContext.courseId.value)
const sandbox = ref(null)
const languages = ref([])
const experiments = ref([])
const selectedExperiment = ref(null)
const selectedLanguage = ref('')
const sourceCode = ref('')
const attempt = ref(null)
const run = ref(null)
const task = ref(null)
const feedback = ref(null)
const state = ref('idle') // idle | submitting | queued | evaluating | terminal | error
const error = ref('')
let pollTimer

const terminal = computed(() => ['accepted', 'wrong_answer', 'time_limit_exceeded', 'memory_limit_exceeded', 'runtime_error', 'compilation_error', 'internal_error'].includes(run.value?.outcome))

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
}

async function load() {
  const [health, langs, definitions] = await Promise.all([
    getSandboxHealth().catch(() => null),
    getSandboxLanguages().catch(() => null),
    isTeacher.value ? Promise.resolve({ items: [] }) : listPublishedExperiments(courseId.value).catch(() => ({ items: [] })),
  ])
  sandbox.value = health
  languages.value = langs?.languages || []
  experiments.value = definitions?.items || []
  selectedExperiment.value = experiments.value[0] || null
  selectedLanguage.value = selectedExperiment.value?.language_whitelist?.[0] || languages.value[0] || ''
}

async function refreshProgress() {
  if (!run.value?.run_id) return
  try {
    if (run.value.task_id) task.value = await getTask(run.value.task_id)
    run.value = await getExperimentRun(courseId.value, run.value.run_id)
    if (terminal.value) {
      stopPolling()
      state.value = 'terminal'
      feedback.value = await getCodingFeedback(courseId.value, run.value.run_id).catch(() => null)
      if (attempt.value?.attempt_id) attempt.value = await getExperimentAttempt(courseId.value, attempt.value.attempt_id)
    } else {
      state.value = 'evaluating'
    }
  } catch (reason) {
    error.value = reason?.message || '无法刷新评测进度'
    state.value = 'error'
    stopPolling()
  }
}

async function submit() {
  if (!selectedExperiment.value || !sourceCode.value.trim() || state.value === 'submitting') return
  state.value = 'submitting'
  error.value = ''
  feedback.value = null
  try {
    if (!attempt.value) {
      attempt.value = await createExperimentAttempt(selectedExperiment.value.experiment_id, courseId.value)
    }
    const key = globalThis.crypto?.randomUUID?.() || `attempt-${Date.now()}`
    const result = await createExperimentRun(
      attempt.value.attempt_id,
      courseId.value,
      { language: selectedLanguage.value, source_code: sourceCode.value },
      key,
    )
    run.value = { run_id: result.run_id, task_id: result.task_id, outcome: result.status }
    state.value = 'queued'
    await refreshProgress()
    if (!terminal.value) pollTimer = window.setInterval(refreshProgress, 1800)
  } catch (reason) {
    const detail = reason?.response?.data?.detail || reason?.detail
    error.value = detail?.message || reason?.message || '提交评测失败'
    state.value = 'error'
  }
}

async function cancelEvaluation() {
  if (!run.value?.task_id) return
  try {
    await cancelTask(run.value.task_id)
    state.value = 'idle'
    stopPolling()
    error.value = ''
  } catch (reason) { error.value = reason?.message || '取消评测失败' }
}

function selectExperiment(item) {
  selectedExperiment.value = item
  selectedLanguage.value = item?.language_whitelist?.[0] || ''
  attempt.value = null
  run.value = null
  feedback.value = null
  state.value = 'idle'
  stopPolling()
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">实验任务</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          {{ isTeacher ? '编辑、验证并发布课程编程实验。' : '提交后进入可信异步评测；自由运行不计入成绩。' }}
        </p>
      </div>
      <SfxCapabilityTag level="experimental" />
    </header>

    <section class="sfx-panel">
      <div class="sfx-exp-head">
        <h2 class="sfx-panel-title">正式评测沙箱</h2>
        <SfxBadge :tone="sandbox?.available ? 'green' : 'amber'">{{ sandbox?.available ? '可用' : '待验证' }}</SfxBadge>
      </div>
      <p class="sfx-t-ui sfx-t-secondary">正式提交在独立 Judge0 中异步完成。课程关闭实验能力时，读取、推荐和执行都会被拒绝。</p>
      <div class="sfx-exp-langs"><SfxBadge v-for="language in languages" :key="language" tone="ink">{{ language }}</SfxBadge></div>
    </section>

    <TeacherExperimentPanel v-if="isTeacher" />

    <section v-else-if="experiments.length" class="sfx-panel sfx-code-runner">
      <div class="sfx-exp-head">
        <div><h2 class="sfx-panel-title">正式提交</h2><p class="sfx-t-ui sfx-t-secondary">ACM/ICPC：全部测试通过才计为完成。</p></div>
        <SfxBadge v-if="run" :tone="terminal ? (run.outcome === 'accepted' ? 'green' : 'amber') : 'ink'">{{ run.outcome }}</SfxBadge>
      </div>
      <label class="sfx-code-label">实验任务
        <select class="sfx-code-select" :value="selectedExperiment" @change="selectExperiment(experiments.find((item) => item.experiment_id === $event.target.value))">
          <option v-for="item in experiments" :key="item.experiment_id" :value="item.experiment_id">{{ item.title }}</option>
        </select>
      </label>
      <label class="sfx-code-label">语言
        <select v-model="selectedLanguage" class="sfx-code-select"><option v-for="language in (selectedExperiment?.language_whitelist || [])" :key="language" :value="language">{{ language }}</option></select>
      </label>
      <label class="sfx-code-label">代码
        <textarea v-model="sourceCode" class="sfx-code-editor" rows="12" spellcheck="false" placeholder="在这里编写代码…" />
      </label>
      <SfxButton variant="primary" :loading="state === 'submitting'" :disabled="!sourceCode.trim() || !selectedLanguage || ['queued', 'evaluating'].includes(state)" @click="submit">
        {{ ['queued', 'evaluating'].includes(state) ? '评测中…' : '提交正式评测' }}
      </SfxButton>
      <SfxButton v-if="['queued', 'evaluating'].includes(state)" variant="secondary" size="sm" @click="cancelEvaluation">取消本次评测</SfxButton>
      <p v-if="task?.status && !terminal" class="sfx-t-ui sfx-t-secondary">任务中心状态：{{ task.status }}，正在轮询结果。</p>
      <p v-if="error" class="sfx-code-error" role="alert">{{ error }}</p>
      <section v-if="feedback" class="sfx-code-diagnosis" aria-live="polite">
        <strong>本次运行讲解</strong>
        <p>{{ feedback.summary }}</p>
        <p class="sfx-t-caption">通过 {{ feedback.result?.passed_count }}/{{ feedback.result?.total_count }} · {{ feedback.result?.outcome }}</p>
        <ol><li v-for="step in feedback.next_steps" :key="step">{{ step }}</li></ol>
      </section>
      <p v-if="attempt?.status === 'finalized' || attempt?.status === 'failed'" class="sfx-t-caption">尝试已由服务端终结，并投影到可信实验记录。</p>
    </section>
    <section v-else class="sfx-panel sfx-empty-state"><FlaskConical :size="22" /><p>教师发布并完成参考解验证后，课程实验会显示在这里。</p></section>
  </div>
</template>

<style scoped>
.sfx-exp-head { display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); }
.sfx-exp-langs { display:flex; flex-wrap:wrap; gap:var(--space-2); margin-top:var(--space-3); }
.sfx-code-runner { display:flex; flex-direction:column; gap:var(--space-3); }
.sfx-code-label { display:flex; flex-direction:column; gap:var(--space-1); color:var(--text-secondary); font-size:var(--ui-sm-size); }
.sfx-code-select,.sfx-code-editor { width:100%; border:1px solid var(--border-subtle); border-radius:var(--radius-sm); background:var(--surface-panel); color:var(--ink-900); padding:var(--space-2) var(--space-3); }
.sfx-code-editor { min-height:180px; resize:vertical; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; line-height:1.5; }
.sfx-code-error { color:var(--danger-700,#b42318); }
.sfx-code-diagnosis { padding:var(--space-3); border-radius:var(--radius-sm); background:var(--surface-soft); color:var(--ink-800); }
.sfx-code-diagnosis p { margin:var(--space-2) 0; }.sfx-code-diagnosis ol { margin:0; padding-left:1.25rem; }.sfx-empty-state { display:flex; gap:var(--space-2); align-items:center; }
</style>
