<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { LockKeyhole, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import { listCourseMembers } from '@/api/course_access.js'
import { getCourseSettings, listCourseGroups, updateCourseAgentPolicy } from '@/api/course_lifecycle.js'
import {
  getTeachingConstraints,
  getTeachingToolPolicies,
  listTeachingConstraintEvaluations,
  listTeachingConstraintVersions,
  previewTeachingConstraints,
  rollbackTeachingConstraints,
  updateTeachingConstraints,
  updateTeachingToolPolicies,
} from '@/api/agent_governance.js'
import { normalizeConstraintProfile, normalizeConstraintRule } from '@/app/lib/teachingConstraints.js'
import TeachingConstraintRules from './components/TeachingConstraintRules.vue'
import TeachingHardnessEditor from './components/TeachingHardnessEditor.vue'
import TeachingToolPolicyTable from './components/TeachingToolPolicyTable.vue'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const canConfigure = computed(() => Boolean(courseContext.allowed.value?.['agent.policy.configure']))
const canView = computed(() => Boolean(courseContext.allowed.value?.['agent.policy.view'] || canConfigure.value))

const loading = ref(true)
const loadError = ref('')
const launchForm = ref({ enabled: true })
const settingVersion = ref(null)
const savingLaunch = ref(false)
const launchNotice = ref('')

const baseline = ref(normalizeConstraintProfile())
const rules = ref([])
const constraintVersion = ref(0)
const constraintVersions = ref([])
const changeReason = ref('调整课程教学约束')
const savingConstraints = ref(false)
const constraintNotice = ref('')
const conflict = ref(false)

const members = ref([])
const groups = ref([])
const tools = ref([])
const toolVersion = ref(null)
const evaluations = ref([])
const savingTools = ref(false)

const previewStudentId = ref('')
const previewIntent = ref('concept_question')
const previewResult = ref(null)
const previewing = ref(false)

const studentOptions = computed(() => members.value.filter(item => item.role === 'student'))

function policyPayload() {
  return {
    baseline: normalizeConstraintProfile(baseline.value),
    rules: rules.value.map(rule => normalizeConstraintRule(rule)),
  }
}

async function loadLaunchSettings() {
  const data = await getCourseSettings(courseId.value)
  settingVersion.value = data?.version ?? null
  launchForm.value = { enabled: data?.agent_policy?.enabled !== false }
}

async function loadGovernance() {
  if (!canView.value) throw new Error('当前账号没有查看智能体治理策略的权限。')
  const results = await Promise.allSettled([
    getTeachingConstraints(courseId.value),
    getTeachingToolPolicies(courseId.value),
    listTeachingConstraintEvaluations(courseId.value, 20),
    listTeachingConstraintVersions(courseId.value),
    listCourseMembers(courseId.value),
    listCourseGroups(courseId.value),
  ])
  if (results[0].status === 'rejected') throw results[0].reason

  const constraint = results[0].value?.active_version ?? {}
  const policy = constraint.policy ?? {}
  constraintVersion.value = Number(constraint.version ?? 0)
  baseline.value = normalizeConstraintProfile(policy.baseline ?? policy)
  rules.value = (policy.rules ?? []).map(rule => normalizeConstraintRule(rule))

  if (results[1].status === 'fulfilled') {
    tools.value = results[1].value?.items ?? []
    toolVersion.value = results[1].value?.active_version?.version ?? null
  }
  if (results[2].status === 'fulfilled') evaluations.value = results[2].value?.items ?? []
  if (results[3].status === 'fulfilled') constraintVersions.value = results[3].value?.items ?? []
  if (results[4].status === 'fulfilled') members.value = results[4].value?.members ?? []
  if (results[5].status === 'fulfilled') groups.value = results[5].value?.items ?? []
  if (!previewStudentId.value && studentOptions.value.length) previewStudentId.value = String(studentOptions.value[0].user_id)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([loadLaunchSettings(), loadGovernance()])
  } catch (error) {
    loadError.value = error?.message || '智能体治理策略读取失败。'
  } finally {
    loading.value = false
  }
}

async function saveLaunch() {
  savingLaunch.value = true
  launchNotice.value = ''
  try {
    await updateCourseAgentPolicy(courseId.value, launchForm.value, settingVersion.value)
    launchNotice.value = '智能体启动策略已保存。'
    await loadLaunchSettings()
  } catch (error) {
    launchNotice.value = error?.message || '保存智能体启动策略失败。'
  } finally {
    savingLaunch.value = false
  }
}

