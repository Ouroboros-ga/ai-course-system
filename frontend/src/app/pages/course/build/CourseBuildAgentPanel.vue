<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { BookOpenText, Check, CircleAlert, SendHorizontal, Sparkles, X } from 'lucide-vue-next'
import { decideBuildProposal, getPrepAgentNodeEvidence, listBuildProposals, runPrepAgentCommand } from '@/api/course_editor.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  courseId: { type: Number, required: true },
  selectedNode: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const proposals = ref([])
const evidence = ref([])
const instruction = ref('')
const loading = ref(false)
const sending = ref(false)
const deciding = ref('')
const error = ref('')
const lastResponse = ref(null)
const pending = computed(() => proposals.value.filter((proposal) => proposal.status === 'pending'))
const selectedTitle = computed(() => props.selectedNode?.title || '')

function apiErrorMessage(caught, fallback) {
  const payload = caught?.response?.data
  const detail = payload?.detail
  return (
    (typeof detail === 'string' ? detail : detail?.message)
    || payload?.message
    || caught?.message
    || fallback
  )
}

async function loadProposals() {
  loading.value = true
  try { proposals.value = (await listBuildProposals(props.courseId))?.items ?? [] }
  catch (caught) { error.value = apiErrorMessage(caught, '无法读取 Agent 提案') }
  finally { loading.value = false }
}
async function loadEvidence() {
  evidence.value = []
  if (!props.selectedNode?.outline_node_id) return
  try { evidence.value = (await getPrepAgentNodeEvidence(props.courseId, props.selectedNode.outline_node_id))?.items ?? [] }
  catch (caught) { error.value = apiErrorMessage(caught, '无法读取此节点的原文证据') }
}
async function send() {
  const value = instruction.value.trim()
  if (!value || sending.value) return
  sending.value = true; error.value = ''; lastResponse.value = null
  try {
    const data = await runPrepAgentCommand(
      props.courseId,
      value,
      props.selectedNode?.outline_node_id ?? null,
    )
    lastResponse.value = data?.explanation ?? { reason: '已创建待教师审核的提案。', changed: [] }
    instruction.value = ''
    await loadProposals()
  } catch (caught) { error.value = apiErrorMessage(caught, '备课 Agent 暂时无法生成提案') }
  finally { sending.value = false }
}
async function decide(proposal, accepted) {
  deciding.value = proposal.proposal_id; error.value = ''
  try {
    await decideBuildProposal(props.courseId, proposal.proposal_id, accepted)
    await loadProposals()
    window.dispatchEvent(new CustomEvent('course-build-proposal-decided'))
  } catch (caught) { error.value = apiErrorMessage(caught, '提案审核失败；草稿未被修改') }
  finally { deciding.value = '' }
}
function submitOnEnter(event) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send() } }
onMounted(loadProposals)
watch(() => props.selectedNode?.outline_node_id, loadEvidence, { immediate: true })
</script>

