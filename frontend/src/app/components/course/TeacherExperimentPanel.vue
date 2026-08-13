<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import {
  createExperimentDefinition,
  createExperimentVersion,
  listExperimentDefinitions,
  lockExperimentVersion,
  previewExperimentReferenceSolution,
  publishExperimentDefinition,
  updateExperimentDefinition,
} from '@/api/experiments.js'
import { resolveExperimentWizardStage } from '@/api/experimentPublishWorkflow.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)

const stageOrder = ['definition', 'limits', 'version', 'preview', 'lock', 'publish']
const stageLabels = {
  definition: '任务定义',
  limits: '语言与资源',
  version: '版本与测试',
  preview: '参考解预览',
  lock: '锁定版本',
  publish: '发布',
  complete: '已发布',
}

const state = ref('loading')
const items = ref([])
const saving = ref(false)
const error = ref('')
const selectedDefinition = ref(null)
const selectedVersionId = ref('')
const stage = ref('definition')
const preview = ref(null)

const definitionForm = ref({
  title: '',
  description: '',
  languages: 'python3',
  max_attempts: 3,
  cooldown_minutes: 30,
})
const versionForm = ref({
  label: 'v1',
  cpuTimeLimit: 5,
  memoryLimit: 128000,
  wallTimeLimit: 10,
  maxProcesses: 30,
  maxFileSize: 1024,
  testCases: [
    { case_name: '公开样例', stdin: '', expected_stdout: '', is_hidden: false, weight: 0.5 },
    { case_name: '边界用例', stdin: '', expected_stdout: '', is_hidden: true, weight: 0.5 },
  ],
})
const referenceForm = ref({ language: 'python3', source_code: '' })

const selectedLanguages = computed(() => definitionForm.value.languages
  .split(',')
  .map((language) => language.trim())
  .filter(Boolean))
const testWeight = computed(() => versionForm.value.testCases
  .reduce((total, testCase) => total + Number(testCase.weight || 0), 0))
const canLock = computed(() => preview.value?.accepted === true && Boolean(selectedVersionId.value))
const canPublish = computed(() => Boolean(selectedDefinition.value && selectedVersionId.value))
const currentStageIndex = computed(() => stageOrder.indexOf(stage.value))

function resetWizard() {
  selectedDefinition.value = null
  selectedVersionId.value = ''
  stage.value = 'definition'
  preview.value = null
  definitionForm.value = {
    title: '', description: '', languages: 'python3', max_attempts: 3, cooldown_minutes: 30,
  }
  versionForm.value = {
    label: 'v1', cpuTimeLimit: 5, memoryLimit: 128000, wallTimeLimit: 10, maxProcesses: 30, maxFileSize: 1024,
    testCases: [
      { case_name: '公开样例', stdin: '', expected_stdout: '', is_hidden: false, weight: 0.5 },
      { case_name: '边界用例', stdin: '', expected_stdout: '', is_hidden: true, weight: 0.5 },
    ],
  }
  referenceForm.value = { language: 'python3', source_code: '' }
}

function unwrap(response) {
  return response?.data ?? response
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const data = unwrap(await listExperimentDefinitions(courseId.value))
    items.value = data?.items ?? []
    state.value = items.value.length ? 'ready' : 'empty'
  } catch (requestError) {
    error.value = requestError?.message || '实验任务读取失败'
    state.value = 'error'
  }
}

async function createDefinition() {
  if (!definitionForm.value.title.trim()) return
  saving.value = true
  error.value = ''
  try {
    const definition = unwrap(await createExperimentDefinition(courseId.value, {
      title: definitionForm.value.title.trim(),
      description: definitionForm.value.description.trim(),
      language_whitelist: selectedLanguages.value,
      max_attempts: Number(definitionForm.value.max_attempts),
      cooldown_minutes: Number(definitionForm.value.cooldown_minutes),
    }))
    selectedDefinition.value = definition
    referenceForm.value.language = selectedLanguages.value[0] || 'python3'
    stage.value = 'limits'
    await load()
  } catch (requestError) {
    error.value = requestError?.message || '创建实验草稿失败'
  } finally {
    saving.value = false
  }
}

