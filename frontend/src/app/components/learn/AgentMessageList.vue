<script setup>
import { nextTick, ref, watch } from 'vue'
import { Lightbulb, TriangleAlert } from 'lucide-vue-next'
import AgentAssistantBubble from './AgentAssistantBubble.vue'

const props = defineProps({
    ws: { type: Object, required: true },
    activeAdjustment: { type: Object, default: null },
    adjustmentBusy: { type: Boolean, default: false },
    adjustmentNotice: { type: String, default: '' },
})
const emit = defineEmits([
    'accept-adjustment',
    'dismiss-adjustment',
    'return-adjustment',
    'retry-opening-review',
    'retry',
])

const listRef = ref(null)

// 消息变化后滚动到底部
watch(
    () => props.ws.messages.value.length,
    async () => {
        await nextTick()
        listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
    }
)

function hasMessageForActiveAdjustment() {
    const adjustmentId = props.activeAdjustment?.proposal?.adjustment_id
    return Boolean(adjustmentId && props.ws.messages.value.some(message => (
        String(message.learningAdjustment?.adjustment_id || '') === String(adjustmentId)
    )))
}
</script>

<template>
    <div ref="listRef" class="sfx-agent-messages">
        <div v-if="!ws.messages.value.length" class="sfx-agent-greeting">
            <div class="sfx-agent-greeting-avatar" aria-hidden="true">
                <Lightbulb :size="22" />
            </div>
            <div class="sfx-agent-greeting-text">
                <p class="sfx-t-body sfx-agent-greeting-title">就当前知识点向我提问</p>
                <p class="sfx-t-caption">回答会结合当前课程内容；有来源时显示原文引用，没有可靠来源时会明确说明。</p>
            </div>
        </div>

        <div v-for="message in ws.messages.value" :key="message.id" class="sfx-agent-message"
            :class="`is-${message.role}`">
            <!-- 用户消息：右侧气泡 + 头像 -->
            <template v-if="message.role === 'user'">
                <div class="sfx-agent-msg-row">
                    <div class="sfx-agent-msg-bubble-wrap is-user">
                        <div class="sfx-agent-question sfx-t-ui">{{ message.content }}</div>
                    </div>
                    <span class="sfx-agent-avatar sfx-agent-avatar-user" aria-hidden="true">
                        <span class="sfx-agent-avatar-initials">我</span>
                    </span>
                </div>
            </template>

            <!-- 智能体消息：左侧头像 + 气泡 -->
            <AgentAssistantBubble v-else :message="message" :active-adjustment="activeAdjustment"
                :adjustment-busy="adjustmentBusy" @accept-adjustment="(adj) => emit('accept-adjustment', adj)"
                @dismiss-adjustment="(adj) => emit('dismiss-adjustment', adj)"
                @return-adjustment="() => emit('return-adjustment')"
                @retry-opening-review="() => emit('retry-opening-review')" @retry="(msg) => emit('retry', msg)" />
        </div>

        <!-- 全局调整通知：仅显示错误/提示，不再把"已确认回顾"作为无来源的持久化框常驻 -->
        <p v-if="adjustmentNotice" class="sfx-agent-adjustment-notice sfx-t-caption" role="status">
            <TriangleAlert :size="13" /> {{ adjustmentNotice }}
        </p>

        <div v-if="ws.isAsking.value" class="sfx-agent-thinking sfx-t-caption" role="status">
            <span class="sfx-agent-thinking-dots">
                <span></span><span></span><span></span>
            </span>
            课程智能体正在结合当前课程内容生成回答…
        </div>
    </div>
</template>

<style scoped>
/* ========== 消息列表 ========== */
.sfx-agent-messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-6) var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
}

/* ========== 欢迎/空状态 ========== */
.sfx-agent-greeting {
    display: flex;
    align-items: flex-start;
    gap: var(--space-4);
    padding: var(--space-5);
    background: var(--surface-panel);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
}

