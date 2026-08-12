<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, LockKeyhole, LockOpen, Save, Sparkles } from 'lucide-vue-next'
import { createTeachingScript, getOutline, getTeachingScripts, lockTeachingScript, runPrepAgentBatchAction, unlockTeachingScript, updateTeachingScript } from '@/api/course_editor.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const state = ref('loading')
const error = ref('')
const items = ref([])
const editable = ref(false)
const selectedId = ref('')
const saving = ref('')
const organizing = ref(false)
const selected = computed(() => items.value.find((item) => item.script_node_id === selectedId.value) ?? null)
const outlineLabel = (item) => item?.outline_node?.display_label || item?.display_label || item?.outline_title || '未关联课程节点'
const scriptStatus = (item) => {
  if (item.has_script) return item.locked ? '已锁定' : `${outlineBreadcrumb(item)} · 草稿可编辑`
  if (item.coverage_issue?.code === 'EVIDENCE_VERIFICATION_FAILED') return '证据校验未通过，待手工补齐'
  if (item.coverage_issue?.code === 'SCRIPT_OUTPUT_MISSING') return '模型未返回讲稿，待手工补齐'
  return '讲稿尚未生成'
}
const outlineBreadcrumb = (item) => {
  const breadcrumb = item?.outline_node?.breadcrumb || item?.breadcrumb || []
  return breadcrumb.length > 1 ? breadcrumb.slice(0, -1).join(' / ') : '课程结构'
}

// 智能体首次智慧备课进行中：解析材料 / 汇总语料 / 提交任务 / 构建中
const FIRST_PREP_PHASES = new Set(['parsing_materials', 'assembling_corpus', 'submitting_build', 'building'])
const isFirstPrepInProgress = computed(() => FIRST_PREP_PHASES.has(workbench?.draftBuildPhase))

