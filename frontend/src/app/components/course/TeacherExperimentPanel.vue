<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import {
  createExperimentDefinition,
  createExperimentVersion,
  listExperimentDefinitions,
  lockExperimentVersion,
  previewExperimentReference,
  publishExperimentDefinition,
} from '@/api/experiments.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const step = ref(1)
const busy = ref(false)
const error = ref('')
const items = ref([])
const draft = ref(null)
const version = ref(null)
const preview = ref(null)
const form = ref({
  title: '', description: '', languages: 'python3', maxAttempts: 3,
  cpu: 5, memory: 128000, wall: 10,
  publicInput: '', publicOutput: '', hiddenInput: '', hiddenOutput: '',
  referenceCode: '',
})

const tests = computed(() => [
  { case_name: 'public_1', stdin: form.value.publicInput, expected_stdout: form.value.publicOutput, is_hidden: false, weight: 0.5 },
  { case_name: 'hidden_1', stdin: form.value.hiddenInput, expected_stdout: form.value.hiddenOutput, is_hidden: true, weight: 0.5 },
])

async function load() {
  try { items.value = (await listExperimentDefinitions(courseId.value))?.items || [] } catch (reason) { error.value = reason?.message || '实验定义读取失败' }
}

async function createDefinition() {
  if (!form.value.title.trim()) return
  busy.value = true; error.value = ''
  try {
    draft.value = await createExperimentDefinition(courseId.value, {
      title: form.value.title.trim(), description: form.value.description,
      language_whitelist: form.value.languages.split(',').map((item) => item.trim()).filter(Boolean),
      max_attempts: form.value.maxAttempts, cooldown_minutes: 0,
    })
    step.value = 2
    await load()
  } catch (reason) { error.value = reason?.message || '创建草稿失败' } finally { busy.value = false }
}

async function createVersion() {
  if (!draft.value || tests.value.some((item) => !item.expected_stdout.trim())) { error.value = '公开与隐藏测试都需要期望输出'; return }
  busy.value = true; error.value = ''
  try {
    version.value = await createExperimentVersion(courseId.value, draft.value.experiment_id, {
      label: 'v1', cpu_time_limit: form.value.cpu, memory_limit: form.value.memory, wall_time_limit: form.value.wall,
      max_processes: 30, max_file_size: 1024, passing_score: 1.0, writes_formal_evidence: true, test_cases: tests.value, activate: true,
    })
    step.value = 3
  } catch (reason) { error.value = reason?.message || '创建版本失败' } finally { busy.value = false }
}

async function verifyReference() {
  if (!version.value || !form.value.referenceCode.trim()) return
  busy.value = true; error.value = ''
  try {
    preview.value = await previewExperimentReference(courseId.value, version.value.version_id, {
      language: form.value.languages.split(',')[0].trim(), source_code: form.value.referenceCode,
    })
    if (preview.value?.passed) step.value = 4
    else error.value = '参考解没有通过全部测试，不能锁定或发布。'
  } catch (reason) { error.value = reason?.message || '参考解预览失败' } finally { busy.value = false }
}

async function lockVersion() {
  busy.value = true; error.value = ''
  try { version.value = await lockExperimentVersion(courseId.value, version.value.version_id); step.value = 5 } catch (reason) { error.value = reason?.message || '锁定版本失败' } finally { busy.value = false }
}

