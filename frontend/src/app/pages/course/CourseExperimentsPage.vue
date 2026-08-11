<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import {
  createCodingDiagnosis,
  createExperimentAttempt,
  createExperimentRun,
  listPublishedExperiments,
} from '@/api/experiments.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'
import TeacherExperimentPanel from '@/app/components/course/TeacherExperimentPanel.vue'

/**
 * 课程实验任务（page-design §16）。
 *
 * 实验定义 / 尝试 / 评分 Evidence 为 planned 契约（§3.7）；
 * 沙箱运行能力为 available（GET /sandbox/health|languages）——本页真实探测并
 * 展示课程可用的语言与安全边界，不伪造实验任务列表。
 *
 * 学生视图：待完成｜进行中｜已完成（筛选器，非 Local Rail）。
 * 教师视图：任务列表 / 创建任务 / 提交情况（§16.2）。
 */
const courseContext = inject('courseContext')
const counter = useCounterStore()

const isTeacher = computed(() => Boolean(courseContext.allowed.value['course.edit']))

const studentFilter = ref('todo') // todo | doing | done
const teacherTab = ref('list') // list | create | submissions

const sandboxStatus = ref('loading') // loading | ready | error
const sandbox = ref(null)
const languages = ref([])
const experiments = ref([])
const selectedExperiment = ref(null)
const attempt = ref(null)
const sourceCode = ref('')
const selectedLanguage = ref('')
const run = ref(null)
const diagnosis = ref(null)
const codeStatus = ref('idle') // idle | loading | running | done | error
const codeError = ref('')

const codeRunStorageKey = computed(
  () => `teaching-agent-code-run:${courseContext.courseId.value}:${counter.userData?.id ?? 'anonymous'}`,
)

async function loadSandbox() {
  sandboxStatus.value = 'loading'
  try {
    const [health, langs] = await Promise.all([
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
    ])
    sandbox.value = health
    languages.value = Array.isArray(langs?.languages) ? langs.languages : []
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
    codeError.value = error?.message || '实验任务加载失败'
  }
}

async function startAttempt() {
  if (attempt.value || !selectedExperiment.value) return
  const result = await createExperimentAttempt(
    selectedExperiment.value.experiment_id,
    courseContext.courseId.value,
    {},
  )
  attempt.value = result
}

async function runCode() {
  if (!selectedExperiment.value || !sourceCode.value.trim() || codeStatus.value === 'running') return
  codeStatus.value = 'running'
  codeError.value = ''
  diagnosis.value = null
  try {
    await startAttempt()
    if (!attempt.value?.attempt_id) throw new Error('实验尝试创建失败')
    const result = await createExperimentRun(
      attempt.value.attempt_id,
      courseContext.courseId.value,
      { language: selectedLanguage.value, source_code: sourceCode.value },
    )
    run.value = result
    const runId = result?.run_id
    if (runId) {
      window.localStorage.setItem(codeRunStorageKey.value, String(runId))
      const diagnosisResult = await createCodingDiagnosis(courseContext.courseId.value, runId)
      diagnosis.value = diagnosisResult
    }
    codeStatus.value = 'done'
  } catch (error) {
    codeError.value = error?.message || '代码运行失败'
    codeStatus.value = 'error'
  }
}