function select(item) {
  selectedId.value = item.script_node_id
  // The shared assistant scopes single-node actions by outline_node_id, not
  // the script row's own ID.  Keep the layout-level selection synchronized so
  // opening the assistant from a lecture-script row always carries its target.
  if (workbench) workbench.selectedNode = item.outline_node || null
}
async function load() {
  state.value = 'loading'; error.value = ''
  try {
    // Load the outline first.  For legacy courses that only have a published
    // version, this request seeds the teacher's next editable draft; scripts
    // must then read that same draft instead of racing a second copy request.
    const outlineData = await getOutline(courseId.value)
    const data = await getTeachingScripts(courseId.value)
    const outlineById = new Map((outlineData?.nodes ?? []).map((node) => [node.outline_node_id, node]))
    // The course structure is authoritative for numbering and titles.  The
    // scripts endpoint remains the source of editable content, but its
    // denormalized display fields must never win over the current outline.
    const scriptByOutline = new Map((data?.items ?? []).map((item) => [item.outline_node_id, item]))
    const issueByOutline = new Map((data?.coverage_issues ?? []).map((issue) => [issue.outline_node_id, issue]))
    const knowledgeNodes = (outlineData?.nodes ?? []).filter((node) => (
      String(node.node_type || '').toLowerCase() === 'knowledge_point'
    ))
    // Render the complete structure tree. A missing script is a visible
    // coverage gap, not a reason to drop that knowledge point from the page.
    items.value = knowledgeNodes.map((outlineNode) => {
      const script = scriptByOutline.get(outlineNode.outline_node_id)
      return {
        ...(script || {
          script_node_id: `missing:${outlineNode.outline_node_id}`,
          content: '',
          style: 'beginner',
          locked: false,
        }),
        has_script: Boolean(script),
        coverage_issue: issueByOutline.get(outlineNode.outline_node_id) ?? null,
        // 无讲稿节点走 fallback 分支时不会展开后端 script 字段；
        // 补齐讲稿（createTeachingScript）依赖 outline_node_id，必须显式提供。
        outline_node_id: outlineNode.outline_node_id,
        outline_node: outlineNode,
        outline_title: outlineNode.title,
        display_number: outlineNode.display_number,
        display_label: outlineNode.display_label,
        breadcrumb: outlineNode.breadcrumb,
      }
    })
    editable.value = Boolean(data?.editable)
    if (!items.value.some((item) => item.script_node_id === selectedId.value)) selectedId.value = items.value[0]?.script_node_id ?? ''
    if (workbench) workbench.selectedNode = selected.value?.outline_node || null
    state.value = 'ready'
  } catch (caught) { error.value = caught?.message || '讲稿读取失败'; state.value = 'error' }
}
async function save(item) {
  if (!editable.value || item.locked || !item.has_script) return
  saving.value = item.script_node_id
  try { await updateTeachingScript(courseId.value, item.script_node_id, { content: item.content, style: item.style }) }
  catch (caught) { error.value = caught?.message || '讲稿保存失败' }
  finally { saving.value = '' }
}
async function createMissingScript(item) {
  if (!editable.value || item.locked || item.has_script) return
  const content = item.content.trim()
  if (!content) {
    error.value = '请先填写非空讲稿，再保存。'
    return
  }
  saving.value = item.script_node_id
  try {
    await createTeachingScript(courseId.value, {
      outline_node_id: item.outline_node_id,
      content,
      style: item.style.trim() || 'beginner',
    })
    const outlineNodeId = item.outline_node_id
    await load()
    selectedId.value = items.value.find((candidate) => candidate.outline_node_id === outlineNodeId)?.script_node_id ?? ''
  } catch (caught) { error.value = caught?.message || '讲稿补齐失败' }
  finally { saving.value = '' }
}
async function lock(item) {
  if (!item.has_script) return
  try { await lockTeachingScript(courseId.value, item.script_node_id); item.locked = true }
  catch (caught) { error.value = caught?.message || '锁定讲稿失败' }
}
async function unlock(item) {
  if (!editable.value || !item.has_script) return
  try { await unlockTeachingScript(courseId.value, item.script_node_id); item.locked = false }
  catch (caught) { error.value = caught?.message || '取消锁定讲稿失败' }
}
function openAgent(customInstruction) {
  if (!workbench || workbench.batchRun) return
  workbench.agentOpen = true
  if (customInstruction) {
    workbench.pendingInstruction = customInstruction
  }
}
function openAgentForNode() {
  const node = selected.value
  if (workbench) {
    workbench.pendingNodeId = node?.outline_node_id || null
    workbench.pendingAgentAction = 'optimize_node_script'
  }
  openAgent(`请针对讲稿节点「${outlineLabel(node)}」的内容和风格提出润色建议，使其更符合教学表达规范。`)
}
async function organizeAll() {
  if (organizing.value || workbench?.batchRun) return
  if (isFirstPrepInProgress.value) return reportOrganizeUnavailable('首次智能备课仍在进行，讲解脚本生成后才能统一优化。')
  if (!editable.value) return reportOrganizeUnavailable('当前课程草稿不可编辑，无法一键优化讲解。')
  if (!items.value.length) return reportOrganizeUnavailable('讲解脚本尚未生成，暂无可优化的内容。')
  if (!items.value.some((item) => item.has_script && !item.locked)) return reportOrganizeUnavailable('没有可优化的未锁定讲稿；请先生成讲稿或解锁一个节点。')
  organizing.value = true; error.value = ''
  const userMessage = {
    role: 'user',
    text: '一键优化全部未锁定讲解脚本，并授权完成后直接应用。',
    source: 'quick_action',
    action: 'optimize_all_scripts',
    executionMode: 'immediate_apply',
  }
  const message = {
    role: 'agent',
    running: true,
    reason: '正在统一优化全部未锁定讲稿的讲解节奏，请勿发起其他智能优化。',
    proposalId: null,
    proposalStatus: null,
  }
  if (workbench) {
    workbench.agentOpen = true
    workbench.agentMessages.push(userMessage)
    workbench.batchRun = { action: 'optimize_all_scripts', startedAt: Date.now() }
    workbench.agentMessages.push(message)
  }
  try {
    const result = await runPrepAgentBatchAction(courseId.value, 'optimize_all_scripts')
    await load()
    Object.assign(message, {
      running: false,
      reason: result.summary || '讲稿优化已完成并直接应用。',
      changeSummary: result.change_summary ?? null,
      proposalId: result.proposal_id ?? null,
      proposalStatus: result.change_summary?.state ?? null,
      excluded: result.excluded_locked_targets || [],
      planner: result.planner,
    })
  } catch (caught) {
    error.value = apiErrorMessage(caught, '一键优化讲解失败，请稍后重试')
    Object.assign(message, { running: false, error: true, reason: error.value })
  } finally {
    if (workbench) workbench.batchRun = null
    organizing.value = false
  }
}
function reportOrganizeUnavailable(reason) {
  error.value = reason
  if (!workbench) return
  workbench.agentOpen = true
  workbench.agentMessages.push({ role: 'agent', error: true, reason })
}
function refreshAfterProposal() { load() }

