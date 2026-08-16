<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AgentPanelHeader from '@/app/components/learn/AgentPanelHeader.vue'
import AgentMessageList from '@/app/components/learn/AgentMessageList.vue'
import AgentPanelFooter from '@/app/components/learn/AgentPanelFooter.vue'

/**
 * 课程智能体面板（page-design §12.5 UNDERSTAND / §13.1 统一人格 / §6.7 SystemResponsePanel）。
 *
 * 受控接入（P1）：useLearningWorkspace.sendQuestion 现在在 cognitive_analysis 能力开关
 * 开启 + analyticsEligible（真实学生）+ studentId 三者齐备时优先调用 TeachingAgent
 * (/teaching-agent/respond)；503/失败时静默回退 V1 /chat/ask，不影响正常 Q&A。
 * 教师/助教预览视角（analyticsEligible=false）直接走 V1。
 *
 * 结构（§6.7）：①系统观察 ②依据（原文引用）③回答 ④建议下一步教学行动。
 * 回答失败 → 显式错误 + 重试；低置信 → 提示核对原文引用；无引用不伪造。
 *
 * 本组件已拆分为编排器，展示层收敛到子组件：
 *  - AgentPanelHeader：头部身份卡片
 *  - AgentMessageList：消息列表（内含 AgentAssistantBubble 单条智能体气泡）
 *  - AgentPanelFooter：快捷操作 + 输入框
 */
const props = defineProps({
    ws: { type: Object, required: true },
    anchor: { type: Object, default: null },
    activeAdjustment: { type: Object, default: null },
    adjustmentBusy: { type: Boolean, default: false },
    adjustmentNotice: { type: String, default: '' },
    hideFooterInput: { type: Boolean, default: false },
})

const emit = defineEmits([
    'exit',
    'action',
    'accept-adjustment',
    'dismiss-adjustment',
    'retry-opening-review',
    'return-adjustment',
])

const rootRef = ref(null)
const footerRef = ref(null)

function send(question) {
    props.ws.sendQuestion(question)
}

function retry(message) {
    if (message?.retryQuestion) send(message.retryQuestion)
}

// C1 修复：打开时焦点进入输入框；Esc 关闭；关闭后焦点回触发区（由 LearnPage 处理）
function handleKeydown(e) {
    if (e.key === 'Escape') {
        e.preventDefault()
        emit('exit')
    }
}

onMounted(() => {
    window.addEventListener('keydown', handleKeydown)
    nextTick(() => footerRef.value?.focusInput())
})

onBeforeUnmount(() => {
    window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
    <aside ref="rootRef" class="sfx-agent is-chat-layout" aria-label="课程智能体" @keydown="handleKeydown">
        <!-- 头部身份卡片 -->
        <AgentPanelHeader :anchor="anchor" @exit="emit('exit')" />

        <!-- 消息列表 + 单条智能体气泡（AgentAssistantBubble） -->
        <AgentMessageList :ws="ws" :active-adjustment="activeAdjustment" :adjustment-busy="adjustmentBusy"
            :adjustment-notice="adjustmentNotice" @accept-adjustment="(adj) => emit('accept-adjustment', adj)"
            @dismiss-adjustment="(adj) => emit('dismiss-adjustment', adj)"
            @return-adjustment="() => emit('return-adjustment')"
            @retry-opening-review="() => emit('retry-opening-review')" @retry="retry" />

        <!-- 底部：快捷操作 + 输入框 -->
        <AgentPanelFooter ref="footerRef" :ws="ws" :hide-footer-input="hideFooterInput" />
    </aside>
</template>

<style scoped>
.sfx-agent {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--surface-canvas);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    overflow: hidden;
}

/* 布局与响应式由子组件自持：AgentPanelHeader / AgentMessageList / AgentAssistantBubble / AgentPanelFooter */
</style>