async function saveConstraints() {
  savingConstraints.value = true
  constraintNotice.value = ''
  conflict.value = false
  try {
    const data = await updateTeachingConstraints(courseId.value, {
      expected_version: constraintVersion.value,
      change_reason: changeReason.value.trim() || '调整课程教学约束',
      policy: policyPayload(),
    })
    const active = data?.active_version ?? {}
    constraintVersion.value = Number(active.version ?? constraintVersion.value)
    constraintNotice.value = `约束策略已保存为版本 ${constraintVersion.value}。`
    constraintVersions.value = (await listTeachingConstraintVersions(courseId.value))?.items ?? []
  } catch (error) {
    if (error?.response?.status === 409) {
      conflict.value = true
      constraintNotice.value = '策略已被其他教师更新。当前未保存表单仍保留，请重新加载后再决定是否重做。'
    } else {
      constraintNotice.value = error?.message || '保存教学约束失败。'
    }
  } finally {
    savingConstraints.value = false
  }
}

async function rollbackVersion(targetVersion) {
  if (!canConfigure.value || constraintVersion.value < 1) return
  savingConstraints.value = true
  try {
    await rollbackTeachingConstraints(courseId.value, {
      target_version: targetVersion,
      expected_version: constraintVersion.value,
      change_reason: `教师回滚到版本 ${targetVersion}`,
    })
    await loadGovernance()
    constraintNotice.value = `已从版本 ${targetVersion} 创建新的回滚版本。`
  } catch (error) {
    constraintNotice.value = error?.message || '回滚失败。'
  } finally {
    savingConstraints.value = false
  }
}

async function saveTools(rows) {
  savingTools.value = true
  try {
    const updates = rows.map(row => ({
      tool_name: row.tool_name,
      enabled: Boolean(row.enabled),
      require_confirmation: row.confirmation_threshold !== 'never',
      confirmation_threshold: row.confirmation_threshold,
      locked: Boolean(row.locked),
      locked_reason: row.locked_reason || null,
    }))
    const data = await updateTeachingToolPolicies(courseId.value, {
      ...(toolVersion.value == null ? {} : { expected_version: toolVersion.value }),
      updates,
    })
    toolVersion.value = data?.active_version?.version ?? toolVersion.value
    const refreshed = await getTeachingToolPolicies(courseId.value)
    tools.value = refreshed?.items ?? []
  } finally {
    savingTools.value = false
  }
}

