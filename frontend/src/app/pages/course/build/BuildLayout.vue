<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { decideBuildProposal, listBuildProposals } from '@/api/course_editor.js'
import { createBuildProposal } from '@/api/course_editor.js'

const context = inject('courseContext')
const courseId = computed(() => context?.courseId?.value)
const proposals = ref([])
const proposalText = ref('')
async function loadProposals() {
  if (!courseId.value) return
  try { proposals.value = (await listBuildProposals(courseId.value))?.items ?? [] } catch { proposals.value = [] }
}
async function decide(proposal, accepted) {
  await decideBuildProposal(courseId.value, proposal.proposal_id, accepted)
  proposal.status = accepted ? 'accepted' : 'rejected'
}
async function createProposal() {
  const text = proposalText.value.trim()
  if (!text || !courseId.value) return
  const match = text.match(/^(outline|script):([^:]+):(title|content|style)\s*=>\s*([\s\S]+)$/)
  if (!match) return
  await createBuildProposal(courseId.value, { tool_name: 'TeacherPrepAgent', reason: '教师从备课浮窗提交的候选修改', operations: [{ operation: 'replace', target: `${match[1]}:${match[2]}:${match[3]}`, after: match[4], before: '' }] })
  proposalText.value = ''
  await loadProposals()
}
onMounted(loadProposals)
const steps = [
  ['materials', '资料'],
  ['structure', '课程结构'],
  ['scripts', '讲授脚本'],
  ['mapping', '教学 PPT 映射'],
  ['media', '媒体与数字人'],
  ['validate', '检查'],
  ['releases', '发布'],
]
</script>

<template>
  <div class="build-layout">
    <aside class="build-rail">
      <p class="eyebrow">课程建设</p>
      <RouterLink v-for="step in steps" :key="step[0]" :to="`/app/course/${courseId}/build/${step[0]}`" class="build-link">
        {{ step[1] }}
      </RouterLink>
      <div class="proposal-box">
        <p class="eyebrow">备课 Agent 提案</p>
        <div v-if="!proposals.length" class="proposal-empty">暂无待审核提案</div>
        <article v-for="proposal in proposals.filter(item => item.status === 'pending')" :key="proposal.proposal_id" class="proposal">
          <strong>{{ proposal.tool_name }}</strong>
          <p>{{ proposal.reason || 'Agent 提出了一项课程草稿修改。' }}</p>
          <div v-for="op in proposal.operations" :key="op.op_id" class="diff" :class="`diff-${op.operation}`"><span>{{ op.target }}</span><del v-if="op.before">{{ op.before }}</del><ins v-if="op.after">{{ op.after }}</ins></div>
          <div class="proposal-actions"><button @click="decide(proposal, true)">接受</button><button @click="decide(proposal, false)">拒绝</button></div>
        </article>
        <form class="proposal-create" @submit.prevent="createProposal">
          <input v-model="proposalText" placeholder="提案格式：outline:on_x:title => 新标题" />
          <button type="submit">提交提案</button>
        </form>
      </div>
    </aside>
    <main class="build-main"><router-view /></main>
  </div>
</template>

<style scoped>
.build-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:16px;padding:16px;max-width:1400px;margin:0 auto;width:100%;box-sizing:border-box}.build-rail{background:var(--surface-panel,#fff);border:1px solid var(--border-default,#dbe2ea);border-radius:12px;padding:12px;height:max-content;display:grid;gap:4px}.eyebrow{font-size:12px;color:var(--text-muted,#64748b);margin:4px 8px 8px}.build-link{padding:10px 8px;border-radius:8px;color:var(--text-secondary,#475569);text-decoration:none;font-size:14px}.build-link:hover,.router-link-active{background:#eef5fa;color:#1769aa}.build-main{min-width:0}.proposal-box{margin-top:16px;border-top:1px solid #e2e8f0;padding-top:12px}.proposal-empty{font-size:12px;color:#94a3b8;padding:6px 8px}.proposal{border:1px solid #fde68a;background:#fffbeb;border-radius:8px;padding:8px;font-size:12px}.proposal strong{color:#334155}.proposal p{margin:5px 0;color:#64748b}.diff{display:grid;gap:2px;margin-top:5px;padding:5px;border-radius:5px;background:#fff}.diff-add{border-left:3px solid #16a34a}.diff-remove{border-left:3px solid #dc2626}.diff-replace{border-left:3px solid #ca8a04}.diff span{color:#64748b}.diff del{color:#b91c1c}.diff ins{color:#166534;text-decoration:none}.proposal-actions{display:flex;gap:5px;margin-top:8px}.proposal-actions button{border:1px solid #cbd5e1;border-radius:5px;background:#fff;padding:4px 7px;cursor:pointer}.proposal-actions button:first-child{color:#166534}.proposal-actions button:last-child{color:#b91c1c}.proposal-create{display:grid;gap:5px;margin-top:10px}.proposal-create input{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:5px;padding:6px;font-size:12px}.proposal-create button{border:1px solid #cbd5e1;background:#fff;border-radius:5px;padding:5px;cursor:pointer}@media(max-width:760px){.build-layout{grid-template-columns:1fr}.build-rail{display:flex;overflow:auto}.build-link{white-space:nowrap}.proposal-box{min-width:260px}}
</style>