<template>
  <aside class="course-build-agent" aria-label="备课 Agent">
    <header class="agent-header">
      <div class="agent-heading"><span class="agent-mark"><Sparkles :size="17" /></span><div><h2>备课 Agent</h2><p>受控提案模式</p></div></div>
      <button type="button" class="close-agent" aria-label="关闭备课 Agent" @click="emit('close')"><X :size="18" /></button>
    </header>

    <div class="agent-scroll">
      <section class="agent-observation">
        <p class="panel-kicker">当前工作范围</p>
        <template v-if="selectedNode">
          <strong>{{ selectedTitle }}</strong>
          <p>已选中课程节点。Agent 会排除所有已锁定的目录和讲稿，只生成待审核提案。</p>
        </template>
        <template v-else>
          <strong>先选择一个课程结构节点</strong>
          <p>你仍可提出全局调整；选择节点后可查看对应原文证据，并更准确地审核建议。</p>
        </template>
      </section>

      <section v-if="lastResponse" class="agent-explanation">
        <p class="panel-kicker">本次提案说明</p>
        <strong>{{ lastResponse.reason || '已生成待审核提案。' }}</strong>
        <p v-if="lastResponse.planner">
          生成方式：{{ lastResponse.planner === 'llm' ? '在线模型' : '本地规则（未调用在线模型）' }}
        </p>
        <p v-if="lastResponse.changed?.length">修改目标：{{ lastResponse.changed.join('、') }}</p>
        <p v-if="lastResponse.excluded_locked_targets?.length" class="excluded">已排除锁定项：{{ lastResponse.excluded_locked_targets.join('、') }}</p>
      </section>

      <section v-if="selectedNode" class="evidence-section">
        <div class="section-heading"><div><p class="panel-kicker">原文证据</p><h3>节点来源</h3></div><BookOpenText :size="18" /></div>
        <p v-if="!evidence.length" class="empty-copy">此节点暂未关联可显示的原文区块。</p>
        <article v-for="item in evidence" :key="item.block_id" class="evidence-card">
          <p>{{ item.text || '原文区块为空' }}</p>
          <footer><code>{{ item.block_id }}</code><span v-if="item.page">第 {{ item.page }} 页</span><span v-if="item.confidence != null">置信度 {{ Math.round(item.confidence * 100) }}%</span></footer>
        </article>
      </section>

      <section class="proposal-section">
        <div class="section-heading"><div><p class="panel-kicker">教师审核</p><h3>待确认提案</h3></div><SfxButton variant="tertiary" size="sm" :loading="loading" @click="loadProposals">刷新</SfxButton></div>
        <p v-if="!pending.length && !loading" class="empty-copy">还没有待审核提案。</p>
        <article v-for="proposal in pending" :key="proposal.proposal_id" class="proposal-card">
          <header><span>{{ proposal.tool_name }}</span><SfxBadge tone="amber">待审核</SfxBadge></header>
          <p class="proposal-reason">{{ proposal.reason || 'Agent 提出了一项课程草稿修改。' }}</p>
          <div v-for="operation in proposal.operations" :key="operation.op_id" class="proposal-operation">
            <div><code>{{ operation.target }}</code><span>{{ operation.operation }}</span></div>
            <del v-if="operation.before">{{ operation.before }}</del>
            <ins v-if="operation.after">{{ operation.after }}</ins>
            <p v-if="operation.reason">{{ operation.reason }}</p>
            <div v-if="operation.evidence_refs?.length" class="evidence-refs">证据：{{ operation.evidence_refs.join('、') }}</div>
          </div>
          <footer><SfxButton size="sm" :loading="deciding === proposal.proposal_id" @click="decide(proposal, true)"><Check :size="15" /> 接受提案</SfxButton><SfxButton size="sm" variant="danger" :disabled="Boolean(deciding)" @click="decide(proposal, false)">拒绝</SfxButton></footer>
        </article>
      </section>
    </div>

    <form class="agent-composer" @submit.prevent="send">
      <label for="agent-instruction">向备课 Agent 说明你想调整什么</label>
      <textarea id="agent-instruction" v-model="instruction" rows="3" maxlength="8000" placeholder="例如：把第二章讲得更适合大一学生，并补一个生活化例子。" :disabled="sending" @keydown="submitOnEnter" />
      <p v-if="error" class="agent-error" role="alert"><CircleAlert :size="15" /> {{ error }}</p>
      <div><span>Enter 发送，Shift + Enter 换行</span><SfxButton type="submit" :disabled="!instruction.trim()" :loading="sending"><SendHorizontal :size="16" /> 生成提案</SfxButton></div>
    </form>
  </aside>
</template>

