<template>
  <main class="course-workbench">
    <header class="workbench-header">
      <div>
        <p class="eyebrow">课程建设 / 教师审核空间</p>
        <h1>课程结构与讲稿</h1>
      </div>
      <div class="header-actions">
        <span class="save-state" aria-live="polite">{{ statusText }}</span>
        <button type="button" class="secondary" @click="reload" :disabled="loading"><RefreshCw :size="16" />刷新</button>
        <button type="button" class="primary" @click="agentOpen = true"><Sparkles :size="16" />备课 Agent</button>
      </div>
    </header>

    <nav class="mobile-panels" aria-label="工作台面板">
      <button v-for="panel in panels" :key="panel.id" type="button" :class="{ active: mobilePanel === panel.id }" @click="mobilePanel = panel.id">{{ panel.label }}</button>
    </nav>

    <section class="workbench-grid" :class="`panel-${mobilePanel}`">
      <aside class="outline-pane panel" aria-label="课程树">
        <div class="panel-heading"><div><p>课程树</p><small>{{ outlineNodes.length }} 个节点</small></div></div>
        <div v-if="loading" class="state">正在读取课程结构…</div>
        <div v-else-if="!outlineNodes.length" class="state">首次智能备课尚未生成课程树。</div>
        <div v-else class="tree" role="tree">
          <button v-for="node in outlineNodes" :key="node.outline_node_id" type="button" class="tree-node" :class="{ active: selectedNodeId === node.outline_node_id }" :style="{ paddingLeft: `${12 + node.depth * 18}px` }" @click="selectNode(node)">
            <span class="node-dot" :class="node.node_type"></span><span>{{ node.title }}</span><LockKeyhole v-if="node.locked" :size="14" aria-label="已锁定" />
          </button>
        </div>
      </aside>

      <section class="editor-pane panel" aria-label="知识点与讲稿编辑">
        <div v-if="!selectedNode" class="state">从左侧选择一个知识点开始编辑。</div>
        <template v-else>
          <div class="panel-heading"><div><p>{{ selectedNode.node_type === 'knowledge_point' ? '知识点' : '课程节点' }}</p><small>{{ selectedNode.locked ? '教师已锁定，Agent 不会修改' : '可直接编辑，也可请求 Agent 生成提案' }}</small></div><button type="button" class="secondary" :disabled="selectedNode.locked || lockLoading" @click="lockSelected"><LockKeyhole :size="15" />{{ selectedNode.locked ? '已锁定' : '锁定节点' }}</button></div>
          <label class="field-label" for="node-title">节点名称</label>
          <input id="node-title" v-model="draftTitle" :disabled="selectedNode.locked" class="title-input" />
          <label class="field-label" for="script-content">讲稿</label>
          <textarea id="script-content" v-model="draftScript" :disabled="selectedScript?.locked" class="script-input" placeholder="该节点尚无讲稿；可让备课 Agent 提出补充建议。"></textarea>
          <div class="editor-actions"><button type="button" class="primary" :disabled="saving || (selectedNode.locked && selectedScript?.locked)" @click="save"><Save :size="16" />{{ saving ? '保存中…' : '保存教师修改' }}</button><button type="button" class="secondary" @click="agentOpen = true"><MessageSquareText :size="16" />让 Agent 修改</button></div>
        </template>
      </section>

      <aside class="evidence-pane panel" aria-label="原文证据与 Agent 对话">
        <div class="panel-heading"><div><p>原文证据</p><small>只展示当前课程材料中的来源</small></div></div>
        <div v-if="evidenceLoading" class="state">读取原文证据…</div>
        <div v-else-if="evidence.length" class="evidence-list"><article v-for="item in evidence" :key="item.block_id" class="evidence-card"><small>第 {{ item.page || '?' }} 页 · {{ item.source_kind || '解析文本' }}</small><p>{{ item.text }}</p></article></div>
        <div v-else class="state compact">选择课程节点后显示其原文证据。</div>
        <div class="proposal-heading"><p>待审核提案</p><small>{{ proposals.length }} 项</small></div>
        <div class="proposal-list"><article v-for="proposal in proposals" :key="proposal.proposal_id" class="proposal-card"><strong>{{ proposal.reason }}</strong><small>{{ proposal.operations?.length || 0 }} 项修改</small><p v-for="op in proposal.operations?.slice(0, 2)" :key="op.op_id">{{ op.target }}：{{ op.reason }}</p><div v-if="proposal.status === 'pending'" class="proposal-actions"><button type="button" class="accept" @click="decide(proposal, true)">接受</button><button type="button" class="reject" @click="decide(proposal, false)">拒绝</button></div><small v-else>已{{ proposal.status === 'accepted' ? '接受' : '处理' }}</small></article></div>
      </aside>
    </section>

    <section v-if="agentOpen" class="agent-popover" role="dialog" aria-modal="true" aria-labelledby="agent-title">
      <div class="agent-heading"><div><p>受控备课 Agent</p><h2 id="agent-title">把教学意图说给我听</h2></div><button type="button" class="icon-button" aria-label="关闭备课 Agent" @click="agentOpen = false"><X :size="18" /></button></div>
      <p class="agent-note">我只读取当前课程语料，并把建议保存为待审核提案。已锁定的目录和讲稿不会进入修改范围。</p>
      <label class="field-label" for="agent-instruction">备课指令</label>
      <textarea id="agent-instruction" v-model="instruction" class="agent-input" placeholder="例如：把第二章讲得更适合大一学生，并补一个生活化例子。"></textarea>
      <p v-if="agentFeedback" class="agent-feedback" aria-live="polite">{{ agentFeedback }}</p>
      <div class="agent-actions"><button type="button" class="secondary" @click="agentOpen = false">稍后再说</button><button type="button" class="primary" :disabled="agentLoading || instruction.trim().length < 2" @click="sendAgent"><Sparkles :size="16" />{{ agentLoading ? '正在形成提案…' : '生成待审核提案' }}</button></div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { LockKeyhole, MessageSquareText, RefreshCw, Save, Sparkles, X } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { decideBuildProposal, getOutline, getPrepAgentNodeEvidence, getTeachingScripts, listBuildProposals, lockOutlineNode, lockTeachingScript, runPrepAgentCommand, updateOutlineNode, updateTeachingScript } from '@/api/course_editor.js'
