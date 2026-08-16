<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { decideBuildProposal, getPrepAgentNodeEvidence, listBuildProposals, runPrepAgentCommand } from '@/api/course_editor.js'
import { changeSummaryMessage } from '@/app/lib/prepAgentPresentation.js'
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'
import AgentHeader from './agent/AgentHeader.vue'
import AgentContextPanel from './agent/AgentContextPanel.vue'
import AgentChatList from './agent/AgentChatList.vue'
import AgentComposer from './agent/AgentComposer.vue'

const props = defineProps({
    courseId: { type: Number, required: true },
    selectedNode: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const workbench = inject('courseBuildWorkbench', null)

// ── 提案与证据 ──
const proposals = ref([])
const evidence = ref([])
const loading = ref(false)
const deciding = ref('')
const error = ref('')
const pending = computed(() => proposals.value.filter((proposal) => proposal.status === 'pending'))

// ── 聊天与发送 ──
const messages = workbench ? toRef(workbench, 'agentMessages') : ref([])
const instruction = ref('')
const sending = ref(false)
const batchRunning = computed(() => Boolean(workbench?.batchRun))
const thinking = ref(false)
const thinkingSteps = [
    '正在分析课程材料…',
    '检查知识点关联…',
    '生成修改提案…',
]
const thinkingStep = ref(0)
let thinkingTimer = null
const thinkingText = computed(() => thinkingSteps[thinkingStep.value] || thinkingSteps[0])

async function loadProposals() {
    loading.value = true
    try {
        proposals.value = (await listBuildProposals(props.courseId, 'pending'))?.items ?? []
    }
    catch (caught) { error.value = apiErrorMessage(caught, '无法读取智能体提案') }
    finally { loading.value = false }
}
async function loadEvidence() {
    evidence.value = []
    if (!props.selectedNode?.outline_node_id) return
    try { evidence.value = (await getPrepAgentNodeEvidence(props.courseId, props.selectedNode.outline_node_id))?.items ?? [] }
    catch (caught) { error.value = apiErrorMessage(caught, '无法读取此节点的原文证据') }
}
async function send(targetNodeId = undefined, requestedAction = null) {
    if (targetNodeId !== undefined && targetNodeId !== null && typeof targetNodeId !== 'string') {
        targetNodeId = undefined
    }
    const value = instruction.value.trim()
    if (!value || sending.value || batchRunning.value) return
    sending.value = true; error.value = ''
    // 用户消息（偏右）
    messages.value.push({ role: 'user', text: value })
    instruction.value = ''
    // 启动思考动画（滚动由 AgentChatList 内部监听消息/思考状态自动处理）
    thinking.value = true
    thinkingStep.value = 0
    thinkingTimer = setInterval(() => {
        thinkingStep.value = (thinkingStep.value + 1) % thinkingSteps.length
    }, 2000)
    try {
        const data = await runPrepAgentCommand(
            props.courseId,
            value,
            targetNodeId === undefined
                ? (props.selectedNode?.outline_node_id ?? null)
                : targetNodeId,
            requestedAction,
        )
        // 停止思考动画
        thinking.value = false
        clearInterval(thinkingTimer)
        const needsClarification = data?.outcome === 'needs_clarification'
        const explanation = data?.explanation ?? {
            reason: data?.summary || data?.clarification || (data?.outcome === 'no_change'
                ? '未发现需要安全调整的内容，草稿保持不变。'
                : data?.status === 'accepted'
                    ? '已完成一键优化并写入课程草稿。'
                    : '已创建待教师审核的提案。'),
            planner: data?.planner,
            excluded_locked_targets: data?.excluded_locked_targets || [],
        }
        const changeSummary = data?.change_summary ?? explanation.change_summary ?? null
        // Agent 回复（偏左）
        const reply = {
            role: 'agent',
            reason: explanation.reason || changeSummaryMessage(changeSummary) || '已生成待审核提案。',
            changeSummary,
            proposalId: data?.proposal_id ?? null,
            proposalStatus: changeSummary?.state ?? null,
            planner: explanation.planner,
            excluded: explanation.excluded_locked_targets || [],
        }
        messages.value.push(reply)
        if (!needsClarification) await loadProposals()
    } catch (caught) {
        thinking.value = false
        clearInterval(thinkingTimer)
        error.value = apiErrorMessage(caught, '助教智能体暂时无法生成提案')
        messages.value.push({ role: 'agent', error: true, reason: error.value })
    } finally {
        sending.value = false
    }
}
async function decide(proposal, accepted) {
    deciding.value = proposal.proposal_id; error.value = ''
    try {
        const data = await decideBuildProposal(props.courseId, proposal.proposal_id, accepted)
        const changeSummary = data?.change_summary ?? null
        const message = messages.value.find((item) => item.proposalId === proposal.proposal_id)
        if (message && changeSummary) {
            message.changeSummary = changeSummary
            message.proposalStatus = changeSummary.state
            message.reason = accepted ? '教师已接受该提案，修改已写入课程草稿。' : '教师已拒绝该提案。'
        }
        await loadProposals()
        window.dispatchEvent(new CustomEvent('course-build-proposal-decided'))
    } catch (caught) { error.value = apiErrorMessage(caught, '提案审核失败；草稿未被修改') }
    finally { deciding.value = '' }
}
onMounted(() => {
    loadProposals()
})
onBeforeUnmount(() => {
    if (thinkingTimer) clearInterval(thinkingTimer)
})
watch(() => props.selectedNode?.outline_node_id, loadEvidence, { immediate: true })
// 子页面通过 workbench.pendingInstruction 触发自动发送。
watch(() => workbench?.pendingInstruction, (text) => {
    if (text) {
        instruction.value = text
        const targetNodeId = workbench.pendingNodeId
        const requestedAction = workbench.pendingAgentAction
        workbench.pendingInstruction = ''
        workbench.pendingNodeId = null
        workbench.pendingAgentAction = null
        nextTick(() => send(targetNodeId, requestedAction))
    }
})
</script>

<template>
    <aside class="course-build-agent" aria-label="助教智能体">
        <AgentHeader @close="emit('close')" />

        <!-- 上下文面板（可折叠）：当前节点与原文证据 -->
        <AgentContextPanel :selected-node="selectedNode" :evidence="evidence" />

        <!-- 聊天消息区 + 待审核提案 -->
        <AgentChatList :messages="messages" :thinking="thinking" :thinking-text="thinkingText" :pending="pending"
            :loading="loading" :deciding="deciding" @decide="decide" @refresh="loadProposals" />

        <!-- 输入区 -->
        <AgentComposer v-model:instruction="instruction" :sending="sending" :batch-running="batchRunning"
            @send="send" />
    </aside>
</template>

<style scoped>
.course-build-agent {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--surface-panel);
    border-left: 1px solid var(--border-strong);
}

/* 布局与响应式（子区块样式见 agent/ 下各子组件） */
@media (max-width: 1250px) {
    .course-build-agent {
        height: 100%;
        border-left: 0;
    }
}

@media (max-width: 760px) {
    .course-build-agent {
        height: auto;
    }
}
</style>