async function publish() {
  busy.value = true; error.value = ''
  try { await publishExperimentDefinition(courseId.value, draft.value.experiment_id); await load(); step.value = 6 } catch (reason) { error.value = reason?.message || '发布校验未通过' } finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <section class="sfx-teacher-experiments">
    <header class="sfx-exp-wizard-head"><div><h2 class="sfx-panel-title">教师实验发布向导</h2><p class="sfx-t-ui sfx-t-secondary">定义 → 资源 → 测试 → 参考解 → 锁定 → 发布。所有门槛由服务端再次校验。</p></div><SfxBadge tone="ink">步骤 {{ step }}/6</SfxBadge></header>
    <div class="sfx-exp-steps" aria-label="发布步骤"><SfxBadge v-for="index in 6" :key="index" :tone="index <= step ? 'green' : 'neutral'">{{ index }}</SfxBadge></div>
    <section v-if="step === 1" class="sfx-panel sfx-form-grid">
      <label>任务名称<input v-model.trim="form.title" class="sfx-input" placeholder="例如：二分查找边界" /></label>
      <label>任务说明<textarea v-model="form.description" class="sfx-input" rows="3" /></label>
      <label>语言白名单<input v-model="form.languages" class="sfx-input" placeholder="python3" /></label>
      <label>最大尝试次数<input v-model.number="form.maxAttempts" class="sfx-input" min="1" type="number" /></label>
      <SfxButton :loading="busy" @click="createDefinition">创建任务定义</SfxButton>
    </section>
    <section v-else-if="step === 2" class="sfx-panel sfx-form-grid">
      <h3 class="sfx-panel-title">语言、资源与测试集</h3>
      <div class="sfx-resource-grid"><label>CPU 秒<input v-model.number="form.cpu" class="sfx-input" type="number" min="1" max="30" /></label><label>内存 KB<input v-model.number="form.memory" class="sfx-input" type="number" min="16000" max="512000" /></label><label>墙钟秒<input v-model.number="form.wall" class="sfx-input" type="number" min="1" max="60" /></label></div>
      <label>公开输入<textarea v-model="form.publicInput" class="sfx-input" rows="2" /></label><label>公开期望输出<textarea v-model="form.publicOutput" class="sfx-input" rows="2" /></label>
      <label>隐藏输入（仅教师可见）<textarea v-model="form.hiddenInput" class="sfx-input" rows="2" /></label><label>隐藏期望输出（仅教师可见）<textarea v-model="form.hiddenOutput" class="sfx-input" rows="2" /></label>
      <p class="sfx-t-caption">两个测试各占 0.5，满足测试权重总和为 1 的完整性校验；最终成绩仍为 ACM/ICPC 的 0 或 1。</p>
      <SfxButton :loading="busy" @click="createVersion">创建活动版本</SfxButton>
    </section>
    <section v-else-if="step === 3" class="sfx-panel sfx-form-grid"><h3 class="sfx-panel-title">参考解预览</h3><p class="sfx-t-ui sfx-t-secondary">参考源码只在本次 Judge0 预览中使用，不持久化、不写日志或 Agent 上下文。</p><textarea v-model="form.referenceCode" class="sfx-code-editor" rows="10" spellcheck="false" placeholder="粘贴临时参考解…" /><SfxButton :loading="busy" @click="verifyReference">在全部测试上预览</SfxButton></section>
    <section v-else-if="step === 4" class="sfx-panel"><h3 class="sfx-panel-title">锁定版本</h3><p class="sfx-t-ui sfx-t-secondary">参考解已全 AC。锁定后，测试与资源边界不能再被静默修改。</p><SfxButton :loading="busy" @click="lockVersion">锁定活动版本</SfxButton></section>
    <section v-else-if="step === 5" class="sfx-panel"><h3 class="sfx-panel-title">发布前检查</h3><p class="sfx-t-ui sfx-t-secondary">服务端会检查课程能力、认证后的沙箱、语言、资源、测试权重、锁定版本与参考解预览。</p><SfxButton :loading="busy" @click="publish">发布给学生</SfxButton></section>
    <section v-else class="sfx-panel"><h3 class="sfx-panel-title">已发布</h3><p class="sfx-t-ui sfx-t-secondary">学生提交后会异步评测、自动终结，并生成可信实验记录。</p><SfxButton variant="secondary" @click="step = 1; draft = null; version = null; preview = null">创建下一项实验</SfxButton></section>
    <SfxError v-if="error" :description="error" @retry="load" />
    <section v-if="items.length" class="sfx-panel"><h3 class="sfx-panel-title">课程实验</h3><div class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>任务</th><th>语言</th><th>状态</th></tr></thead><tbody><tr v-for="item in items" :key="item.experiment_id"><td>{{ item.title }}</td><td>{{ (item.language_whitelist || []).join(', ') }}</td><td><SfxBadge :tone="item.publish_status === 'published' ? 'green' : 'amber'">{{ item.publish_status }}</SfxBadge></td></tr></tbody></table></div></section>
  </section>
</template>

<style scoped>
.sfx-teacher-experiments,.sfx-form-grid{display:flex;flex-direction:column;gap:var(--space-3)}.sfx-exp-wizard-head{display:flex;justify-content:space-between;gap:var(--space-3)}.sfx-exp-steps,.sfx-resource-grid{display:flex;gap:var(--space-2);flex-wrap:wrap}.sfx-form-grid label{display:flex;flex-direction:column;gap:var(--space-1);font-size:var(--ui-sm-size);color:var(--text-secondary)}.sfx-resource-grid label{min-width:10rem;flex:1}.sfx-code-editor{width:100%;border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-panel);padding:var(--space-2) var(--space-3);font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
</style>