onMounted(async () => {
  await loadSandbox()
  await loadExperiments()
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">实验任务</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          {{ isTeacher ? '管理课程实验定义、查看提交情况' : '完成课程实验，运行记录会保存为你的学习记录' }}
        </p>
      </div>
      <SfxCapabilityTag level="experimental" />
    </header>

    <!-- 沙箱运行能力（真实探测，available） -->
    <section class="sfx-panel">
      <div class="sfx-exp-sandbox-head">
        <h2 class="sfx-panel-title">代码沙箱</h2>
        <SfxBadge v-if="sandboxStatus === 'ready' && sandbox?.available" tone="green">运行能力可用</SfxBadge>
        <SfxBadge v-else-if="sandboxStatus === 'ready'" tone="amber">当前不可用</SfxBadge>
        <SfxBadge v-else tone="neutral">探测中</SfxBadge>
      </div>
      <template v-if="sandboxStatus === 'ready'">
        <dl class="sfx-desc">
          <dt>支持语言</dt>
          <dd>
            <span v-if="languages.length" class="sfx-exp-langs">
              <SfxBadge v-for="lang in languages" :key="lang" tone="ink">{{ lang }}</SfxBadge>
            </span>
            <span v-else>未获取到语言列表</span>
          </dd>
          <dt>能力边界</dt>
          <dd>目前支持运行代码并查看结果；完整的实验任务流程（含自动评分）将在后续版本提供。</dd>
        </dl>
      </template>
      <p v-else-if="sandboxStatus === 'error'" class="sfx-t-ui sfx-t-secondary">
        沙箱服务暂时不可达，实验运行不可用。这不影响课程其他内容。
      </p>
    </section>

    <TeacherExperimentPanel v-if="isTeacher" />

    <!-- 学生视图 -->
    <template v-if="!isTeacher">
      <div class="sfx-exp-filters" role="tablist" aria-label="实验任务筛选">
        <button
          v-for="opt in [
            { value: 'todo', label: '待完成' },
            { value: 'doing', label: '进行中' },
            { value: 'done', label: '已完成' },
          ]"
          :key="opt.value"
          type="button"
          role="tab"
          :aria-selected="studentFilter === opt.value"
          class="sfx-exp-filter"
          :class="{ 'is-active': studentFilter === opt.value }"
          @click="studentFilter = opt.value"
        >{{ opt.label }}</button>
      </div>

      <section v-if="experiments.length" class="sfx-panel sfx-code-runner">
        <div class="sfx-exp-sandbox-head">
          <div>
            <h2 class="sfx-panel-title">代码实验</h2>
            <p class="sfx-t-ui sfx-t-secondary">提交后代码会在独立环境中运行，并自动给出诊断建议。</p>
          </div>
          <SfxBadge v-if="run?.outcome" tone="ink">{{ run.outcome }}</SfxBadge>
        </div>
        <label class="sfx-code-label">
          实验任务
          <select v-model="selectedExperiment" class="sfx-code-select" @change="attempt = null">
            <option v-for="item in experiments" :key="item.experiment_id" :value="item">{{ item.title }}</option>
          </select>
        </label>
        <label class="sfx-code-label">
          编程语言
          <select v-model="selectedLanguage" class="sfx-code-select">
            <option v-for="lang in (selectedExperiment?.language_whitelist || languages)" :key="lang" :value="lang">{{ lang }}</option>
          </select>
        </label>
        <label class="sfx-code-label">
          代码
          <textarea v-model="sourceCode" class="sfx-code-editor" rows="12" spellcheck="false" placeholder="在这里编写代码…" />
        </label>
        <button class="sfx-code-run" type="button" :disabled="codeStatus === 'running' || !sourceCode.trim() || !selectedExperiment" @click="runCode">
          {{ codeStatus === 'running' ? '运行中…' : '运行代码' }}
        </button>
        <p v-if="codeError" class="sfx-code-error" role="alert">{{ codeError }}</p>
        <div v-if="diagnosis" class="sfx-code-diagnosis">
          <strong>代码诊断：{{ diagnosis.error_class || diagnosis.outcome || '已完成' }}</strong>
          <p v-if="diagnosis.summary">{{ diagnosis.summary }}</p>
          <ul v-if="diagnosis.debug_steps?.length">
            <li v-for="step in diagnosis.debug_steps" :key="step">{{ step }}</li>
          </ul>
          <small>本次运行结果已保存，可在学习页查看诊断建议。</small>
        </div>
      </section>

      <SfxPlannedPanel
        v-if="!experiments.length"
        contract-key="experiments"
        title="课程实验任务 · 即将开放"
        available-note="代码运行环境已在上方展示；实验任务功能将在后续版本提供。"
      >
        <template #icon><FlaskConical :size="20" :stroke-width="1.9" /></template>
        <p class="sfx-t-ui sfx-t-secondary">
          教师发布实验任务后，这里会显示任务名称、关联知识点、截止时间与完成条件；
          完成实验后可查看学习记录与教师反馈。
        </p>
      </SfxPlannedPanel>
    </template>

    <!-- 旧教师占位说明保留为历史参考；真实教师端由 TeacherExperimentPanel 提供。 -->
    <template v-if="false">
      <div class="sfx-exp-filters" role="tablist" aria-label="教师实验工作区">
        <button
          v-for="opt in [
            { value: 'list', label: '任务列表' },
            { value: 'create', label: '创建任务' },
            { value: 'submissions', label: '提交情况' },
          ]"
          :key="opt.value"
          type="button"
          role="tab"
          :aria-selected="teacherTab === opt.value"
          class="sfx-exp-filter"
          :class="{ 'is-active': teacherTab === opt.value }"
          @click="teacherTab = opt.value"
        >{{ opt.label }}</button>
      </div>

      <SfxPlannedPanel
        v-if="teacherTab === 'list'"
        contract-key="experiments"
        title="实验任务列表 · 即将开放"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          列表将包含：任务名、关联知识点、状态、截止时间、提交人数、异常数与安全策略。
        </p>
      </SfxPlannedPanel>

      <SfxPlannedPanel
        v-else-if="teacherTab === 'create'"
        contract-key="experiments"
        title="创建实验任务 · 即将开放"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          创建流程分为：基本信息 → 实验内容 → 评测与提示 → 安全策略 → 预览发布。
          代码运行环境与支持的语言可在「设置 → 代码运行」中配置。
        </p>
      </SfxPlannedPanel>

      <SfxPlannedPanel
        v-else
        contract-key="experiments"
        title="提交情况 · 即将开放"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          教师只能查看本课程任务范围内的学生提交，不会看到学生在其他自主实验中的内容。
        </p>
      </SfxPlannedPanel>
    </template>
  </div>