async function saveLimits() {
  if (!selectedDefinition.value || !selectedLanguages.value.length) return
  saving.value = true
  error.value = ''
  try {
    const definition = unwrap(await updateExperimentDefinition(
      courseId.value,
      selectedDefinition.value.experiment_id,
      {
        title: definitionForm.value.title.trim(),
        description: definitionForm.value.description.trim(),
        language_whitelist: selectedLanguages.value,
        max_attempts: Number(definitionForm.value.max_attempts),
        cooldown_minutes: Number(definitionForm.value.cooldown_minutes),
      },
    ))
    selectedDefinition.value = definition
    referenceForm.value.language = selectedLanguages.value[0]
    stage.value = 'version'
    await load()
  } catch (requestError) {
    error.value = requestError?.message || '保存语言与资源限制失败'
  } finally {
    saving.value = false
  }
}

function addTestCase(isHidden) {
  versionForm.value.testCases.push({
    case_name: isHidden ? '隐藏用例' : '公开样例',
    stdin: '',
    expected_stdout: '',
    is_hidden: isHidden,
    weight: 0,
  })
}

function removeTestCase(index) {
  if (versionForm.value.testCases.length <= 1) return
  versionForm.value.testCases.splice(index, 1)
}

async function createVersion() {
  if (!selectedDefinition.value || Math.abs(testWeight.value - 1) > 0.000001) return
  saving.value = true
  error.value = ''
  try {
    const version = unwrap(await createExperimentVersion(
      courseId.value,
      selectedDefinition.value.experiment_id,
      versionForm.value,
    ))
    selectedVersionId.value = version.version_id
    stage.value = 'preview'
    await load()
  } catch (requestError) {
    error.value = requestError?.message || '创建实验版本失败'
  } finally {
    saving.value = false
  }
}

async function runReferencePreview() {
  if (!selectedVersionId.value || !referenceForm.value.source_code.trim()) return
  saving.value = true
  error.value = ''
  try {
    preview.value = unwrap(await previewExperimentReferenceSolution(
      courseId.value,
      selectedVersionId.value,
      {
        language: referenceForm.value.language,
        source_code: referenceForm.value.source_code,
      },
    ))
  } catch (requestError) {
    error.value = requestError?.message || '参考解预览失败'
  } finally {
    saving.value = false
  }
}

async function lockVersion() {
  if (!canLock.value) return
  saving.value = true
  error.value = ''
  try {
    await lockExperimentVersion(courseId.value, selectedVersionId.value)
    stage.value = 'publish'
    await load()
  } catch (requestError) {
    error.value = requestError?.message || '锁定实验版本失败'
  } finally {
    saving.value = false
  }
}

async function publish() {
  if (!canPublish.value) return
  saving.value = true
  error.value = ''
  try {
    const definition = unwrap(await publishExperimentDefinition(
      courseId.value,
      selectedDefinition.value.experiment_id,
    ))
    selectedDefinition.value = definition
    stage.value = 'complete'
    await load()
  } catch (requestError) {
    error.value = requestError?.message || '发布实验失败。请检查参考解预览、锁定状态和课程沙箱能力。'
  } finally {
    saving.value = false
  }
}

function continueDraft(item) {
  selectedDefinition.value = item
  selectedVersionId.value = item.default_version_id || ''
  definitionForm.value = {
    title: item.title || '',
    description: item.description || '',
    languages: (item.language_whitelist || []).join(', '),
    max_attempts: item.max_attempts || 3,
    cooldown_minutes: item.cooldown_minutes || 0,
  }
  referenceForm.value = {
    language: item.language_whitelist?.[0] || 'python3',
    source_code: '',
  }
  preview.value = null
  stage.value = resolveExperimentWizardStage(item)
}

function startNewDraft() {
  resetWizard()
}

onMounted(load)
</script>

