<template>
  <main class="production-workspace">
    <header class="workspace-header">
      <div class="course-identity">
        <button class="back-button" type="button" aria-label="返回课程编辑" @click="goLegacy"><ArrowLeft :size="18" /></button>
        <div>
          <p class="breadcrumb">教师空间 / 课程生产</p>
          <h1>{{ courseTitle }} <span>课程 #{{ courseId }}</span></h1>
          <p v-if="courseMeta" class="course-meta">{{ courseMeta }}</p>
        </div>
      </div>
      <div class="header-actions">
        <span class="save-state"><Cloud :size="16" />{{ saveState }}</span>
        <button type="button" class="secondary" @click="goMapping"><Waypoints :size="16" />知识映射</button>
        <button type="button" class="secondary" @click="goLegacy"><ExternalLink :size="16" />原编辑器</button>
        <button type="button" class="primary publish-action" :disabled="publicationLoading || (!isPublished && !canPublish)" :aria-describedby="!isPublished && !canPublish ? 'publish-blockers' : undefined" @click="togglePublication"><Upload :size="16" />{{ publicationLoading ? '处理中…' : isPublished ? '取消发布' : '发布课程' }}</button>
      </div>
    </header>

    <div v-if="contextError" class="context-error" role="alert"><AlertTriangle :size="17" /><span>{{ contextError }}</span><button type="button" @click="loadCourseContext">重试读取</button></div>

    <div class="workbench-grid">
      <nav class="pipeline" aria-label="课程生产步骤">
        <p class="pipeline-label">生产流程</p>
        <button v-for="step in steps" :key="step.id" type="button" :class="['pipeline-step', { active: activeStep === step.id }]" :aria-current="activeStep === step.id ? 'step' : undefined" @click="selectStep(step.id)">
          <component :is="step.icon" :size="17" /><span>{{ step.label }}</span><small :class="`state-${step.state}`">{{ step.stateLabel }}</small>
        </button>
      </nav>

      <section class="main-stage" aria-live="polite">
        <div class="stage-heading">
          <div><p class="eyebrow">当前步骤</p><h2>{{ currentStep.label }}</h2><p>{{ currentStep.description }}</p></div>
          <div class="heading-status"><span class="course-status" :class="isPublished ? 'published' : 'draft'">{{ isPublished ? '已发布' : '草稿' }}</span><span class="status-chip" :class="`state-${currentStep.state}`">{{ currentStep.stateLabel }}</span></div>
        </div>

        <section v-if="activeStep === 'materials'" class="stage-panel">
          <FileUp :size="28" /><h3>沿用已验证的资料上传与解析流程</h3>
          <p>{{ parseDescription }}</p>
          <button type="button" class="primary" @click="goLegacy"><Upload :size="16" />去上传或检查教学资料</button>
        </section>

        <section v-else-if="activeStep === 'script'" class="stage-panel wide-panel">
          <div class="split-heading"><div><h3>脚本版本</h3><p>保存快照后可在已有接口允许的范围内回滚。</p></div><button type="button" class="secondary" :disabled="snapshotLoading" @click="createSnapshot"><Save :size="16" />{{ snapshotLoading ? '保存中…' : '创建快照' }}</button></div>
          <div v-if="versionsLoading" class="empty-state"><LoaderCircle class="spin" :size="20" />正在读取脚本版本…</div>
          <div v-else-if="versionsError" class="error-state"><AlertTriangle :size="18" /><span>{{ versionsError }}</span><button type="button" @click="loadVersions">重试</button></div>
          <ol v-else-if="versions.length" class="version-list"><li v-for="version in versions" :key="version.id || version.script_id"><span><strong>{{ version.version_name || version.name || '未命名快照' }}</strong><small>{{ version.created_at || '时间未知' }}</small></span><span v-if="version.is_active" class="status-chip state-complete">当前使用</span></li></ol>
          <div v-else class="empty-state">尚无脚本快照。创建快照后可在原编辑器中查看和回滚。</div>
        </section>

        <section v-else-if="activeStep === 'mapping'" class="stage-panel wide-panel">
          <Waypoints :size="28" /><h3>知识点—PPT 映射治理</h3><p>{{ mappingDescription }}</p>
          <button type="button" class="primary" @click="goMapping"><ArrowRight :size="16" />进入映射工作区</button>
        </section>

        <section v-else-if="activeStep === 'ppt'" class="stage-panel wide-panel">
          <Presentation :size="28" /><h3>生成课程 PPT</h3><p>复用现有 PPT 生成对话框。生成完成后，请在新课程的工作台中进行映射检查。</p>
          <button type="button" class="primary" @click="showPptDialog = true"><Sparkles :size="16" />生成 PPT</button>
          <p class="integration-note"><Info :size="16" />现有异步 PPT 创建接口只返回课程 ID，未返回可轮询的任务 ID；因此本页不会要求教师手动填入 sid。</p>
        </section>

        <section v-else-if="activeStep === 'audio'" class="stage-panel wide-panel">
          <Volume2 :size="28" /><h3>课程音频状态</h3><p>工作台持续读取课程级 TTS 状态。当前后端没有独立的课程级 TTS 重试接口，失败后可返回原编辑器重新发起。</p>
          <button type="button" class="secondary" @click="goLegacy">在原编辑器生成音频 <ExternalLink :size="16" /></button>
        </section>

        <section v-else-if="activeStep === 'avatar'" class="stage-panel wide-panel">
          <Video :size="28" /><h3>课程数字人视频</h3><p>在右侧任务面板提交或恢复数字人视频任务。任务提交后可以离开本页，重新进入会从课程任务列表读取状态。</p>
        </section>

        <section v-else class="stage-panel">
          <component :is="currentStep.icon" :size="28" /><h3>{{ currentStep.legacyTitle }}</h3><p>{{ currentStep.legacyDescription }}</p><button type="button" class="secondary" @click="goLegacy">在原编辑器中处理 <ExternalLink :size="16" /></button>
        </section>
      </section>

      <aside class="quality-panel" aria-label="发布检查与任务状态">
        <div class="quality-title"><ShieldCheck :size="18" /><div><h2>发布检查</h2><p>{{ isPublished ? '课程当前已对学生可见' : '发布前请完成必要确认' }}</p></div></div>
        <ul class="checklist"><li v-for="item in checks" :key="item.label" :class="`check-${item.state}`"><component :is="item.state === 'complete' ? CheckCircle2 : item.state === 'blocked' ? AlertTriangle : CircleDashed" :size="17" :class="item.state" /><span>{{ item.label }}</span><small>{{ item.note }}</small></li></ul>
        <div v-if="mappingReady && !mappingReviewed" class="review-action"><p><Info :size="16" />页面范围已具备，仍需教师完成本次检查。</p><button type="button" class="secondary full-width" @click="confirmMappingReview">确认已检查映射</button></div>
        <div v-if="!isPublished" id="publish-blockers" class="publish-summary" :class="canPublish ? 'ready' : 'blocked'"><component :is="canPublish ? CheckCircle2 : AlertTriangle" :size="17" /><p>{{ canPublish ? '已满足本工作台可验证的发布条件。' : `发布前还需：${publishBlockers.join('、')}` }}</p></div>
        <div class="notice"><Info :size="17" /><p>“已生成”不等于“已确认”。当前后端没有持久化教师确认状态；本页的映射检查确认只在本次会话用于发布判断。</p></div>
        <CourseTaskPanel :course-id="courseId" :show-video-generation="activeStep === 'avatar'" @open-legacy="goLegacy" @summary="handleTaskSummary" />
      </aside>
    </div>
    <PPTGenerationDialog v-model:visible="showPptDialog" :course-id="courseId" @generated="onPptGenerated" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, CircleDashed, Cloud, ExternalLink, FileCheck2, FileText, FileUp, Info, LoaderCircle, Presentation, Save, ShieldCheck, Sparkles, Upload, Waypoints, Volume2, Video } from 'lucide-vue-next'