async function preview() {
  if (!previewStudentId.value) return
  previewing.value = true
  try {
    const data = await previewTeachingConstraints(courseId.value, {
      student_id: Number(previewStudentId.value),
      intent: previewIntent.value,
      policy: policyPayload(),
    })
    previewResult.value = data?.effective ?? null
  } finally {
    previewing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-settings-page sfx-agent-settings">
    <header class="sfx-settings-head">
      <div><h1 class="sfx-t-title2">智能体设置</h1><p class="sfx-t-ui sfx-t-secondary">集中管理启动状态、教学约束、对象例外、工具确认与执行审计。</p></div>
      <SfxBadge tone="ink">约束版本 {{ constraintVersion }}</SfxBadge>
    </header>

    <SfxSkeleton v-if="loading" :lines="8" />
    <SfxError v-else-if="loadError" :description="loadError" @retry="load" />

    <template v-else>
      <section class="sfx-panel agent-section">
        <div class="section-head"><div><h2 class="sfx-panel-title">1. 智能体启动</h2><p>关闭后学生侧教学问答入口不可用；该开关与下方版本化约束独立保存。</p></div></div>
        <label class="agent-check"><input v-model="launchForm.enabled" type="checkbox" :disabled="!canConfigure" /><span>启用课程教学智能体</span></label>
        <p v-if="launchNotice" class="section-notice" role="status">{{ launchNotice }}</p>
        <div class="section-actions"><SfxButton :disabled="!canConfigure" :loading="savingLaunch" @click="saveLaunch">保存启动策略</SfxButton></div>
      </section>

      <section class="sfx-panel agent-section">
        <div class="section-head"><div><h2 class="sfx-panel-title"><LockKeyhole :size="17" /> 2. 平台硬底线</h2><p>以下规则由服务端确定性执行，教师与学生均不能关闭。</p></div></div>
        <ul class="floor-list">
          <li><ShieldCheck :size="16" /> 课程事实回答必须保留可验证引用</li>
          <li><ShieldCheck :size="16" /> 高风险动作至少需要教师确认</li>
          <li><ShieldCheck :size="16" /> 课程、学习者、分组与审计严格隔离</li>
          <li><ShieldCheck :size="16" /> 学生请求不能携带或覆盖 hardness 与工具权限</li>
        </ul>
      </section>

      <section class="sfx-panel agent-section">
        <div class="section-head"><div><h2 class="sfx-panel-title">3. 约束强度</h2><p>配置课程基线、五类约束范围和受界高级参数。</p></div></div>
        <TeachingHardnessEditor v-model="baseline" :disabled="!canConfigure" />
        <SfxField label="变更原因" hint="写入不可变版本记录，便于审计与回滚。" required>
          <input v-model="changeReason" class="sfx-input" maxlength="256" :disabled="!canConfigure" />
        </SfxField>
        <p v-if="constraintNotice" class="section-notice" :class="{ 'is-conflict': conflict }" :role="conflict ? 'alert' : 'status'">{{ constraintNotice }}</p>
        <div class="section-actions">
          <SfxButton v-if="conflict" variant="secondary" @click="load"><template #icon><RefreshCw :size="15" /></template>重新加载</SfxButton>
          <SfxButton :disabled="!canConfigure" :loading="savingConstraints" @click="saveConstraints">保存约束新版本</SfxButton>
        </div>
        <div v-if="constraintVersions.length" class="version-list">
          <span class="sfx-t-ui">版本历史</span>
          <div v-for="item in constraintVersions.slice(0, 5)" :key="item.version" class="version-row">
            <span>v{{ item.version }} · {{ item.change_reason }}</span>
            <SfxButton v-if="item.version !== constraintVersion" variant="tertiary" size="sm" :disabled="!canConfigure" @click="rollbackVersion(item.version)">回滚为新版本</SfxButton>
            <SfxBadge v-else tone="green">当前版本</SfxBadge>
          </div>
        </div>
      </section>

      <section class="sfx-panel agent-section">
        <div class="section-head"><div><h2 class="sfx-panel-title">4. 生效对象与例外</h2><p>按课程分组或学生设置意图、概念、优先级与时间窗；服务端复核对象归属。</p></div></div>
        <TeachingConstraintRules v-model="rules" :members="members" :groups="groups" :disabled="!canConfigure" />
        <div class="preview-row">
          <select v-model="previewStudentId" class="sfx-select" :disabled="!studentOptions.length">
            <option value="">选择学生进行预览</option><option v-for="item in studentOptions" :key="item.user_id" :value="String(item.user_id)">学生 #{{ item.user_id }}</option>
          </select>
          <select v-model="previewIntent" class="sfx-select"><option value="concept_question">概念问答</option><option value="code_debugging">代码诊断</option><option value="learning_guidance">学习引导</option><option value="other">其他</option></select>
          <SfxButton variant="secondary" :disabled="!previewStudentId" :loading="previewing" @click="preview">预览有效约束</SfxButton>
        </div>
        <p v-if="previewResult" class="preview-result">有效等级：<strong>{{ previewResult.level }}</strong>；命中规则：{{ previewResult.matched_rule_ids?.join('、') || '课程基线' }}；禁用工具：{{ previewResult.disabled_tools?.join('、') || '无' }}。</p>
      </section>

      <section class="sfx-panel agent-section">
        <div class="section-head"><div><h2 class="sfx-panel-title">5. 工具与审计</h2><p>工具允许规则与 hardness 取交集；平台审计不可关闭且不保存原始问答正文。</p></div></div>
        <TeachingToolPolicyTable :tools="tools" :evaluations="evaluations" :disabled="!canConfigure" :saving="savingTools" @save="saveTools" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.sfx-agent-settings { max-width: 980px; }
.agent-section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-head h2, .section-head p { margin: 0; }
.section-head h2 { display: flex; align-items: center; gap: var(--space-2); }
.section-head p { margin-top: var(--space-1); color: var(--text-secondary); }
.agent-check { display: flex; align-items: center; gap: var(--space-2); cursor: pointer; }
.agent-check input { width: 16px; height: 16px; accent-color: var(--ink-700); }
.floor-list { margin: 0; padding: 0; list-style: none; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.floor-list li { display: flex; align-items: center; gap: var(--space-2); color: var(--green-700); }
.section-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.section-notice, .preview-result { margin: 0; padding: var(--space-2) var(--space-3); border: var(--border-default); border-radius: var(--radius-md); background: var(--surface-cool); color: var(--text-secondary); }
.section-notice.is-conflict { border-color: var(--amber-300); background: var(--amber-100); color: var(--amber-700); }
.version-list { display: flex; flex-direction: column; gap: var(--space-2); padding-top: var(--space-3); border-top: var(--border-default); }
.version-row { min-height: 36px; display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.preview-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: var(--space-3); align-items: center; padding-top: var(--space-3); border-top: var(--border-default); }
@media (max-width: 720px) { .floor-list, .preview-row { grid-template-columns: 1fr; } }
</style>