<template>
  <section class="sfx-teacher-experiments">
    <header class="sfx-experiment-header">
      <div>
        <h2 class="sfx-panel-title">教师实验任务</h2>
        <p class="sfx-t-ui sfx-t-secondary">按版本固化题目与测试。正式成绩采用 ACM/ICPC 全量通过规则。</p>
      </div>
      <SfxButton v-if="selectedDefinition" variant="secondary" @click="startNewDraft">新建草稿</SfxButton>
    </header>

    <ol class="sfx-experiment-steps" aria-label="实验发布流程">
      <li v-for="step in stageOrder" :key="step" :class="{ active: stage === step, complete: currentStageIndex > stageOrder.indexOf(step) || stage === 'complete' }">
        {{ stageLabels[step] }}
      </li>
    </ol>

    <SfxError v-if="error" :description="error" @retry="load" />

    <form v-if="stage === 'definition'" class="sfx-panel sfx-wizard-form" @submit.prevent="createDefinition">
      <h3 class="sfx-panel-subtitle">任务定义</h3>
      <label>任务名称<input v-model.trim="definitionForm.title" class="sfx-input" required maxlength="200" /></label>
      <label>任务说明<textarea v-model.trim="definitionForm.description" class="sfx-input" rows="4" maxlength="4000" /></label>
      <label>最大尝试次数<input v-model.number="definitionForm.max_attempts" class="sfx-input" type="number" min="1" max="20" /></label>
      <label>冷却时间（分钟）<input v-model.number="definitionForm.cooldown_minutes" class="sfx-input" type="number" min="0" max="1440" /></label>
      <SfxButton type="submit" :loading="saving">创建任务定义</SfxButton>
    </form>

    <form v-else-if="stage === 'limits'" class="sfx-panel sfx-wizard-form" @submit.prevent="saveLimits">
      <h3 class="sfx-panel-subtitle">语言与资源</h3>
      <label>允许语言<input v-model="definitionForm.languages" class="sfx-input" placeholder="python3, cpp" /></label>
      <p class="sfx-t-caption">仅允许课程已启用并可由评测机执行的语言。</p>
      <label>最大尝试次数<input v-model.number="definitionForm.max_attempts" class="sfx-input" type="number" min="1" max="20" /></label>
      <label>冷却时间（分钟）<input v-model.number="definitionForm.cooldown_minutes" class="sfx-input" type="number" min="0" max="1440" /></label>
      <div class="sfx-wizard-actions">
        <SfxButton variant="secondary" @click="stage = 'definition'">返回定义</SfxButton>
        <SfxButton type="submit" :disabled="!selectedLanguages.length" :loading="saving">保存并配置版本</SfxButton>
      </div>
    </form>

    <section v-else-if="stage === 'version'" class="sfx-panel sfx-wizard-form">
      <h3 class="sfx-panel-subtitle">版本与测试</h3>
      <p class="sfx-t-caption">权重用于完整性校验，正式结果仍是全量通过或未通过。</p>
      <div class="sfx-limit-grid">
        <label>版本标签<input v-model.trim="versionForm.label" class="sfx-input" maxlength="100" /></label>
        <label>CPU 秒数<input v-model.number="versionForm.cpuTimeLimit" class="sfx-input" type="number" min="1" max="30" /></label>
        <label>内存 KB<input v-model.number="versionForm.memoryLimit" class="sfx-input" type="number" min="16000" max="512000" /></label>
        <label>墙钟秒数<input v-model.number="versionForm.wallTimeLimit" class="sfx-input" type="number" min="1" max="60" /></label>
        <label>最大进程数<input v-model.number="versionForm.maxProcesses" class="sfx-input" type="number" min="1" max="120" /></label>
        <label>最大文件 KB<input v-model.number="versionForm.maxFileSize" class="sfx-input" type="number" min="1" max="8192" /></label>
      </div>
      <article v-for="(testCase, index) in versionForm.testCases" :key="`${index}-${testCase.is_hidden}`" class="sfx-test-case">
        <header>
          <strong>测试 {{ index + 1 }}</strong>
          <SfxBadge :tone="testCase.is_hidden ? 'amber' : 'ink'">{{ testCase.is_hidden ? '隐藏' : '公开' }}</SfxBadge>
          <SfxButton variant="tertiary" size="sm" :disabled="versionForm.testCases.length === 1" @click="removeTestCase(index)">移除</SfxButton>
        </header>
        <label>名称<input v-model.trim="testCase.case_name" class="sfx-input" maxlength="200" /></label>
        <label>标准输入<textarea v-model="testCase.stdin" class="sfx-input sfx-code-input" rows="3" /></label>
        <label>期望输出<textarea v-model="testCase.expected_stdout" class="sfx-input sfx-code-input" rows="3" /></label>
        <label>权重<input v-model.number="testCase.weight" class="sfx-input" type="number" min="0" max="1" step="0.01" /></label>
      </article>
      <div class="sfx-wizard-actions">
        <SfxButton variant="secondary" @click="addTestCase(false)">增加公开测试</SfxButton>
        <SfxButton variant="secondary" @click="addTestCase(true)">增加隐藏测试</SfxButton>
        <SfxBadge :tone="Math.abs(testWeight - 1) < 0.000001 ? 'green' : 'red'">权重 {{ testWeight.toFixed(2) }} / 1.00</SfxBadge>
      </div>
      <div class="sfx-wizard-actions">
        <SfxButton variant="secondary" @click="stage = 'limits'">返回资源</SfxButton>
        <SfxButton :disabled="Math.abs(testWeight - 1) >= 0.000001" :loading="saving" @click="createVersion">创建不可变版本</SfxButton>
      </div>
    </section>

    <form v-else-if="stage === 'preview'" class="sfx-panel sfx-wizard-form" @submit.prevent="runReferencePreview">
      <h3 class="sfx-panel-subtitle">参考解预览</h3>
      <p class="sfx-t-caption">参考源码仅用于这次预览，不会保存到实验、日志或智能体上下文。</p>
      <label>参考解语言<select v-model="referenceForm.language" class="sfx-input"><option v-for="language in selectedLanguages" :key="language" :value="language">{{ language }}</option></select></label>
      <label>参考源码<textarea v-model="referenceForm.source_code" class="sfx-input sfx-code-input" rows="12" spellcheck="false" /></label>
      <div v-if="preview" class="sfx-preview-result" :class="preview.accepted ? 'accepted' : 'rejected'">
        <SfxBadge :tone="preview.accepted ? 'green' : 'red'">{{ preview.accepted ? '全部通过' : '未全部通过' }}</SfxBadge>
        <span>{{ preview.passed_count }} / {{ preview.total_count }} 个测试通过</span>
      </div>
      <div class="sfx-wizard-actions">
        <SfxButton type="submit" :disabled="!referenceForm.source_code.trim()" :loading="saving">运行参考解预览</SfxButton>
        <SfxButton variant="secondary" :disabled="!canLock" @click="stage = 'lock'">进入锁定</SfxButton>
      </div>
    </form>

    <section v-else-if="stage === 'lock'" class="sfx-panel sfx-wizard-form">
      <h3 class="sfx-panel-subtitle">锁定版本</h3>
      <p>锁定后，题目资源和测试集不再可修改。后续调整请创建新版本并重新预览。</p>
      <div class="sfx-wizard-actions">
        <SfxButton variant="secondary" @click="stage = 'preview'">返回预览</SfxButton>
        <SfxButton :disabled="!canLock" :loading="saving" @click="lockVersion">锁定版本</SfxButton>
      </div>
    </section>

    <section v-else-if="stage === 'publish'" class="sfx-panel sfx-wizard-form">
      <h3 class="sfx-panel-subtitle">发布实验</h3>
      <p>发布前服务端会再次校验课程能力、评测机、语言白名单、资源边界、全量测试、默认版本、锁定状态和参考解预览。</p>
      <SfxButton :disabled="!canPublish" :loading="saving" @click="publish">发布给学生</SfxButton>
    </section>

    <section v-else-if="stage === 'complete'" class="sfx-panel sfx-wizard-form">
      <h3 class="sfx-panel-subtitle">实验已发布</h3>
      <p>学生提交将进入持久化评测队列，只有服务端终结结果会生成实验室可信记录。</p>
      <SfxButton variant="secondary" @click="startNewDraft">创建下一项实验</SfxButton>
    </section>

    <section class="sfx-panel sfx-experiment-list">
      <header class="sfx-list-header"><h3 class="sfx-panel-subtitle">现有实验</h3><SfxButton variant="secondary" size="sm" :loading="state === 'loading'" @click="load">刷新</SfxButton></header>
      <SfxError v-if="state === 'error'" :description="error" @retry="load" />
      <SfxEmpty v-else-if="state === 'empty'" title="暂无实验任务" description="创建草稿后可继续完成版本、测试和发布。" />
      <div v-else class="sfx-table-wrap">
        <table class="sfx-table">
          <thead><tr><th>任务</th><th>语言</th><th>状态</th><th>默认版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.experiment_id">
              <td><strong>{{ item.title }}</strong><p class="sfx-t-caption">{{ item.description }}</p></td>
              <td>{{ (item.language_whitelist || []).join(', ') }}</td>
              <td><SfxBadge :tone="item.publish_status === 'published' ? 'green' : 'amber'">{{ item.publish_status }}</SfxBadge></td>
              <td>{{ item.default_version_id || '未创建' }}</td>
              <td><SfxButton v-if="item.publish_status !== 'published'" size="sm" variant="secondary" @click="continueDraft(item)">继续配置</SfxButton></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