<style scoped>
.course-build-agent{display:flex;flex-direction:column;height:100%;background:var(--surface-panel);border-left:1px solid var(--border-strong)}.agent-header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);min-height:72px;padding:0 var(--space-4);border-bottom:1px solid var(--border-default)}.agent-heading{display:flex;align-items:center;gap:var(--space-2)}.agent-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:var(--radius-md);background:var(--ink-100);color:var(--ink-700)}.agent-heading h2,.agent-heading p{margin:0}.agent-heading h2{font-size:var(--title-3-size);line-height:1.2;color:var(--text-primary)}.agent-heading p{margin-top:2px;color:var(--text-muted);font-size:var(--caption-size)}.close-agent{display:none;place-items:center;width:40px;height:40px;border:0;border-radius:var(--radius-md);background:transparent;color:var(--text-secondary);cursor:pointer}.close-agent:hover{background:var(--surface-cool)}.agent-scroll{flex:1;overflow:auto;padding:var(--space-4);display:grid;align-content:start;gap:var(--space-4)}.agent-observation,.agent-explanation{padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-cool)}.agent-observation strong,.agent-explanation strong{color:var(--text-primary);font-size:var(--ui-md-size)}.agent-observation p:not(.panel-kicker),.agent-explanation p:not(.panel-kicker){margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.panel-kicker{margin:0 0 var(--space-1);font-size:var(--caption-size);font-weight:650;letter-spacing:.06em;color:var(--ink-500)}.excluded{color:var(--amber-700)!important}.section-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2);margin-bottom:var(--space-2);color:var(--ink-700)}.section-heading h3{margin:0;font-size:var(--title-3-size);color:var(--text-primary)}.empty-copy{margin:0;padding:var(--space-3);color:var(--text-muted);font-size:var(--ui-sm-size);border:1px dashed var(--border-strong);border-radius:var(--radius-md)}.evidence-section,.proposal-section{display:grid;gap:var(--space-2)}.evidence-card{padding:var(--space-3);background:var(--surface-cool);border-left:3px solid var(--ink-500);border-radius:0 var(--radius-md) var(--radius-md) 0}.evidence-card p{margin:0;color:var(--text-primary);font-size:var(--ui-sm-size);line-height:1.6;white-space:pre-wrap}.evidence-card footer{display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:var(--space-2);color:var(--text-muted);font-size:var(--caption-size)}.evidence-card code,.proposal-operation code{font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:11px}.proposal-card{display:grid;gap:var(--space-2);padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md)}.proposal-card>header,.proposal-card>footer{display:flex;justify-content:space-between;align-items:center;gap:var(--space-2)}.proposal-card>header>span{font-size:var(--ui-sm-size);font-weight:600;color:var(--ink-900)}.proposal-card>footer{justify-content:flex-end}.proposal-reason{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.proposal-operation{display:grid;gap:var(--space-1);padding:var(--space-2);border-left:3px solid var(--green-500);background:var(--green-100)}.proposal-operation>div:first-child{display:flex;justify-content:space-between;gap:var(--space-2);color:var(--text-muted)}.proposal-operation>div:first-child span{font-size:var(--caption-size)}.proposal-operation del{color:var(--red-700);font-size:var(--ui-sm-size);white-space:pre-wrap}.proposal-operation ins{color:var(--green-700);font-size:var(--ui-sm-size);text-decoration:none;white-space:pre-wrap}.proposal-operation p{margin:0;color:var(--text-secondary);font-size:var(--caption-size);line-height:1.45}.evidence-refs{color:var(--ink-500);font-size:var(--caption-size)}.agent-composer{padding:var(--space-3) var(--space-4) var(--space-4);border-top:1px solid var(--border-default);background:var(--surface-panel)}.agent-composer label{display:block;margin-bottom:var(--space-2);color:var(--text-primary);font-size:var(--ui-sm-size);font-weight:600}.agent-composer textarea{display:block;width:100%;box-sizing:border-box;min-height:74px;padding:var(--space-2) var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);outline:none;resize:vertical;color:var(--text-primary);font:inherit;font-size:var(--ui-sm-size);line-height:1.5}.agent-composer textarea:focus{border-color:var(--ink-500);box-shadow:0 0 0 2px var(--ink-100)}.agent-composer>div{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);margin-top:var(--space-2);color:var(--text-muted);font-size:var(--caption-size)}.agent-error{display:flex;gap:var(--space-1);align-items:flex-start;margin:var(--space-2) 0 0;color:var(--red-700);font-size:var(--caption-size);line-height:1.4}
@media(max-width:1250px){.course-build-agent{height:100%;border-left:0}.close-agent{display:grid}}
@media(max-width:760px){.course-build-agent{height:auto}.agent-scroll{padding:var(--space-3)}.agent-composer{padding:var(--space-3)}.agent-composer>div>span{display:none}}
</style>