import { showToast } from '@/utils/toast.js'

const route = useRoute()
const courseId = computed(() => route.params.courseId)
const loading = ref(false); const saving = ref(false); const lockLoading = ref(false); const evidenceLoading = ref(false)
const outline = ref(null); const scripts = ref([]); const evidence = ref([]); const proposals = ref([])
const selectedNodeId = ref(''); const draftTitle = ref(''); const draftScript = ref(''); const mobilePanel = ref('tree')
const agentOpen = ref(false); const instruction = ref(''); const agentLoading = ref(false); const agentFeedback = ref('')
const panels = [{ id: 'tree', label: '课程树' }, { id: 'editor', label: '编辑' }, { id: 'evidence', label: '证据与 Agent' }]
const statusText = computed(() => loading.value ? '正在同步课程…' : '教师修改仅在保存后生效')
const scriptByOutline = computed(() => Object.fromEntries(scripts.value.map(item => [item.outline_node_id, item])))
const selectedNode = computed(() => outlineNodes.value.find(item => item.outline_node_id === selectedNodeId.value) || null)
const selectedScript = computed(() => selectedNode.value ? scriptByOutline.value[selectedNode.value.outline_node_id] : null)
const outlineNodes = computed(() => {
  const raw = outline.value?.nodes || []; const depth = {}; const byParent = {}
  raw.forEach(item => { (byParent[item.parent_node_id || 'root'] ||= []).push(item) }); Object.values(byParent).forEach(items => items.sort((a,b) => a.order_index - b.order_index))
  const walk = (parent, level) => (byParent[parent] || []).flatMap(item => { depth[item.outline_node_id] = level; return [{ ...item, depth: level }, ...walk(item.outline_node_id, level + 1)] })
  return walk('root', 0)
})

