<script setup>
import { nextTick, ref } from 'vue'
import { Lightbulb, ListChecks, RefreshCw } from 'lucide-vue-next'
import AgentInputForm from '@/app/components/learn/AgentInputForm.vue'

const props = defineProps({
    ws: { type: Object, required: true },
    hideFooterInput: { type: Boolean, default: false },
})

// ④ 建议下一步教学行动（§6.7）：真实可操作项，非伪造
const quickActions = [
    { id: 'rephrase', label: '换一种解释', icon: RefreshCw, prompt: '请换一种方式解释：' },
    { id: 'example', label: '举个例子', icon: Lightbulb, prompt: '请举一个具体例子说明：' },
    { id: 'quiz', label: '出一道小题', icon: ListChecks, prompt: '请针对这个知识点出一道小题考我：' },
]

function handleQuick(action) {
    const base = props.ws.currentNode.value?.title || '当前知识点'
    props.ws.sendQuestion(`${action.prompt}${base}`)
}

// C1 修复：面板打开时由父组件通过 focusInput() 聚焦输入框
const inputFormRef = ref(null)
function focusInput() {
    nextTick(() => inputFormRef.value?.focus())
}
defineExpose({ focusInput })
</script>

<template>
    <footer class="sfx-agent-footer">
        <div class="sfx-agent-next">
            <span class="sfx-agent-seg-label sfx-t-caption">建议下一步</span>
            <div class="sfx-agent-quick">
                <button v-for="action in quickActions" :key="action.id" type="button"
                    class="sfx-agent-quick-btn sfx-t-sm" :disabled="ws.isAsking.value" @click="handleQuick(action)">
                    <component :is="action.icon" :size="14" /> {{ action.label }}
                </button>
            </div>
        </div>

        <AgentInputForm v-if="!hideFooterInput" ref="inputFormRef" :ws="ws" :autofocus="true" />
    </footer>
</template>

<style scoped>
/* ========== 底部：快捷操作 + 输入区 ========== */
.sfx-agent-footer {
    border-top: 1px solid var(--border-subtle);
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    background: var(--surface-panel);
}

.sfx-agent-next {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

.sfx-agent-seg-label {
    font-size: var(--caption-size);
    font-weight: 600;
    color: var(--text-muted);
    text-transform: none;
    letter-spacing: 0.02em;
}

.sfx-agent-quick {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
}

.sfx-agent-quick-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    height: 34px;
    padding: 0 var(--space-3);
    border-radius: var(--radius-full);
    border: 1px solid var(--border-default);
    background: var(--surface-panel);
    color: var(--ink-700);
    transition: background var(--duration-fast) var(--ease-out),
        border-color var(--duration-fast) var(--ease-out),
        color var(--duration-fast) var(--ease-out);
}

.sfx-agent-quick-btn:hover:not(:disabled) {
    background: var(--ink-50);
    border-color: var(--ink-200);
    color: var(--ink-900);
}

.sfx-agent-quick-btn:disabled {
    color: var(--text-disabled);
    cursor: not-allowed;
}
</style>