import PPTGenerationDialog from '@/components/profile/LoginIn/courses/PPTGenerationDialog.vue'
import { getCourseWorkspaceContext, publishCourse, unpublishCourse } from '@/api/course_workspace.js'
import { getMappingDetail } from '@/api/mapping.js'
import { createScriptSnapshot, getScriptVersions } from '@/api/script_editor.js'
import CourseTaskPanel from '@/features/teacher-workspace/components/CourseTaskPanel.vue'
import { showToast } from '@/utils/toast.js'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => route.params.courseId)
const activeStep = ref('materials')
const stepChosenByTeacher = ref(false)
const showPptDialog = ref(false)
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')
const snapshotLoading = ref(false)
const courseLoading = ref(false)
const contextError = ref('')
const courseContext = ref(null)
const mappingInspection = ref({ loading: true, available: false, total: 0, mapped: 0 })
const mappingReviewed = ref(false)
const publicationLoading = ref(false)
const taskSummary = ref({ total: 0, running: 0, blocking: 0, review: 0, known: false })
const saveState = ref('正在同步课程状态')

const course = computed(() => courseContext.value?.course || {})
const script = computed(() => courseContext.value?.script || null)
const nodeCount = computed(() => courseContext.value?.nodes?.length || 0)
const isPublished = computed(() => course.value.status === 'published')
const courseTitle = computed(() => course.value.title || (courseLoading.value ? '正在读取课程…' : '课程生产工作台'))
const courseMeta = computed(() => {
  if (!courseContext.value) return ''
  const parts = []
  if (nodeCount.value) parts.push(`${nodeCount.value} 个知识点`)
  if (course.value.total_pages) parts.push(`${course.value.total_pages} 页资料`)
  if (script.value?.version_name || script.value?.version) parts.push(script.value.version_name || `脚本 v${script.value.version}`)
  return parts.join(' · ')
})
const parseStage = computed(() => deriveParseStage(courseContext.value?.parse_info))
const mappingReady = computed(() => mappingInspection.value.available && mappingInspection.value.total > 0 && mappingInspection.value.mapped === mappingInspection.value.total)
const mappingDescription = computed(() => {
  if (mappingInspection.value.loading) return '正在读取已有 Mapping 数据。课程上下文不会用静态映射状态代替真实检查。'
  if (!mappingInspection.value.available) return '映射状态暂时无法读取，请进入映射工作区重试。Evidence 与知识图谱审核尚未接入，因此不会用静态数据伪装为可用功能。'
  return `已有 ${mappingInspection.value.mapped}/${mappingInspection.value.total} 个知识点具备页面范围。请在独立工作区确认范围后再发布。`
})
const parseDescription = computed(() => {
  if (parseStage.value.state === 'complete') return `资料解析已完成，当前课程包含 ${nodeCount.value} 个知识点。需要调整资料或结构时，仍可返回原编辑器。`
  if (parseStage.value.state === 'running') return '资料仍在解析中。解析完成后会在重新进入工作台时同步课程结构。'
  if (parseStage.value.state === 'failed') return '资料解析未成功完成。请在原编辑器检查源文件并重新发起解析。'
  return '尚未读取到解析完成的资料。上传、Docling 解析和知识结构提取仍由现有课程编辑器负责。'
})
const steps = computed(() => [
  { id: 'materials', label: '教学资料', icon: FileUp, state: parseStage.value.state, stateLabel: parseStage.value.label, description: '上传并解析资料，建立课程原始输入。', legacyTitle: '教学资料', legacyDescription: '已有上传和解析模块保持不变。' },
  { id: 'structure', label: '课程结构', icon: FileText, state: nodeCount.value ? 'review' : parseStage.value.state === 'running' ? 'pending' : 'blocked', stateLabel: nodeCount.value ? '待检查' : parseStage.value.state === 'running' ? '解析中' : '待资料', description: '检查解析后的章节与知识点结构。', legacyTitle: '课程结构检查', legacyDescription: '请在原编辑器中选择和编辑知识节点。' },
  { id: 'script', label: '教学脚本', icon: FileCheck2, state: script.value ? 'review' : 'pending', stateLabel: script.value ? '待确认' : '待生成', description: '以版本快照保护教师修改。', legacyTitle: '教学脚本', legacyDescription: '当前可查询、创建快照；脚本正文仍由现有编辑器管理。' },
  { id: 'ppt', label: 'PPT 课件', icon: Presentation, state: 'ready', stateLabel: '可生成', description: '生成并检查课程 PPT。', legacyTitle: 'PPT 课件', legacyDescription: '请通过原编辑器访问更多模板设置。' },
  { id: 'mapping', label: '知识映射', icon: Waypoints, state: mappingReady.value ? (mappingReviewed.value ? 'complete' : 'review') : mappingInspection.value.loading ? 'pending' : 'blocked', stateLabel: mappingReady.value ? (mappingReviewed.value ? '已检查' : '待确认') : mappingInspection.value.loading ? '读取中' : '待治理', description: '审核知识点与 PPT 页面范围。', legacyTitle: '知识映射', legacyDescription: '映射治理已迁移到独立工作区。' },
  { id: 'audio', label: '音频生成', icon: Volume2, state: taskSummary.value.blocking ? 'failed' : taskSummary.value.review ? 'review' : taskSummary.value.running ? 'running' : 'pending', stateLabel: taskSummary.value.blocking ? '需恢复' : taskSummary.value.review ? '待确认' : taskSummary.value.running ? '处理中' : '查看状态', description: '在脚本确认后生成音频。', legacyTitle: '音频生成', legacyDescription: '批量 TTS 任务仍由现有编辑器发起。' },
  { id: 'avatar', label: '数字人生成', icon: Video, state: taskSummary.value.blocking ? 'failed' : taskSummary.value.review ? 'review' : taskSummary.value.running ? 'running' : 'pending', stateLabel: taskSummary.value.blocking ? '需恢复' : taskSummary.value.review ? '待确认' : taskSummary.value.running ? '处理中' : '查看状态', description: '在音频与映射确认后生成数字人内容。', legacyTitle: '数字人生成', legacyDescription: '数字人生成与资产配置仍在原编辑器。' },
])
const currentStep = computed(() => steps.value.find(step => step.id === activeStep.value) || steps.value[0])
const taskGate = computed(() => {
  if (!taskSummary.value.known) return { state: 'pending', note: '任务状态正在同步或暂时不可读', blocker: '' }
  if (taskSummary.value.blocking) return { state: 'blocked', note: `${taskSummary.value.blocking} 个失败或部分成功任务需要恢复`, blocker: '生成任务恢复' }
  if (taskSummary.value.review) return { state: 'pending', note: `${taskSummary.value.review} 个生成结果待教师确认`, blocker: '生成结果教师确认' }
  if (taskSummary.value.running) return { state: 'pending', note: `${taskSummary.value.running} 个任务仍在执行，不自动阻止发布`, blocker: '' }
  return { state: 'complete', note: '暂无阻断任务', blocker: '' }
})
const checks = computed(() => {
  const material = parseStage.value
  const mapping = mappingInspection.value
  return [
    { label: '教学资料已解析', note: material.note, state: material.state === 'complete' ? 'complete' : material.state === 'failed' ? 'blocked' : 'pending' },
    { label: '课程结构与脚本', note: script.value ? `${nodeCount.value} 个知识点，${versions.value.length || 1} 个脚本版本` : '尚未读取到可用脚本', state: script.value && nodeCount.value ? 'complete' : 'blocked' },
    { label: '知识点与 PPT 映射', note: mapping.loading ? '正在读取映射状态' : !mapping.available ? '映射状态无法读取' : !mappingReady.value ? `${mapping.mapped}/${mapping.total} 个知识点已有页面范围` : mappingReviewed.value ? '教师已在本次会话确认' : '页面范围已齐全，待教师确认', state: mappingReady.value && mappingReviewed.value ? 'complete' : !mapping.loading && (!mapping.available || !mappingReady.value) ? 'blocked' : 'pending' },
    { label: '生成任务状态', ...taskGate.value },
  ]
})
const publishBlockers = computed(() => {
  const blockers = checks.value
    .filter(item => ['教学资料已解析', '课程结构与脚本', '知识点与 PPT 映射'].includes(item.label) && item.state !== 'complete')
    .map(item => item.label)
  if (taskGate.value.blocker) blockers.push(taskGate.value.blocker)
  return blockers
})
const canPublish = computed(() => publishBlockers.value.length === 0)

