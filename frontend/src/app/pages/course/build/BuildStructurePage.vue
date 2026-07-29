<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ChevronDown, ChevronUp, GripVertical, LockKeyhole, Plus, Save, Sparkles } from 'lucide-vue-next'
import { createOutlineNode, getOutline, lockOutlineNode, reorderOutline, updateOutlineNode } from '@/api/course_editor.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const state = ref('loading')
const error = ref('')
const nodes = ref([])
const editable = ref(false)
const saving = ref('')
const selectedId = ref('')
const selected = computed(() => nodes.value.find((node) => node.outline_node_id === selectedId.value) ?? null)

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
async function lock(node) {
  if (node.locked) return
  try { await lockOutlineNode(courseId.value, node.outline_node_id); node.locked = true }
  catch (caught) { error.value = caught?.message || '锁定节点失败' }
}
async function addNode() {
  try {
    const item = await createOutlineNode(courseId.value, { title: '新知识点', node_type: 'knowledge_point', order_index: nodes.value.length })
    nodes.value.push(item); select(item)
  } catch (caught) { error.value = caught?.message || '新增课程节点失败' }
}
async function move(index, delta) {
  const targetIndex = index + delta
  if (targetIndex < 0 || targetIndex >= nodes.value.length || !editable.value) return
  const snapshot = [...nodes.value]
  ;[nodes.value[index], nodes.value[targetIndex]] = [nodes.value[targetIndex], nodes.value[index]]
  try { await reorderOutline(courseId.value, nodes.value.map((node) => node.outline_node_id)) }
  catch (caught) { nodes.value = snapshot; error.value = caught?.message || '调整顺序失败' }
}
function openAgent() { if (workbench) workbench.agentOpen = true }
function refreshAfterProposal() { load() }
onMounted(() => { load(); window.addEventListener('course-build-proposal-decided', refreshAfterProposal) })
onBeforeUnmount(() => window.removeEventListener('course-build-proposal-decided', refreshAfterProposal))
</script>

