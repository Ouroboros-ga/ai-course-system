<script setup>
import { Check } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import { operationDisplayLabel } from '@/app/lib/prepAgentPresentation.js'

defineProps({
    pending: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    deciding: { type: String, default: '' },
})
defineEmits(['decide', 'refresh'])

function operationActionLabel(operation) {
    if (operation === 'remove') return '移除'
    if (operation === 'add') return '新增'
    return '修改'
}
</script>

<template>
    <section v-if="pending.length" class="proposal-section">
        <div class="section-heading">
            <div>
                <p class="panel-kicker">教师审核</p>
                <h3>待确认提案</h3>
            </div>
            <SfxButton variant="tertiary" size="sm" :loading="loading" @click="$emit('refresh')">刷新</SfxButton>
        </div>
        <article v-for="proposal in pending" :key="proposal.proposal_id" class="proposal-card">
            <header>
                <span>{{ proposal.tool_name }}</span>
                <SfxBadge tone="amber">待审核</SfxBadge>
            </header>
            <p class="proposal-reason">{{ proposal.reason || '智能体提出了一项课程草稿修改。' }}</p>
            <div v-for="operation in proposal.operations" :key="operation.op_id" class="proposal-operation">
                <div><strong>{{ operationDisplayLabel(operation) }}</strong><span>{{
                    operationActionLabel(operation.operation) }}</span></div>
                <del v-if="operation.before">{{ operation.before }}</del>
                <ins v-if="operation.after">{{ operation.after }}</ins>
                <p v-if="operation.reason">{{ operation.reason }}</p>
                <div v-if="operation.evidence_refs?.length" class="evidence-refs">证据：{{ operation.evidence_refs.length
                    }} 条</div>
            </div>
            <footer>
                <SfxButton size="sm" :loading="deciding === proposal.proposal_id"
                    @click="$emit('decide', proposal, true)">
                    <Check :size="15" /> 接受提案
                </SfxButton>
                <SfxButton size="sm" variant="danger" :disabled="Boolean(deciding)"
                    @click="$emit('decide', proposal, false)">拒绝</SfxButton>
            </footer>
        </article>
    </section>
</template>

<style scoped>
/* ── 通用（与上下文面板共用，作用域内自持） ── */
.panel-kicker {
    margin: 0 0 var(--space-1);
    font-size: var(--caption-size);
    font-weight: 650;
    letter-spacing: 0.06em;
    color: var(--ink-500);
}

.section-heading {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
    color: var(--ink-700);
}

.section-heading h3 {
    margin: 0;
    font-size: var(--title-3-size);
    color: var(--text-primary);
}

/* ── 提案卡片 ── */
.proposal-section {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-2);
}

.proposal-card {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: var(--surface-panel);
}

.proposal-card>header,
.proposal-card>footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
}

.proposal-card>header>span {
    font-size: var(--ui-sm-size);
    font-weight: 600;
    color: var(--ink-900);
}

.proposal-card>footer {
    justify-content: flex-end;
}

.proposal-reason {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.proposal-operation {
    display: grid;
    gap: var(--space-1);
    padding: var(--space-2);
    border-left: 3px solid var(--green-500);
    background: var(--green-100);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.proposal-operation>div:first-child {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    color: var(--text-muted);
}

.proposal-operation>div:first-child span {
    font-size: var(--caption-size);
}

.proposal-operation del {
    color: var(--red-700);
    font-size: var(--ui-sm-size);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.proposal-operation ins {
    color: var(--green-700);
    font-size: var(--ui-sm-size);
    text-decoration: none;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.proposal-operation p {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--caption-size);
    line-height: 1.45;
    overflow-wrap: anywhere;
}

.evidence-refs {
    color: var(--ink-500);
    font-size: var(--caption-size);
}

.proposal-operation code {
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: var(--caption-size);
}
</style>