function deriveParseStage(parseInfo) {
  if (!parseInfo) return { state: 'pending', label: '待解析', note: '尚未读取到解析结果' }
  const raw = String(parseInfo.status || '').toLowerCase()
  if (['completed', 'success', 'succeeded', 'done'].includes(raw)) return { state: 'complete', label: '已解析', note: `已解析 ${parseInfo.total_texts || 0} 段文本` }
  if (raw.includes('fail') || raw.includes('error')) return { state: 'failed', label: '解析失败', note: '请在原编辑器检查源文件' }
  return { state: 'running', label: raw ? '解析中' : '处理中', note: '解析服务仍在处理资料' }
}
function goLegacy() { router.push(`/teacher/course/${courseId.value}`) }
function goMapping() { router.push('/teacher/course/' + courseId.value + '/mapping') }
function selectStep(stepId) { activeStep.value = stepId; stepChosenByTeacher.value = true }
function selectRecommendedStep() {
  if (stepChosenByTeacher.value) return
  if (taskSummary.value.known && taskSummary.value.blocking) { activeStep.value = 'avatar'; return }
  if (parseStage.value.state !== 'complete') { activeStep.value = 'materials'; return }
  if (!nodeCount.value) { activeStep.value = 'structure'; return }
  if (!script.value) { activeStep.value = 'script'; return }
  if (!mappingReady.value || !mappingReviewed.value) { activeStep.value = 'mapping'; return }
  activeStep.value = 'audio'
}
function confirmMappingReview() { mappingReviewed.value = true; saveState.value = '映射已在本次会话确认，等待发布操作'; showToast('已记录本次会话的映射检查。发布后端尚未提供持久化确认字段。', 'info') }

