<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ChevronDown, ChevronUp, GripVertical, LockKeyhole, LockOpen, Save, Sparkles } from 'lucide-vue-next'
import { createOutlineNode, deleteOutlineNode, getOutline, lockOutlineNode, unlockOutlineNode, reorderOutline, runPrepAgentBatchAction, updateOutlineNode } from '@/api/course_editor.js'
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
const nodes = ref([])
const editable = ref(false)
const saving = ref('')
const selectedId = ref('')
const organizing = ref(false)
const deleting = ref(false)
const selected = computed(() => nodes.value.find((node) => node.outline_node_id === selectedId.value) ?? null)

// 智能体首次智慧备课进行中：解析材料 / 汇总语料 / 提交任务 / 构建中
// 这几个阶段下页面应提示"智能体首次智慧备课中"，避免教师误以为目录草稿缺失
const FIRST_PREP_PHASES = new Set(['parsing_materials', 'assembling_corpus', 'submitting_build', 'building'])
const isFirstPrepInProgress = computed(() => FIRST_PREP_PHASES.has(workbench?.draftBuildPhase))

function select(node) {
  selectedId.value = node.outline_node_id
  if (workbench) workbench.selectedNode = node
}
async function load() {
  state.value = 'loading'; error.value = ''
  try {
    const data = await getOutline(courseId.value)
    nodes.value = data?.nodes ?? []
    editable.value = Boolean(data?.editable)
    if (!nodes.value.some((node) => node.outline_node_id === selectedId.value)) selectedId.value = nodes.value[0]?.outline_node_id ?? ''
    if (workbench) workbench.selectedNode = selected.value
    state.value = 'ready'
  } catch (caught) { error.value = caught?.message || '课程结构读取失败'; state.value = 'error' }
}
async function save(node) {
  if (!editable.value || node.locked) return
  saving.value = node.outline_node_id
  try { await updateOutlineNode(courseId.value, node.outline_node_id, { title: node.title }) }
  catch (caught) { error.value = caught?.message || '节点保存失败' }
  finally { saving.value = '' }
}
async function toggleLock(node) {
  try {
    if (node.locked) {
      await unlockOutlineNode(courseId.value, node.outline_node_id); node.locked = false
    } else {
      await lockOutlineNode(courseId.value, node.outline_node_id); node.locked = true
    }
  } catch (caught) { error.value = caught?.message || '锁定操作失败' }
}
async function addNode() {
  try {
    const item = await createOutlineNode(courseId.value, { title: '新知识点', node_type: 'knowledge_point', order_index: nodes.value.length })
    nodes.value.push(item); select(item)
  } catch (caught) { error.value = caught?.message || '新增课程节点失败' }
}
async function deleteNode() {
  const node = selected.value
  if (!node || deleting.value) return
  deleting.value = true; error.value = ''
  try {
    await deleteOutlineNode(courseId.value, node.outline_node_id)
    const index = nodes.value.findIndex((n) => n.outline_node_id === node.outline_node_id)
    nodes.value.splice(index, 1)
    selectedId.value = nodes.value[Math.max(0, index - 1)]?.outline_node_id ?? ''
    if (workbench) workbench.selectedNode = selected.value
  } catch (caught) { error.value = caught?.message || '删除节点失败' }
  finally { deleting.value = false }
}
async function move(index, delta) {
  const targetIndex = index + delta
  if (targetIndex < 0 || targetIndex >= nodes.value.length || !editable.value) return
  const snapshot = [...nodes.value]
  ;[nodes.value[index], nodes.value[targetIndex]] = [nodes.value[targetIndex], nodes.value[index]]
  try { await reorderOutline(courseId.value, nodes.value.map((node) => node.outline_node_id)) }
  catch (caught) { nodes.value = snapshot; error.value = caught?.message || '调整顺序失败' }
}
async function organizeAll() {
  if (organizing.value || workbench?.batchRun) return
  if (isFirstPrepInProgress.value) return reportOrganizeUnavailable('首次智能备课仍在进行，课程结构生成后才能一键整理。')
  if (!editable.value) return reportOrganizeUnavailable('当前课程草稿不可编辑，无法一键整理结构。')
  if (!nodes.value.length) return reportOrganizeUnavailable('课程结构尚未生成，暂无可整理的节点。')
  if (!nodes.value.some((node) => !node.locked)) return reportOrganizeUnavailable('所有课程节点都已锁定；解锁至少一个节点后再整理。')
  organizing.value = true; error.value = ''
  const message = {
    role: 'agent',
    running: true,
    reason: '正在整理全部未锁定的课程节点，请勿发起其他智能优化。',
    changed: [],
  }
  if (workbench) {
    workbench.agentOpen = true
    workbench.batchRun = { action: 'organize_structure', startedAt: Date.now() }
    workbench.agentMessages.push(message)
  }
  try {
    const result = await runPrepAgentBatchAction(courseId.value, 'organize_structure')
    await load()
    Object.assign(message, {
      running: false,
      reason: result.summary || '课程结构已整理并直接应用。',
      changed: [`已更新 ${result.updated_count || 0} 个节点`],
      excluded: result.excluded_locked_targets || [],
      planner: result.planner,
    })
  } catch (caught) {
    error.value = apiErrorMessage(caught, '一键整理失败，请稍后重试')
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
function openAgent() {
  if (!workbench || workbench.batchRun) return
  workbench.agentOpen = true
  // 自动发送针对当前节点的调整指令
  const node = selected.value
  const nodeTitle = node?.title || '当前节点'
  const nodeId = node?.outline_node_id
  workbench.pendingInstruction = `请优化课程节点「${nodeTitle}」的标题，纠正不准确的 OCR 文本和用词，但不要修改其他节点或讲解脚本。`
  if (nodeId) workbench.pendingNodeId = nodeId
  workbench.pendingAgentAction = 'optimize_node_title'
}
function refreshAfterProposal() { load() }

// 通过 workbench.stageActions 把按钮操作暴露给 BuildLayout 的 stage-context
watch([editable, nodes, organizing, deleting, selectedId], () => {
  if (workbench) {
    workbench.stageActions = {
      canOrganize: editable.value && nodes.value.some((node) => !node.locked),
      organizing: organizing.value,
      canAdd: editable.value,
      canDelete: editable.value && Boolean(selected.value) && nodes.value.length > 0,
      deleting: deleting.value,
      onOrganize: organizeAll,
      organizeLabel: '一键整理结构',
      onAdd: addNode,
      onDelete: deleteNode,
    }
  }
}, { immediate: true })
onMounted(() => { load(); window.addEventListener('course-build-proposal-decided', refreshAfterProposal) })
onBeforeUnmount(() => { window.removeEventListener('course-build-proposal-decided', refreshAfterProposal); if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="structure-stage">
    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <div v-else-if="isFirstPrepInProgress && !nodes.length" class="first-prep-pending" role="status" aria-live="polite">
      <div class="first-prep-icon" aria-hidden="true"><Sparkles :size="26" :stroke-width="1.8" /></div>
      <h3>智能体首次智慧备课中</h3>
      <p>正在自动解析课程材料并整理目录结构，完成后可在此编辑。</p>
      <div class="first-prep-progress" aria-hidden="true"><span></span><span></span><span></span></div>
    </div>
    <div v-else-if="!nodes.length" class="empty-state">
      <Sparkles :size="22" />
      <strong>课程结构尚未生成</strong>
      <p>完成课程材料解析和首次智能备课后，目录草稿会出现在这里。</p>
    </div>
    <div v-else class="structure-workbench">
      <div class="outline-list" aria-label="课程结构目录">
        <button
          v-for="(node, index) in nodes"
          :key="node.outline_node_id"
          type="button"
          class="outline-row"
          :class="{ selected: selectedId === node.outline_node_id, locked: node.locked }"
          @click="select(node)"
        >
          <span class="outline-order">{{ node.display_number || String(index + 1).padStart(2, '0') }}</span>
          <GripVertical :size="16" class="drag-mark" aria-hidden="true" />
          <span class="outline-title" :style="{ paddingInlineStart: `${Math.min((node.depth || 0) * 12, 36)}px` }">{{ node.title }}</span>
          <LockKeyhole v-if="node.locked" :size="15" aria-label="已锁定" class="lock-icon" />
          <span v-else-if="node.source_block_refs?.length" class="evidence-count">{{ node.source_block_refs.length }} 条证据</span>
        </button>
      </div>

      <article v-if="selected" class="node-editor">
        <header>
          <div>
            <p class="node-type">{{ selected.node_type }} · {{ selected.display_number || `节点 ${nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) + 1}` }}</p>
            <h3>编辑课程节点</h3>
          </div>
          <SfxBadge :tone="selected.locked ? 'green' : 'amber'">{{ selected.locked ? '已锁定' : '可编辑' }}</SfxBadge>
        </header>
        <label>知识点名称<input v-model="selected.title" :disabled="!editable || selected.locked" @blur="save(selected)" /></label>
        <p v-if="selected.source_block_refs?.length" class="source-summary">已关联 {{ selected.source_block_refs.length }} 个原文区块；可在右侧助教面板的“节点来源”查看具体原文。</p>
        <p v-if="saving === selected.outline_node_id" class="saving"><Save :size="14" /> 正在保存更改</p>
        <div class="node-actions">
          <SfxButton variant="secondary" size="sm" :disabled="!editable || nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) === 0" @click="move(nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id), -1)"><ChevronUp :size="15" /> 上移</SfxButton>
          <SfxButton variant="secondary" size="sm" :disabled="!editable || nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) === nodes.length - 1" @click="move(nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id), 1)"><ChevronDown :size="15" /> 下移</SfxButton>
          <SfxButton v-if="!selected.locked" variant="secondary" size="sm" :disabled="!editable" @click="toggleLock(selected)"><LockKeyhole :size="15" /> 锁定节点</SfxButton>
          <SfxButton v-else variant="secondary" size="sm" @click="toggleLock(selected)"><LockOpen :size="15" /> 取消锁定</SfxButton>
          <SfxButton variant="tertiary" size="sm" :disabled="Boolean(workbench?.batchRun)" @click="openAgent"><Sparkles :size="15" /> 智能优化节点</SfxButton>
        </div>
        <p class="lock-note"><LockKeyhole :size="14" /> 锁定后，智能体优化时不会修改此节点。</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.structure-stage{display:flex;flex-direction:column;gap:0;padding:0;height:100%;overflow:hidden}
.structure-workbench{display:grid;grid-template-columns:minmax(280px,.95fr) minmax(320px,1.05fr);gap:var(--space-4);min-height:0;flex:1;overflow:hidden}
.outline-list{display:grid;align-content:start;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow-y:auto;min-height:0}
.outline-row{display:grid;grid-template-columns:26px 18px minmax(0,1fr) auto;gap:var(--space-2);align-items:center;min-height:52px;padding:0 var(--space-3);border:0;border-bottom:1px solid var(--border-subtle);background:var(--surface-panel);color:var(--text-primary);text-align:left;cursor:pointer;font:inherit;position:relative}
.outline-row:last-child{border-bottom:0}
.outline-row:hover{background:var(--surface-cool)}
.outline-row.selected{background:var(--ink-100);color:var(--ink-900)}
.outline-row.selected::before{position:absolute;left:0;top:var(--space-2);bottom:var(--space-2);width:3px;background:var(--ink-900);content:"";border-radius:var(--radius-full)}
.outline-row.locked{color:var(--text-secondary)}
.outline-order{font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:var(--caption-size);color:var(--text-muted)}
.drag-mark{color:var(--ink-300)}
.outline-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--ui-md-size);font-weight:var(--ui-md-weight)}
.lock-icon{color:var(--green-700);flex-shrink:0}
.evidence-count{font-size:var(--caption-size);color:var(--ink-500);white-space:nowrap}
.node-editor{display:grid;align-content:start;gap:var(--space-3);padding:var(--space-4);border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--surface-canvas);overflow-y:auto;min-height:0}
.node-editor header{display:flex;justify-content:space-between;gap:var(--space-2);align-items:flex-start}
.node-type{margin:0;color:var(--text-muted);font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:var(--caption-size)}
.node-editor h3{margin:var(--space-1) 0 0;color:var(--text-primary);font-size:var(--title-3-size)}
.node-editor label{display:grid;gap:var(--space-1);color:var(--text-secondary);font-size:var(--ui-sm-size);font-weight:600}
.node-editor input{height:40px;box-sizing:border-box;padding:0 var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);outline:none;background:var(--surface-panel);color:var(--text-primary);font:inherit;font-size:var(--body-md-size)}
.node-editor input:focus{border-color:var(--ink-500);box-shadow:0 0 0 2px var(--ink-100)}
.node-editor input:disabled{background:var(--surface-cool);color:var(--text-secondary)}
.source-summary{margin:0;padding:var(--space-3);border-left:3px solid var(--ink-500);border-radius:0 var(--radius-sm) var(--radius-sm) 0;background:var(--surface-cool);color:var(--text-secondary);font-size:var(--caption-size);line-height:1.5;overflow-wrap:anywhere}
.saving,.lock-note{display:flex;align-items:center;gap:var(--space-1);margin:0;color:var(--text-muted);font-size:var(--caption-size)}
.node-actions{display:flex;flex-wrap:wrap;gap:var(--space-3);padding-top:var(--space-1)}.node-actions :deep(.sfx-btn-label){display:inline-flex;align-items:center;gap:var(--space-2)}
.lock-note{padding-top:var(--space-2);border-top:1px solid var(--border-default)}
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
@media(max-width:880px){.structure-workbench{grid-template-columns:1fr;overflow:visible}.outline-list{max-height:300px;overflow-y:auto}}
@media(max-width:560px){.structure-stage{padding:var(--space-3)}.outline-row{padding:0 var(--space-2)}.evidence-count{display:none}.node-actions :deep(.sfx-btn){flex:1}}
</style>