.sfx-teacher-experiments { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.sfx-experiment-header, .sfx-list-header, .sfx-wizard-actions, .sfx-test-case > header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.sfx-experiment-header > div { min-width: 0; }
.sfx-experiment-header p, .sfx-wizard-form > p { margin: var(--space-1) 0 0; color: var(--text-secondary); line-height: 1.6; }
.sfx-experiment-steps { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: var(--space-2); padding: 0; margin: 0; list-style: none; }
.sfx-experiment-steps li { min-height: 36px; display: flex; align-items: center; justify-content: center; padding: 0 var(--space-2); border: var(--border-default); color: var(--text-muted); font-size: var(--ui-sm-size); text-align: center; overflow-wrap: anywhere; }
.sfx-experiment-steps li.active { border-color: var(--color-brand); color: var(--color-brand); background: var(--ink-100); }
.sfx-experiment-steps li.complete { border-color: var(--green-300); color: var(--green-700); background: var(--green-100); }
.sfx-wizard-form { display: grid; gap: var(--space-4); max-width: 960px; }
.sfx-wizard-form label { display: grid; gap: var(--space-2); color: var(--text-primary); font-size: var(--ui-md-size); font-weight: var(--ui-md-weight); }
.sfx-panel-subtitle { margin: 0; font-size: var(--title-3-size); line-height: var(--title-3-line-height); }
.sfx-limit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.sfx-test-case { display: grid; gap: var(--space-3); padding: var(--space-4); border: var(--border-default); border-radius: var(--radius-md); background: var(--surface-cool); }
.sfx-test-case > header { justify-content: flex-start; }
.sfx-test-case > header .sfx-btn { margin-left: auto; }
.sfx-code-input { min-height: 80px; font-family: "JetBrains Mono", "Fira Code", Consolas, monospace; line-height: 1.55; }
.sfx-preview-result { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3); border: var(--border-default); }
.sfx-preview-result.accepted { border-color: var(--green-300); background: var(--green-100); }
.sfx-preview-result.rejected { border-color: var(--red-300); background: var(--red-100); }
.sfx-experiment-list { display: grid; gap: var(--space-4); min-width: 0; }
@media (max-width: 760px) {
  .sfx-experiment-header, .sfx-list-header, .sfx-wizard-actions { align-items: stretch; flex-direction: column; }
  .sfx-experiment-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sfx-limit-grid { grid-template-columns: 1fr; }
}
</style>