async function loadVersions() {
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const result = await getScriptVersions(courseId.value)
    versions.value = Array.isArray(result) ? result : (result?.versions || result?.items || [])
  } catch {
    versionsError.value = '脚本版本暂时无法读取，请检查网络或在原编辑器中重试。'
  } finally {
    versionsLoading.value = false
  }
}
async function loadMappingInspection() {
  mappingInspection.value = { loading: true, available: false, total: 0, mapped: 0 }
  try {
    const result = await getMappingDetail(courseId.value)
    const nodes = Array.isArray(result?.nodes) ? result.nodes : []
    const mapped = nodes.filter(node => Number.isFinite(Number(node.page_start)) && Number(node.page_start) >= 1 && Number.isFinite(Number(node.page_end)) && Number(node.page_end) >= Number(node.page_start)).length
    mappingInspection.value = { loading: false, available: true, total: nodes.length, mapped }
  } catch {
    mappingInspection.value = { loading: false, available: false, total: 0, mapped: 0 }
  }
}
async function loadCourseContext() {
  courseLoading.value = true
  contextError.value = ''
  try {
    courseContext.value = await getCourseWorkspaceContext(courseId.value)
    saveState.value = '课程上下文已同步'
  } catch {
    contextError.value = '课程上下文暂时无法读取。页面不会用静态课程或发布状态代替真实数据。'
    saveState.value = '课程上下文未同步'
  } finally {
    courseLoading.value = false
  }
  await loadMappingInspection()
  selectRecommendedStep()
}
async function createSnapshot() {
  snapshotLoading.value = true
  try {
    await createScriptSnapshot(courseId.value)
    showToast('脚本快照已创建', 'success')
    await loadVersions()
  } catch {
    showToast('创建脚本快照失败，请稍后重试', 'error')
  } finally {
    snapshotLoading.value = false
  }
}
async function togglePublication() {
  if (!isPublished.value && !canPublish.value) return
  const wasPublished = isPublished.value
  if (!wasPublished) {
    showToast('请在课程建设的“正式发布”步骤运行发布前检查；如有问题，确认后再发布。', 'info')
    router.push(`/app/course/${courseId.value}/build/releases`)
    return
  }
  const nextAction = wasPublished ? '取消发布' : '发布'
  if (!window.confirm(`确定要${nextAction}“${courseTitle.value}”吗？`)) return
  publicationLoading.value = true
  try {
    await unpublishCourse(courseId.value)
    if (courseContext.value?.course) courseContext.value = { ...courseContext.value, course: { ...courseContext.value.course, status: wasPublished ? 'draft' : 'published' } }
    saveState.value = wasPublished ? '课程已取消发布' : '课程已发布'
    showToast(wasPublished ? '课程已取消发布' : '课程已发布', 'success')
  } catch {
    showToast(`${nextAction}失败，请检查课程权限和网络后重试。`, 'error')
  } finally {
    publicationLoading.value = false
  }
}
function handleTaskSummary(summary) {
  taskSummary.value = { ...taskSummary.value, ...summary }
  saveState.value = summary.running ? '有 ' + summary.running + ' 个后台任务正在执行' : summary.blocking ? summary.blocking + ' 个后台任务需要恢复' : summary.known ? '课程任务已同步' : '课程任务未同步'
  selectRecommendedStep()
}
function onPptGenerated(payload) {
  saveState.value = payload?.course_id && String(payload.course_id) !== String(courseId.value) ? `PPT 已生成到新课程 #${payload.course_id}，请通过对话框继续打开该课程。` : 'PPT 已生成，建议进入映射检查'
}