<template>
  <section class="structure-stage">
    <header class="section-toolbar">
      <div><h2>课程结构草稿</h2><p>材料解析提供候选；备课 Agent 组织建议；只有教师确认的调整才会写入草稿。</p></div>
      <SfxButton :disabled="!editable" @click="addNode"><Plus :size="16" /> 新增节点</SfxButton>
    </header>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <div v-else-if="!nodes.length" class="empty-state"><Sparkles :size="22" /><strong>课程结构尚未生成</strong><p>完成课程材料解析和首次智能备课后，目录草稿会出现在这里。</p></div>
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
          <span class="outline-order">{{ String(index + 1).padStart(2, '0') }}</span>
          <GripVertical :size="16" class="drag-mark" aria-hidden="true" />
          <span class="outline-title">{{ node.title }}</span>
          <LockKeyhole v-if="node.locked" :size="15" aria-label="已锁定" />
          <span v-else-if="node.source_block_refs?.length" class="evidence-count">{{ node.source_block_refs.length }} 条证据</span>
        </button>
      </div>

      <article v-if="selected" class="node-editor">
        <header><div><p class="node-type">{{ selected.node_type }} · 节点 {{ nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) + 1 }}</p><h3>编辑课程节点</h3></div><SfxBadge :tone="selected.locked ? 'green' : 'amber'">{{ selected.locked ? '已锁定' : '可编辑' }}</SfxBadge></header>
        <label>知识点名称<input v-model="selected.title" :disabled="!editable || selected.locked" @blur="save(selected)" /></label>
        <p v-if="selected.source_block_refs?.length" class="source-summary">关联原文区块：{{ selected.source_block_refs.join('、') }}</p>
        <p v-if="saving === selected.outline_node_id" class="saving"><Save :size="14" /> 正在保存更改</p>
        <div class="node-actions">
          <SfxButton variant="secondary" size="sm" :disabled="!editable || nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) === 0" @click="move(nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id), -1)"><ChevronUp :size="15" /> 上移</SfxButton>
          <SfxButton variant="secondary" size="sm" :disabled="!editable || nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id) === nodes.length - 1" @click="move(nodes.findIndex((node) => node.outline_node_id === selected.outline_node_id), 1)"><ChevronDown :size="15" /> 下移</SfxButton>
          <SfxButton v-if="!selected.locked" variant="secondary" size="sm" :disabled="!editable" @click="lock(selected)"><LockKeyhole :size="15" /> 锁定节点</SfxButton>
          <SfxButton variant="tertiary" size="sm" @click="openAgent"><Sparkles :size="15" /> 让 Agent 调整</SfxButton>
        </div>
        <p class="lock-note"><LockKeyhole :size="14" /> 锁定后不会进入后续 Agent 的可修改集合。</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.structure-stage{display:grid;gap:var(--space-4);padding:var(--space-5);background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-lg)}.section-toolbar{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-4);padding-bottom:var(--space-4);border-bottom:1px solid var(--border-default)}.section-toolbar h2{margin:0;color:var(--text-primary);font-size:var(--title-3-size)}.section-toolbar p{max-width:680px;margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.structure-workbench{display:grid;grid-template-columns:minmax(280px,.95fr) minmax(320px,1.05fr);gap:var(--space-4)}.outline-list{display:grid;align-content:start;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow:hidden}.outline-row{display:grid;grid-template-columns:26px 18px minmax(0,1fr) auto;gap:var(--space-2);align-items:center;min-height:52px;padding:0 var(--space-3);border:0;border-bottom:1px solid var(--border-subtle);background:var(--surface-panel);color:var(--text-primary);text-align:left;cursor:pointer;font:inherit}.outline-row:last-child{border-bottom:0}.outline-row:hover{background:var(--surface-cool)}.outline-row.selected{background:var(--ink-100);box-shadow:inset 3px 0 var(--ink-700)}.outline-row.locked{color:var(--text-secondary)}.outline-order{font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:11px;color:var(--text-muted)}.drag-mark{color:var(--ink-300)}.outline-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--ui-md-size);font-weight:550}.evidence-count{font-size:var(--caption-size);color:var(--ink-500);white-space:nowrap}.node-editor{display:grid;align-content:start;gap:var(--space-3);padding:var(--space-4);border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--surface-canvas)}.node-editor header{display:flex;justify-content:space-between;gap:var(--space-2);align-items:flex-start}.node-type{margin:0;color:var(--text-muted);font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:11px}.node-editor h3{margin:var(--space-1) 0 0;color:var(--text-primary);font-size:var(--title-3-size)}.node-editor label{display:grid;gap:var(--space-1);color:var(--text-secondary);font-size:var(--ui-sm-size);font-weight:600}.node-editor input{height:40px;box-sizing:border-box;padding:0 var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);outline:none;background:var(--surface-panel);color:var(--text-primary);font:inherit;font-size:var(--body-md-size)}.node-editor input:focus{border-color:var(--ink-500);box-shadow:0 0 0 2px var(--ink-100)}.node-editor input:disabled{background:var(--surface-cool);color:var(--text-secondary)}.source-summary{margin:0;padding:var(--space-3);border-left:3px solid var(--ink-500);border-radius:0 var(--radius-sm) var(--radius-sm) 0;background:var(--surface-cool);color:var(--text-secondary);font-size:var(--caption-size);line-height:1.5;overflow-wrap:anywhere}.saving,.lock-note{display:flex;align-items:center;gap:var(--space-1);margin:0;color:var(--text-muted);font-size:var(--caption-size)}.node-actions{display:flex;flex-wrap:wrap;gap:var(--space-2);padding-top:var(--space-1)}.lock-note{padding-top:var(--space-2);border-top:1px solid var(--border-default)}.empty-state{display:grid;justify-items:center;gap:var(--space-2);padding:var(--space-12) var(--space-5);color:var(--text-muted);text-align:center}.empty-state strong{color:var(--text-primary);font-size:var(--title-3-size)}.empty-state p{max-width:440px;margin:0;font-size:var(--ui-md-size);line-height:1.6}
@media(max-width:880px){.structure-workbench{grid-template-columns:1fr}.outline-list{max-height:300px;overflow:auto}}@media(max-width:560px){.structure-stage{padding:var(--space-3)}.section-toolbar{align-items:stretch;flex-direction:column}.section-toolbar :deep(.sfx-btn){width:100%}.outline-row{padding:0 var(--space-2)}.evidence-count{display:none}.node-actions :deep(.sfx-btn){flex:1}}
</style>