async function reload () { loading.value = true; try { const [nextOutline, nextScripts, nextProposals] = await Promise.all([getOutline(courseId.value), getTeachingScripts(courseId.value), listBuildProposals(courseId.value)]); outline.value = nextOutline; scripts.value = nextScripts?.items || []; proposals.value = nextProposals?.items || []; if (!selectedNodeId.value && outlineNodes.value.length) await selectNode(outlineNodes.value[0]) } catch { showToast('课程工作台暂时无法读取，请稍后重试。', 'error') } finally { loading.value = false } }
async function selectNode (node) { selectedNodeId.value = node.outline_node_id; draftTitle.value = node.title; draftScript.value = scriptByOutline.value[node.outline_node_id]?.content || ''; evidence.value = []; evidenceLoading.value = true; try { const result = await getPrepAgentNodeEvidence(courseId.value, node.outline_node_id); evidence.value = result?.items || [] } catch { evidence.value = [] } finally { evidenceLoading.value = false } }
async function save () { if (!selectedNode.value) return; saving.value = true; try { if (!selectedNode.value.locked && draftTitle.value !== selectedNode.value.title) await updateOutlineNode(courseId.value, selectedNode.value.outline_node_id, { title: draftTitle.value }); if (selectedScript.value && !selectedScript.value.locked && draftScript.value !== selectedScript.value.content) await updateTeachingScript(courseId.value, selectedScript.value.script_node_id, { content: draftScript.value }); showToast('教师修改已保存。', 'success'); await reload() } catch { showToast('保存失败；已锁定内容不可被覆盖。', 'error') } finally { saving.value = false } }
async function lockSelected () { if (!selectedNode.value) return; lockLoading.value = true; try { await lockOutlineNode(courseId.value, selectedNode.value.outline_node_id); if (selectedScript.value) await lockTeachingScript(courseId.value, selectedScript.value.script_node_id); showToast('节点已锁定，后续 Agent 不会修改。', 'success'); await reload() } catch { showToast('锁定失败，请重试。', 'error') } finally { lockLoading.value = false } }
async function sendAgent () {
  agentLoading.value = true
  agentFeedback.value = ''
  try {
    const result = await runPrepAgentCommand(
      courseId.value,
      instruction.value,
      selectedNodeId.value || null,
    )
    if (result?.outcome === 'needs_clarification') {
      agentFeedback.value = result.clarification || '请说明要优化的内容或先选中一个课程节点。'
      return
    }
    const excluded = result?.explanation?.excluded_locked_targets?.length
      || result?.excluded_locked_targets?.length
      || 0
    const reason = result?.explanation?.reason
      || result?.summary
      || (result?.status === 'accepted' ? '已完成一键优化并写入课程草稿。' : '已生成待审核提案。')
    agentFeedback.value = `${reason}${excluded ? ` 已排除 ${excluded} 个锁定目标。` : ''}`
    instruction.value = ''
    await reload()
  } catch (error) {
    agentFeedback.value = error?.response?.data?.detail?.message || '未能生成提案；请确认初始草稿已生成且仍有未锁定节点。'
  } finally {
    agentLoading.value = false
  }
}
async function decide (proposal, accepted) { try { await decideBuildProposal(courseId.value, proposal.proposal_id, accepted); showToast(accepted ? '提案已接受并写入课程草稿。' : '提案已拒绝。', 'success'); await reload() } catch { showToast('提案处理失败，可能包含已锁定的目标。', 'error') } }
onMounted(reload)
</script>