.sfx-agent-greeting-avatar {
    flex-shrink: 0;
    width: 44px;
    height: 44px;
    border-radius: var(--radius-full);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, var(--amber-200), var(--amber-100));
    color: var(--amber-700);
}

.sfx-agent-greeting-text {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
}

.sfx-agent-greeting-title {
    font-weight: 600;
    color: var(--ink-900);
    margin: 0;
}

.sfx-agent-greeting-text p:last-child {
    color: var(--text-secondary);
    margin: 0;
}

/* ========== 消息行：用户/智能体左右区分 ========== */
.sfx-agent-message {
    display: flex;
    width: 100%;
}

.sfx-agent-msg-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    width: 100%;
}

.sfx-agent-msg-row.is-assistant {
    justify-content: flex-start;
}

.sfx-agent-msg-row:not(.is-assistant) {
    justify-content: flex-end;
}

/* 消息气泡外层 */
.sfx-agent-msg-bubble-wrap {
    min-width: 0;
    max-width: calc(100% - 52px);
    display: flex;
    flex-direction: column;
}

.sfx-agent-msg-bubble-wrap.is-user {
    align-items: flex-end;
}

.sfx-agent-msg-bubble-wrap.is-assistant {
    align-items: stretch;
}

/* ========== 用户气泡 ========== */
.sfx-agent-question {
    background: var(--color-brand);
    color: var(--text-inverse);
    border-radius: var(--radius-md) 4px var(--radius-md) var(--radius-md);
    padding: var(--space-3) var(--space-4);
    line-height: 1.7;
    box-shadow: 0 1px 2px rgb(20 33 61 / 10%);
    word-break: break-word;
    font-size: var(--ui-md-size);
}

/* ========== 通用头像（与头部/气泡共用，作用域内自持） ========== */
.sfx-agent-avatar {
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-full);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: var(--caption-size);
    line-height: 1;
    user-select: none;
}

.sfx-agent-avatar-ai {
    background: linear-gradient(135deg, var(--ink-700), var(--ink-500));
    color: var(--text-inverse);
    box-shadow: 0 1px 2px rgb(20 33 61 / 18%);
}

.sfx-agent-avatar-user {
    background: var(--amber-200);
    color: var(--amber-900);
    box-shadow: 0 1px 2px rgb(155 102 24 / 12%);
}

.sfx-agent-avatar-initials {
    letter-spacing: 0.02em;
}

/* 全局调整通知 */
.sfx-agent-adjustment-notice {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-3) var(--space-4);
    background: var(--amber-100);
    border: 1px dashed var(--amber-300);
    border-radius: var(--radius-md);
    color: var(--amber-700);
}

/* 思考中动画 */
.sfx-agent-thinking {
    display: inline-flex;
    align-items: center;
    gap: var(--space-3);
    color: var(--text-muted);
    padding: var(--space-3) var(--space-4);
    background: var(--surface-panel);
    border: 1px dashed var(--border-default);
    border-radius: var(--radius-md);
    align-self: flex-start;
    margin-left: 48px;
}

.sfx-agent-thinking-dots {
    display: inline-flex;
    gap: 4px;
    align-items: center;
}

.sfx-agent-thinking-dots span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ink-300);
    animation: sfx-thinking-bounce 1.2s infinite ease-in-out;
}

.sfx-agent-thinking-dots span:nth-child(2) {
    animation-delay: 0.15s;
}

.sfx-agent-thinking-dots span:nth-child(3) {
    animation-delay: 0.3s;
}

@keyframes sfx-thinking-bounce {

    0%,
    80%,
    100% {
        transform: scale(0.7);
        opacity: 0.5;
    }

    40% {
        transform: scale(1);
        opacity: 1;
    }
}

/* 响应式：窄屏下消息间距收窄 */
@media (max-width: 900px) {
    .sfx-agent-messages {
        padding: var(--space-4) var(--space-3);
        gap: var(--space-5);
    }

    .sfx-agent-msg-bubble-wrap {
        max-width: calc(100% - 44px);
    }

    .sfx-agent-avatar {
        width: 32px;
        height: 32px;
    }
}
</style>
