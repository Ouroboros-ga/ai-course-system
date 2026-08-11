<script setup>
import { computed, onMounted, ref } from 'vue'
import { decidePatchProposal, listPatchProposals } from '@/api/course_build.js'
import { operationDisplayLabel } from '@/app/lib/prepAgentPresentation.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({ courseId: { type: [String, Number], required: true } })
const items = ref([])
const loading = ref(false)
const acting = ref('')
const error = ref('')
const selectedOps = ref({})
const pending = computed(() => items.value.filter((proposal) => proposal.status === 'pending'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await listPatchProposals(props.courseId, { status: 'pending' }))?.items ?? []
    selectedOps.value = Object.fromEntries(items.value.map((proposal) => [proposal.proposal_id, proposal.operations.map((operation) => operation.op_id)]))
  }
  catch (caught) { error.value = caught?.message || '无法读取教师审核提案' }
  finally { loading.value = false }
}
async function decide(proposal, acceptedIds) {
  acting.value = proposal.proposal_id
  try { await decidePatchProposal(props.courseId, proposal.proposal_id, { accepted_operation_ids: acceptedIds }); await load() }
  catch (caught) { error.value = caught?.message || '审核操作失败' }
  finally { acting.value = '' }
}
function acceptAll(proposal) { return decide(proposal, selectedOps.value[proposal.proposal_id] ?? []) }
function rejectAll(proposal) { return decide(proposal, []) }
onMounted(load)
</script>

<template>
  <section class="sfx-proposals sfx-panel">
    <div class="sfx-proposals-head"><div><h2 class="sfx-panel-title">教师审核提案</h2><p class="sfx-t-caption">Agent 只能提交补丁提案；只有教师明确接受的操作才会写入草稿。</p></div><SfxButton size="sm" variant="secondary" :loading="loading" @click="load">刷新</SfxButton></div>
    <p v-if="error" class="sfx-proposal-error sfx-t-caption" role="alert">{{ error }}</p>
    <p v-else-if="!pending.length && !loading" class="sfx-t-caption sfx-t-muted">没有待审核提案。</p>
    <article v-for="proposal in pending" :key="proposal.proposal_id" class="sfx-proposal">
      <header><div><strong>{{ proposal.tool_name }}</strong><span class="sfx-t-caption"> · {{ proposal.policy_version || '未标注策略版本' }}</span></div><SfxBadge tone="amber">待审核</SfxBadge></header>
      <p v-if="proposal.reason" class="sfx-t-ui">{{ proposal.reason }}</p>
      <label v-for="operation in proposal.operations" :key="operation.op_id" class="sfx-proposal-op" :class="`is-${operation.operation}`">
        <div class="sfx-proposal-op-head"><span><input v-model="selectedOps[proposal.proposal_id]" type="checkbox" :value="operation.op_id" /> <SfxBadge :tone="operation.operation === 'remove' ? 'red' : 'green'">{{ operation.operation }}</SfxBadge></span><strong class="sfx-proposal-display">{{ operationDisplayLabel(operation) }}</strong></div>
        <del v-if="operation.before" class="sfx-proposal-before">{{ operation.before }}</del><ins v-if="operation.after" class="sfx-proposal-after">{{ operation.after }}</ins>
        <p v-if="operation.reason" class="sfx-t-caption">{{ operation.reason }}</p>
      </label>
      <footer><SfxButton size="sm" :loading="acting === proposal.proposal_id" @click="acceptAll(proposal)">接受所选、拒绝其余</SfxButton><SfxButton size="sm" variant="danger" :loading="acting === proposal.proposal_id" @click="rejectAll(proposal)">拒绝全部</SfxButton></footer>
    </article>
  </section>
</template>

<style scoped>
.sfx-proposals{display:grid;gap:var(--space-3)}.sfx-proposals-head,.sfx-proposal header,.sfx-proposal footer,.sfx-proposal-op-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2)}.sfx-proposal{display:grid;gap:var(--space-2);padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md)}.sfx-proposal-op{display:grid;gap:var(--space-1);padding:var(--space-2);border-left:3px solid var(--green-600);background:var(--green-50)}.sfx-proposal-op.is-remove{border-color:var(--red-600);background:var(--red-50)}.sfx-proposal-before{color:var(--red-700);white-space:pre-wrap}.sfx-proposal-after{color:var(--green-700);white-space:pre-wrap}.sfx-proposal footer{justify-content:flex-end}.sfx-proposal-error{color:var(--red-700)}.sfx-proposal-display{overflow-wrap:break-word}
</style>
