<script setup>
import { SendHorizontal } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
    instruction: { type: String, default: '' },
    sending: { type: Boolean, default: false },
    batchRunning: { type: Boolean, default: false },
})
const emit = defineEmits(['update:instruction', 'send'])

function submitOnEnter(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        emit('send')
    }
}
</script>

<template>
    <form class="agent-composer" @submit.prevent="emit('send')">
        <textarea id="agent-instruction" :value="instruction" rows="2" maxlength="8000" placeholder="向助教智能体说明你想调整什么…"
            :disabled="sending || batchRunning" @input="emit('update:instruction', $event.target.value)"
            @keydown="submitOnEnter" />
        <div class="composer-bar">
            <span class="composer-hint">{{ batchRunning ? '批量优化进行中' : 'Enter 发送，Shift + Enter 换行' }}</span>
            <SfxButton type="submit" :disabled="!props.instruction.trim() || batchRunning" :loading="sending">
                <SendHorizontal :size="16" /> 发送
            </SfxButton>
        </div>
    </form>
</template>

<style scoped>
/* ── 输入区 ── */
.agent-composer {
    flex-shrink: 0;
    padding: var(--space-3);
    border-top: 1px solid var(--border-default);
    background: var(--surface-panel);
}

.agent-composer textarea {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: 44px;
    max-height: 120px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    outline: none;
    resize: none;
    color: var(--text-primary);
    font: inherit;
    font-size: var(--ui-sm-size);
    line-height: 1.5;
    background: var(--surface-cool);
}

.agent-composer textarea:focus {
    border-color: var(--ink-500);
    box-shadow: 0 0 0 2px var(--ink-100);
    background: var(--surface-panel);
}

.composer-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-top: var(--space-2);
}

.composer-hint {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

/* ── 响应式 ── */
@media (max-width: 760px) {
    .agent-composer {
        padding: var(--space-3);
    }

    .composer-hint {
        display: none;
    }
}
</style>