</template>

<style scoped>
.sfx-exp-sandbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sfx-exp-langs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-exp-filters {
  display: inline-flex;
  gap: var(--space-1);
  background: var(--surface-soft);
  border-radius: var(--radius-md);
  padding: 3px;
  align-self: flex-start;
  margin: var(--space-2) 0 var(--space-2);
}

.sfx-exp-filter {
  height: 30px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
}

.sfx-exp-filter:hover { color: var(--ink-700); }
.sfx-exp-filter.is-active { background: var(--surface-panel); color: var(--ink-900); box-shadow: var(--shadow-xs); }

.sfx-code-runner { display: flex; flex-direction: column; gap: var(--space-3); }
.sfx-code-label { display: flex; flex-direction: column; gap: var(--space-1); color: var(--text-secondary); font-size: var(--ui-sm-size); }
.sfx-code-select, .sfx-code-editor {
  width: 100%;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  color: var(--ink-900);
  padding: var(--space-2) var(--space-3);
}
.sfx-code-editor { min-height: 180px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.5; }
.sfx-code-run { align-self: flex-start; padding: var(--space-2) var(--space-4); border-radius: var(--radius-sm); background: var(--ink-900); color: white; font-weight: 600; }
.sfx-code-run:disabled { cursor: not-allowed; opacity: .55; }
.sfx-code-error { color: var(--danger-700, #b42318); }
.sfx-code-diagnosis { padding: var(--space-3); border-radius: var(--radius-sm); background: var(--surface-soft); color: var(--ink-800); }
.sfx-code-diagnosis p { margin: var(--space-2) 0; }
.sfx-code-diagnosis ul { margin: 0; padding-left: 1.25rem; }
</style>