onMounted(() => { loadCourseContext(); loadVersions() })
</script>

<style scoped>
.production-workspace{min-height:100dvh;background:#f5f7fa;color:#1e293b}.workspace-header{min-height:64px;padding:10px 24px;background:#fff;border-bottom:1px solid #d9e1ea;display:flex;align-items:center;justify-content:space-between;gap:18px}.course-identity,.header-actions{display:flex;align-items:center;gap:12px}.back-button{width:40px;height:40px;border:1px solid #d9e1ea;border-radius:9px;background:#fff;color:#334155;display:grid;place-items:center;cursor:pointer}.breadcrumb,.eyebrow{margin:0;color:#64748b;font-size:12px}.workspace-header h1{font-size:18px;line-height:1.3;margin:3px 0 0}.workspace-header h1 span{font-weight:400;color:#64748b;font-size:13px}.course-meta{margin:3px 0 0;color:#64748b;font-size:12px}.save-state{color:#475569;font-size:13px;display:inline-flex;gap:6px;align-items:center}.primary,.secondary{min-height:38px;border-radius:8px;padding:0 12px;display:inline-flex;align-items:center;justify-content:center;gap:7px;cursor:pointer;font-size:13px;font-weight:600}.primary{background:#1769aa;border:1px solid #1769aa;color:#fff}.secondary{background:#fff;border:1px solid #cbd5e1;color:#334155}.primary:disabled,.secondary:disabled{opacity:.55;cursor:not-allowed}.context-error{max-width:1678px;margin:14px auto 0;padding:10px 14px;border:1px solid #fecaca;border-radius:9px;background:#fef2f2;color:#991b1b;display:flex;gap:8px;align-items:center;font-size:13px}.context-error button{margin-left:auto;border:0;background:transparent;color:#1769aa;text-decoration:underline;cursor:pointer}.workbench-grid{display:grid;grid-template-columns:220px minmax(0,1fr) 310px;gap:16px;padding:16px;max-width:1710px;margin:0 auto}.pipeline,.main-stage,.quality-panel{background:#fff;border:1px solid #d9e1ea;border-radius:12px}.pipeline{padding:12px;height:max-content}.pipeline-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:5px 9px 9px}.pipeline-step{width:100%;border:0;background:transparent;border-radius:8px;padding:10px 9px;display:grid;grid-template-columns:20px 1fr auto;gap:8px;align-items:center;text-align:left;color:#334155;cursor:pointer;font-size:13px}.pipeline-step:hover{background:#f1f5f9}.pipeline-step.active{background:#e8f1f8;color:#0b5f97;font-weight:700}.pipeline-step small{font-size:11px}.state-complete{color:#15803d}.state-review{color:#a16207}.state-ready{color:#1769aa}.state-pending{color:#64748b}.state-running{color:#1769aa}.state-blocked,.state-failed{color:#b91c1c}.main-stage{padding:24px;min-height:520px}.stage-heading,.split-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:1px solid #e2e8f0;padding-bottom:18px}.stage-heading h2{margin:5px 0;font-size:22px}.stage-heading p{margin:0;color:#64748b;font-size:14px;line-height:1.55}.heading-status{display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.status-chip,.course-status{padding:4px 8px;border-radius:999px;background:#f1f5f9;font-size:12px;font-weight:600;white-space:nowrap}.course-status.published{background:#dcfce7;color:#166534}.course-status.draft{background:#f1f5f9;color:#475569}.stage-panel{margin-top:28px;max-width:620px;min-height:270px;border:1px dashed #cbd5e1;border-radius:10px;padding:28px;display:flex;align-items:flex-start;justify-content:center;flex-direction:column;gap:12px;color:#475569}.stage-panel>svg{color:#1769aa}.stage-panel h3{color:#1e293b;margin:0;font-size:17px}.stage-panel p{margin:0;line-height:1.65;font-size:14px}.wide-panel{max-width:none;justify-content:flex-start}.integration-note{width:100%;box-sizing:border-box;margin:6px 0 0;padding:10px 12px;display:flex;gap:7px;align-items:flex-start;background:#f8fafc;border-left:3px solid #94a3b8;border-radius:6px;font-size:13px;line-height:1.55;color:#475569}.version-list{width:100%;list-style:none;padding:0;margin:4px 0 0;border-top:1px solid #e2e8f0}.version-list li{display:flex;justify-content:space-between;align-items:center;padding:13px 0;border-bottom:1px solid #e2e8f0}.version-list strong,.version-list small{display:block}.version-list small{font-size:12px;color:#64748b;margin-top:4px}.empty-state,.error-state{display:flex;align-items:center;justify-content:center;gap:8px;min-height:130px;color:#64748b;font-size:14px}.error-state{color:#b91c1c;justify-content:flex-start}.error-state button{border:0;background:none;color:#1769aa;text-decoration:underline;cursor:pointer}.spin{animation:spin 1s linear infinite}.quality-panel{padding:18px;height:max-content}.quality-title{display:flex;align-items:flex-start;gap:8px;color:#1e3a5f}.quality-title h2{font-size:16px;margin:0}.quality-title p{margin:3px 0 0;color:#64748b;font-size:12px}.checklist{list-style:none;padding:6px 0 0;margin:0}.checklist li{display:grid;grid-template-columns:18px 1fr;gap:8px;padding:13px 0;border-bottom:1px solid #edf2f7;font-size:13px}.checklist small{grid-column:2;color:#64748b;font-size:12px;line-height:1.45}.checklist .complete{color:#16a34a}.checklist .pending{color:#a16207}.checklist .blocked{color:#b91c1c}.review-action,.publish-summary,.notice{margin-top:14px;padding:12px;border-radius:8px;font-size:13px;line-height:1.5}.review-action{background:#fffbeb;border:1px solid #fde68a}.review-action p,.publish-summary p,.notice p{margin:0}.review-action p,.publish-summary{display:flex;gap:8px;align-items:flex-start}.full-width{width:100%;margin-top:10px}.publish-summary.ready{background:#f0fdf4;color:#166534}.publish-summary.blocked{background:#fef2f2;color:#991b1b}.notice{background:#eff6ff;color:#1e3a5f;display:flex;gap:8px}.notice p{font-size:12px}.publish-action{white-space:nowrap}@keyframes spin{to{transform:rotate(360deg)}}button:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}@media(prefers-reduced-motion:reduce){.spin{animation:none}}@media(max-width:1180px){.workbench-grid{grid-template-columns:200px minmax(0,1fr)}.quality-panel{grid-column:2}.header-actions .save-state{display:none}}@media(max-width:860px){.workspace-header{padding:10px 14px;align-items:flex-start;flex-direction:column}.header-actions{width:100%;justify-content:flex-end;flex-wrap:wrap}.workbench-grid{grid-template-columns:1fr;padding:10px}.pipeline{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px}.pipeline-label{grid-column:1/-1}.quality-panel{grid-column:auto}.main-stage{padding:18px}.stage-heading{flex-direction:column}.stage-panel{padding:20px}.context-error{margin:10px}}@media(max-width:480px){.header-actions{justify-content:stretch;min-width:0}.header-actions button{flex:1;min-width:0;white-space:normal;line-height:1.25}.secondary,.primary{font-size:12px;padding:0 8px}.pipeline{grid-template-columns:1fr}.integration-note{font-size:12px}.stage-panel{min-height:230px}.course-identity{align-items:flex-start}.workspace-header h1{font-size:16px}.course-meta{max-width:310px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.heading-status{justify-content:flex-start}}
</style>
