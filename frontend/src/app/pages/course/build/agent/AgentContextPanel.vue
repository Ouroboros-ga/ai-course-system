<script setup>
import { computed, ref } from 'vue'
import { BookOpenText, ChevronDown } from 'lucide-vue-next'

const props = defineProps({
    selectedNode: { type: Object, default: null },
    evidence: { type: Array, default: () => [] },
})

// 上下文面板折叠状态（默认收起，减少遮挡编辑区）
const contextCollapsed = ref(true)
function toggleContext() { contextCollapsed.value = !contextCollapsed.value }

const selectedTitle = computed(() => props.selectedNode?.title || '')
</script>

<template>
    <section class="agent-context" :class="{ 'is-collapsed': contextCollapsed }">
        <button type="button" class="context-toggle" @click="toggleContext">
            <div class="context-toggle-left">
                <p class="panel-kicker">当前工作范围</p>
                <strong v-if="selectedNode">{{ selectedTitle }}</strong>
                <strong v-else>未选择节点</strong>
            </div>
            <ChevronDown :size="20" class="context-chevron" :class="{ 'is-open': !contextCollapsed }" />
        </button>

        <div v-show="!contextCollapsed" class="context-body">
            <section v-if="selectedNode" class="evidence-section">
                <div class="section-heading">
                    <div>
                        <p class="panel-kicker">原文证据</p>
                        <h3>节点来源</h3>
                    </div>
                    <BookOpenText :size="18" />
                </div>
                <p v-if="!evidence.length" class="empty-copy">此节点暂未关联可显示的原文区块。</p>
                <article v-for="item in evidence" :key="item.block_id" class="evidence-card">
                    <p>{{ item.text || '原文区块为空' }}</p>
                    <footer>
                        <code>{{ item.block_id }}</code>
                        <span v-if="item.page">第 {{ item.page }} 页</span>
                        <span v-if="item.confidence != null">置信度 {{ Math.round(item.confidence * 100) }}%</span>
                    </footer>
                </article>
            </section>
        </div>
    </section>
</template>

<style scoped>
/* ── 上下文面板（可折叠） ── */
.agent-context {
    flex-shrink: 0;
    border-bottom: 1px solid var(--border-default);
    background: var(--surface-cool);
}

.context-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    min-height: 56px;
    padding: var(--space-4) var(--space-4);
    border: 0;
    background: transparent;
    cursor: pointer;
    text-align: left;
    transition: background var(--duration-fast) var(--ease-out);
}

.context-toggle:hover {
    background: var(--ink-100);
}

.context-toggle-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
}

.context-toggle-left strong {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.context-chevron {
    color: var(--text-muted);
    transition: transform var(--duration-fast) var(--ease-out);
    flex-shrink: 0;
}

.context-chevron.is-open {
    transform: rotate(180deg);
}

.context-body {
    padding: 0 var(--space-4) var(--space-3);
}

/* ── 通用（与提案区共用，作用域内自持） ── */
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

.empty-copy {
    margin: 0;
    padding: var(--space-3);
    color: var(--text-muted);
    font-size: var(--ui-sm-size);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-md);
}

/* ── 证据卡片 ── */
.evidence-section {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-3);
    /* 证据多时面板内独立滚动,避免撑爆上下文区导致无法滚动 */
    max-height: 40vh;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-right: var(--space-1);
}

.evidence-card {
    padding: var(--space-3);
    background: var(--surface-panel);
    border-left: 3px solid var(--ink-500);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
}

.evidence-card p {
    margin: 0;
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
    line-height: 1.6;
    white-space: pre-wrap;
}

.evidence-card footer {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-2);
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.evidence-card code {
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: var(--caption-size);
}
</style>