<style scoped>
.course-workbench{min-height:100dvh;background:#f6f8fb;color:#172033}.workbench-header{min-height:64px;padding:12px 24px;background:#fff;border-bottom:1px solid #d9e1ea;display:flex;justify-content:space-between;align-items:center;gap:16px}.eyebrow,.panel-heading small,.proposal-card small{margin:0;color:#64748b;font-size:12px}.workbench-header h1{margin:3px 0 0;font-size:19px}.header-actions,.editor-actions,.agent-actions,.proposal-actions{display:flex;align-items:center;gap:8px}.save-state{font-size:13px;color:#475569}.primary,.secondary,.accept,.reject{min-height:38px;border-radius:8px;padding:0 12px;font-weight:600;display:inline-flex;align-items:center;justify-content:center;gap:7px;cursor:pointer}.primary{border:1px solid #1769aa;background:#1769aa;color:#fff}.secondary{border:1px solid #cbd5e1;background:#fff;color:#334155}.accept{border:1px solid #15803d;background:#f0fdf4;color:#166534}.reject{border:1px solid #e2e8f0;background:#fff;color:#475569}.primary:disabled,.secondary:disabled{opacity:.55;cursor:not-allowed}.workbench-grid{display:grid;grid-template-columns:250px minmax(360px,1fr) 350px;gap:14px;max-width:1720px;margin:0 auto;padding:14px}.panel{background:#fff;border:1px solid #d9e1ea;border-radius:12px;min-height:0}.outline-pane,.evidence-pane{padding:14px}.editor-pane{padding:20px}.panel-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;border-bottom:1px solid #edf1f5;padding-bottom:12px}.panel-heading p,.proposal-heading p{margin:0;font-size:14px;font-weight:700}.state{min-height:160px;display:flex;align-items:center;justify-content:center;text-align:center;color:#64748b;font-size:14px;line-height:1.6}.state.compact{min-height:80px}.tree{margin-top:10px;max-height:calc(100dvh - 150px);overflow:auto}.tree-node{width:100%;min-height:40px;border:0;border-radius:7px;background:transparent;color:#334155;text-align:left;display:flex;align-items:center;gap:7px;padding-right:8px;cursor:pointer;font:inherit;font-size:13px}.tree-node:hover{background:#f1f5f9}.tree-node.active{background:#e8f1f8;color:#0b5f97;font-weight:700}.node-dot{width:8px;height:8px;border-radius:50%;background:#94a3b8;flex:0 0 auto}.node-dot.knowledge_point{background:#1769aa}.node-dot.chapter,.node-dot.section{background:#7c3aed}.field-label{display:block;margin-top:18px;color:#475569;font-size:13px;font-weight:600}.title-input,.script-input,.agent-input{box-sizing:border-box;width:100%;margin-top:6px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#172033;padding:10px;font:inherit;font-size:14px;line-height:1.6}.title-input:focus,.script-input:focus,.agent-input:focus,button:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}.script-input{min-height:310px;resize:vertical}.editor-actions{justify-content:flex-end;margin-top:14px}.evidence-list{display:grid;gap:8px;margin:12px 0}.evidence-card,.proposal-card{border:1px solid #e2e8f0;border-radius:8px;padding:10px}.evidence-card p,.proposal-card p{margin:6px 0 0;font-size:13px;line-height:1.6;color:#475569;white-space:pre-wrap}.proposal-heading{display:flex;justify-content:space-between;border-top:1px solid #edf1f5;margin-top:16px;padding-top:14px}.proposal-list{display:grid;gap:8px;margin-top:10px;max-height:300px;overflow:auto}.proposal-card strong{font-size:13px;display:block;line-height:1.5}.proposal-actions{margin-top:10px}.agent-popover{position:fixed;right:24px;bottom:24px;z-index:50;width:min(500px,calc(100vw - 28px));background:#fff;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 18px 50px rgba(15,23,42,.2);padding:18px}.agent-heading{display:flex;justify-content:space-between;gap:12px}.agent-heading p{margin:0;color:#1769aa;font-size:12px;font-weight:700}.agent-heading h2{margin:4px 0 0;font-size:18px}.icon-button{width:38px;height:38px;border:0;border-radius:8px;background:#f1f5f9;color:#334155;cursor:pointer;display:grid;place-items:center}.agent-note,.agent-feedback{color:#475569;font-size:13px;line-height:1.6}.agent-feedback{background:#eff6ff;border-radius:8px;padding:9px}.agent-input{min-height:120px;resize:vertical}.agent-actions{justify-content:flex-end;margin-top:14px}.mobile-panels{display:none}@media(max-width:1060px){.workbench-grid{grid-template-columns:220px minmax(0,1fr)}.evidence-pane{grid-column:1/-1;min-height:260px}.evidence-pane .proposal-list{max-height:180px}}@media(max-width:720px){.workbench-header{padding:12px 14px;align-items:flex-start;flex-direction:column}.header-actions{width:100%;justify-content:space-between}.save-state{display:none}.mobile-panels{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;padding:8px 10px;background:#fff;border-bottom:1px solid #d9e1ea}.mobile-panels button{min-height:42px;border:0;border-radius:8px;background:#f1f5f9;color:#475569;font:inherit;font-size:13px;cursor:pointer}.mobile-panels button.active{background:#e8f1f8;color:#0b5f97;font-weight:700}.workbench-grid{display:block;padding:10px}.panel{display:none}.panel-tree .outline-pane,.panel-editor .editor-pane,.panel-evidence .evidence-pane{display:block}.tree{max-height:none}.script-input{min-height:280px}.agent-popover{right:14px;bottom:14px;padding:16px}.header-actions .primary,.header-actions .secondary{flex:1;font-size:12px;padding:0 8px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
