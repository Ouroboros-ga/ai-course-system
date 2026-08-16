<script setup>
import { nextTick, ref, watch } from 'vue'
import { CircleAlert, Sparkles } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import { changeSummaryMessage } from '@/app/lib/prepAgentPresentation.js'
import AgentProposals from './AgentProposals.vue'

const props = defineProps({
    messages: { type: Array, default: () => [] },
    thinking: { type: Boolean, default: false },
    thinkingText: { type: String, default: '' },
    pending: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    deciding: { type: String, default: '' },
})
defineEmits(['decide', 'refresh'])

// 滚动容器：消息/思考气泡变化时自动滚到底部
const chatScroll = ref(null)
function scrollToBottom() {
    nextTick(() => {
        if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight
    })
}
watch(() => props.messages, scrollToBottom, { deep: true })
watch(() => props.thinking, (v) => { if (v) scrollToBottom() })
</script>

<template>
    <div ref="chatScroll" class="agent-chat">
        <p v-if="!messages.length" class="chat-empty">描述你想要的调整，助手会给出修改建议供你确认。</p>

        <template v-for="(msg, i) in messages" :key="i">
            <!-- 用户消息（偏右） -->
            <div v-if="msg.role === 'user'" class="chat-msg chat-msg--user">
                <div class="chat-bubble chat-bubble--user">
                    <div v-if="msg.source === 'quick_action'" class="quick-action-badge">
                        <SfxBadge tone="ink">一键操作 · 已授权直接应用</SfxBadge>
                    </div>
                    <p>{{ msg.text }}</p>
                </div>
            </div>

            <!-- Agent 回复（偏左） -->
            <div v-else class="chat-msg chat-msg--agent">
                <div class="chat-avatar">
                    <Sparkles :size="14" />
                </div>
                <div class="chat-bubble chat-bubble--agent" :class="{ 'chat-bubble--running': msg.running }">
                    <p v-if="msg.running" class="chat-running"><span class="running-dot"></span>{{ msg.reason }}</p>
                    <p v-else-if="msg.error" class="chat-error">
                        <CircleAlert :size="14" /> {{ msg.reason }}
                    </p>
                    <template v-else>
                        <p class="chat-reason">{{ msg.reason }}</p>
                        <p v-if="msg.planner" class="chat-meta">生成方式：{{ msg.planner.startsWith('llm') ? 'AI 生成' : '规则生成'
                            }}</p>
                        <p v-if="changeSummaryMessage(msg.changeSummary)" class="chat-meta">{{
                            changeSummaryMessage(msg.changeSummary) }}</p>
                        <p v-if="msg.excluded?.length" class="chat-excluded">已排除锁定项：{{ msg.excluded.join('、') }}</p>
                    </template>
                </div>
            </div>
        </template>

        <!-- 思考中气泡 -->
        <div v-if="thinking" class="chat-msg chat-msg--agent">
            <div class="chat-avatar thinking-avatar">
                <Sparkles :size="14" />
            </div>
            <div class="chat-bubble chat-bubble--thinking">
                <div class="thinking-dots"><span></span><span></span><span></span></div>
                <p class="thinking-text">{{ thinkingText }}</p>
            </div>
        </div>

        <!-- 待审核提案区 -->
        <AgentProposals :pending="pending" :loading="loading" :deciding="deciding"
            @decide="(proposal, accepted) => $emit('decide', proposal, accepted)" @refresh="$emit('refresh')" />
    </div>
</template>

<style scoped>
/* ── 聊天消息区 ── */
.agent-chat {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: var(--space-3) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
}

.chat-empty {
    margin: auto;
    padding: var(--space-6) var(--space-3);
    text-align: center;
    color: var(--text-muted);
    font-size: var(--ui-sm-size);
    line-height: 1.6;
}

.chat-msg {
    display: flex;
    gap: var(--space-2);
    max-width: 100%;
}

.chat-msg--user {
    justify-content: flex-end;
}

.chat-msg--agent {
    justify-content: flex-start;
}

.chat-avatar {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    background: var(--ink-100);
    color: var(--ink-700);
    display: grid;
    place-items: center;
    flex-shrink: 0;
    margin-top: 2px;
}

.chat-bubble {
    max-width: 85%;
    padding: var(--space-2) var(--space-3);
    font-size: var(--ui-sm-size);
    line-height: 1.55;
}

.chat-bubble--user {
    background: var(--ink-900);
    color: var(--text-inverse);
    border-radius: var(--radius-md) var(--radius-xs) var(--radius-md) var(--radius-md);
}

.chat-bubble--user p {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
}

.quick-action-badge {
    margin-bottom: var(--space-2);
}

.chat-bubble--agent {
    background: var(--surface-cool);
    color: var(--text-primary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-xs) var(--radius-md) var(--radius-md) var(--radius-md);
}

.chat-bubble--agent p {
    margin: 0 0 var(--space-1);
    overflow-wrap: break-word;
}

.chat-bubble--agent p:last-child {
    margin-bottom: 0;
}

.chat-reason {
    color: var(--text-primary);
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
}

.chat-meta {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.chat-excluded {
    color: var(--amber-700);
    font-size: var(--caption-size);
}

.chat-error {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
    color: var(--red-700);
    font-size: var(--caption-size);
}

.chat-running {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--ink-700);
}

.chat-bubble--running {
    background: var(--ink-100);
    border-color: var(--ink-300);
}

.running-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    background: var(--ink-500);
    animation: thinking-pulse 1.5s ease-in-out infinite;
    flex-shrink: 0;
}

/* ── 思考气泡 ── */
.thinking-avatar {
    animation: thinking-pulse 1.5s ease-in-out infinite;
}

.chat-bubble--thinking {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    background: var(--ink-100);
    border: 1px solid var(--ink-300);
    border-radius: var(--radius-xs) var(--radius-md) var(--radius-md) var(--radius-md);
    padding: var(--space-2) var(--space-3);
}

.thinking-dots {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
}

.thinking-dots span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ink-500);
    animation: thinking-bounce 1.4s ease-in-out infinite;
}

.thinking-dots span:nth-child(2) {
    animation-delay: 0.16s;
}

.thinking-dots span:nth-child(3) {
    animation-delay: 0.32s;
}

.thinking-text {
    margin: 0;
    color: var(--ink-700);
    font-size: var(--caption-size);
    font-weight: 500;
    white-space: nowrap;
    transition: opacity var(--duration-fast) var(--ease-out);
}

@keyframes thinking-bounce {

    0%,
    80%,
    100% {
        transform: scale(0.6);
        opacity: 0.4;
    }

    40% {
        transform: scale(1);
        opacity: 1;
    }
}

@keyframes thinking-pulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.5;
    }
}

/* ── 响应式 ── */
@media (max-width: 760px) {
    .agent-chat {
        padding: var(--space-3);
    }
}
</style>