watch([editable, items, organizing], () => {
  if (workbench) {
    workbench.stageActions = {
      canOrganize: editable.value && items.value.some((item) => item.has_script && !item.locked),
      organizing: organizing.value,
      onOrganize: organizeAll,
      organizeLabel: '一键优化讲解',
    }
  }
}, { immediate: true })
onMounted(() => { load(); window.addEventListener('course-build-proposal-decided', refreshAfterProposal) })
onBeforeUnmount(() => { window.removeEventListener('course-build-proposal-decided', refreshAfterProposal); if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="scripts-stage">
    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <div v-else-if="isFirstPrepInProgress && !items.length" class="first-prep-pending" role="status" aria-live="polite">
      <div class="first-prep-icon" aria-hidden="true"><Sparkles :size="26" :stroke-width="1.8" /></div>
      <h3>智能体首次智慧备课中</h3>
      <p>正在自动解析课程材料并生成讲稿草稿，完成后可在此审核和编辑。</p>
      <div class="first-prep-progress" aria-hidden="true"><span></span><span></span><span></span></div>
    </div>
    <div v-else-if="!items.length" class="empty-state"><Sparkles :size="22" /><strong>讲授脚本尚未生成</strong><p>先确认课程结构并完成首次智能备课，系统才会生成可审核的讲稿草稿。</p></div>
    <div v-else class="scripts-workbench">
      <div class="script-list" aria-label="讲稿节点列表">
        <button v-for="item in items" :key="item.script_node_id" class="script-row" :class="{ selected: selectedId === item.script_node_id, issue: !item.has_script && item.coverage_issue }" type="button" @click="select(item)">
          <span><strong>{{ outlineLabel(item) }}</strong><small>{{ scriptStatus(item) }}</small></span><LockKeyhole v-if="item.locked" :size="15" />
        </button>
      </div>
      <article v-if="selected" class="script-editor">
        <header><div><p>关联目录节点 · {{ outlineBreadcrumb(selected) }}</p><h3>{{ outlineLabel(selected) }}</h3></div><SfxBadge :tone="selected.locked ? 'green' : selected.coverage_issue ? 'red' : 'amber'">{{ selected.locked ? '已锁定' : selected.coverage_issue ? '待补齐' : '草稿' }}</SfxBadge></header>
        <div v-if="!selected.has_script" class="missing-script" :class="{ failed: selected.coverage_issue }">
          <AlertTriangle v-if="selected.coverage_issue" :size="18" aria-hidden="true" />
          <div>
            <strong v-if="selected.coverage_issue?.code === 'EVIDENCE_VERIFICATION_FAILED'">未保留未验证讲稿</strong>
            <strong v-else-if="selected.coverage_issue?.code === 'SCRIPT_OUTPUT_MISSING'">模型未返回该知识点讲稿</strong>
            <strong v-else>当前讲稿版本尚未覆盖该知识点</strong>
            <p v-if="selected.coverage_issue">系统保留了已通过校验的其他讲稿；请教师依据当前知识点来源材料手工补齐。本操作不会再次调用智能体。</p>
            <p v-else>请手工补齐讲稿后再继续课程建设。</p>
          </div>
        </div>
        <label>讲授脚本<textarea v-model="selected.content" :disabled="!editable || selected.locked" @blur="selected.has_script && save(selected)" /></label>
        <label>讲解风格<input v-model="selected.style" :disabled="!editable || selected.locked" placeholder="例如：面向大一学生，循序解释" @blur="selected.has_script && save(selected)" /></label>
        <p v-if="saving === selected.script_node_id" class="saving"><Save :size="14" /> 正在保存讲稿</p>
        <div class="script-actions">
          <SfxButton v-if="!selected.has_script" variant="primary" size="sm" :disabled="!editable || selected.locked || !selected.content.trim()" :loading="saving === selected.script_node_id" @click="createMissingScript(selected)"><Save :size="15" /> 保存讲稿</SfxButton>
          <SfxButton v-if="selected.has_script && !selected.locked" variant="secondary" size="sm" :disabled="!editable" @click="lock(selected)"><LockKeyhole :size="15" /> 锁定讲稿</SfxButton>
          <SfxButton v-else-if="selected.has_script" variant="secondary" size="sm" :disabled="!editable" @click="unlock(selected)"><LockOpen :size="15" /> 取消锁定</SfxButton>
          <SfxButton v-if="selected.has_script" variant="tertiary" size="sm" :disabled="Boolean(workbench?.batchRun)" @click="openAgentForNode"><Sparkles :size="15" /> 智能优化讲解</SfxButton>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.scripts-stage{display:flex;flex-direction:column;gap:0;padding:0;height:100%;overflow:hidden}
.scripts-workbench{display:grid;grid-template-columns:minmax(220px,.7fr) minmax(360px,1.3fr);gap:var(--space-4);min-height:0;flex:1;overflow:hidden}
.script-list{display:grid;align-content:start;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow-y:auto;min-height:0}
.script-row{display:flex;justify-content:space-between;align-items:center;gap:var(--space-2);min-height:58px;padding:0 var(--space-3);border:0;border-bottom:1px solid var(--border-subtle);background:var(--surface-panel);color:var(--text-primary);text-align:left;cursor:pointer;font:inherit;position:relative}
.script-row:last-child{border-bottom:0}
.script-row:hover{background:var(--surface-cool)}
.script-row.selected{background:var(--ink-100);color:var(--ink-900)}
.script-row.issue small{color:var(--red-700)}
.script-row.selected::before{position:absolute;left:0;top:var(--space-2);bottom:var(--space-2);width:3px;background:var(--ink-900);content:"";border-radius:var(--radius-full)}
.script-row span{display:grid;gap:2px}
.script-row strong{font-size:var(--ui-sm-size);font-weight:600;line-height:1.35}
.script-row small{font-size:var(--caption-size);color:var(--text-muted)}
.script-editor{display:grid;gap:var(--space-3);padding:var(--space-4);border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--surface-canvas);overflow-y:auto;min-height:0}
.script-editor header{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2)}
.script-editor header p{margin:0;color:var(--text-muted);font-size:var(--caption-size)}
.script-editor header h3{margin:var(--space-1) 0 0;color:var(--text-primary);font-size:var(--ui-md-size)}
.script-editor label{display:grid;gap:var(--space-1);color:var(--text-secondary);font-size:var(--ui-sm-size);font-weight:600}
.script-editor textarea,.script-editor input{box-sizing:border-box;width:100%;border:1px solid var(--border-default);border-radius:var(--radius-md);outline:none;background:var(--surface-panel);color:var(--text-primary);font:inherit}
.script-editor textarea{min-height:280px;padding:var(--space-3);font-size:var(--body-md-size);line-height:var(--body-md-line);resize:vertical}
.script-editor input{height:40px;padding:0 var(--space-3);font-size:var(--ui-md-size)}
.script-editor textarea:focus,.script-editor input:focus{border-color:var(--ink-500);box-shadow:0 0 0 2px var(--ink-100)}
.script-editor textarea:disabled,.script-editor input:disabled{background:var(--surface-cool);color:var(--text-secondary)}
.saving{display:flex;align-items:center;gap:var(--space-1);margin:0;color:var(--text-muted);font-size:var(--caption-size)}
.script-actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}
.empty-state{display:grid;justify-items:center;gap:var(--space-2);padding:var(--space-12) var(--space-5);color:var(--text-muted);text-align:center}
.empty-state strong{color:var(--text-primary);font-size:var(--title-3-size)}
.empty-state p{max-width:440px;margin:0;font-size:var(--ui-md-size);line-height:1.6}
.first-prep-pending{display:grid;justify-items:center;gap:var(--space-3);padding:var(--space-12) var(--space-5);color:var(--text-secondary);text-align:center}
.first-prep-pending h3{margin:0;color:var(--text-primary);font-size:var(--title-3-size);font-weight:var(--title-3-weight)}
.first-prep-pending p{max-width:440px;margin:0;font-size:var(--ui-md-size);line-height:1.6}
.first-prep-icon{width:56px;height:56px;border-radius:var(--radius-full);background:var(--ink-100);color:var(--ink-700);display:flex;align-items:center;justify-content:center;animation:first-prep-pulse 1.6s ease-in-out infinite}
.first-prep-progress{display:flex;gap:var(--space-2)}
.first-prep-progress span{width:8px;height:8px;border-radius:var(--radius-full);background:var(--ink-500);opacity:.4;animation:first-prep-bounce 1.2s ease-in-out infinite}
.first-prep-progress span:nth-child(2){animation-delay:.15s}
.first-prep-progress span:nth-child(3){animation-delay:.3s}
@keyframes first-prep-pulse{0%,100%{transform:scale(1);opacity:.85}50%{transform:scale(1.06);opacity:1}}
@keyframes first-prep-bounce{0%,100%{transform:translateY(0);opacity:.4}50%{transform:translateY(-6px);opacity:1}}
.missing-script{display:flex;gap:var(--space-2);padding:var(--space-4);border:1px dashed var(--border-default);border-radius:var(--radius-md);background:var(--surface-cool);color:var(--text-muted);line-height:1.6}
.missing-script.failed{border-style:solid;border-color:var(--red-300);background:var(--red-100);color:var(--red-700)}
.missing-script strong{display:block;color:var(--text-primary)}
.missing-script.failed strong{color:var(--red-700)}
.missing-script p{margin:var(--space-1) 0 0}
@media(max-width:880px){.scripts-workbench{grid-template-columns:1fr;overflow:visible}.script-list{max-height:260px;overflow:auto}}
@media(max-width:560px){.scripts-stage{padding:var(--space-3)}.script-editor{padding:var(--space-3)}.script-actions :deep(.sfx-btn){flex:1}}
</style>
