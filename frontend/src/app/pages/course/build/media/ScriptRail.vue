<script setup>
import { inject } from 'vue'
import { Sparkles, Volume2 } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const mediaBuild = inject('mediaBuild')
const { scripts, selectedScriptId, batchNodeIds, canGenerate, acting, scriptLabel, scriptItemAudio, previewBatchItem, toggleBatchNode } = mediaBuild
</script>

<template>
    <aside class="script-rail" aria-label="可生成媒体的讲稿知识点">
        <header class="rail-header">
            <div><span>讲稿知识点</span><small>{{ scripts.length }} 个可用</small></div>
            <SfxBadge :tone="canGenerate ? 'ink' : 'red'">{{ canGenerate ? '可创建' : '无生成权限' }}</SfxBadge>
        </header>
        <p class="rail-note">点击行选中并自动试听；行首勾选参与批量生成。</p>
        <div v-if="scripts.length" class="script-list">
            <div v-for="script in scripts" :key="script.script_node_id" class="script-item-row"
                :class="{ selected: selectedScriptId === script.script_node_id }"
                @click="selectedScriptId = script.script_node_id">
                <label class="script-check" aria-label="批量生成勾选" @click.stop>
                    <input type="checkbox" :checked="batchNodeIds.includes(Number(script.script_node_db_id))"
                        @change="toggleBatchNode(script)" />
                </label>
                <div class="script-item-copy">
                    <strong>{{ scriptLabel(script) }}</strong>
                    <small>{{ Array.from(script.content || '').length }} 字 · {{ script.locked ? '已锁定讲稿' : '草稿讲稿'
                        }}</small>
                </div>
                <SfxButton v-if="scriptItemAudio(script)" variant="secondary" size="sm"
                    :loading="acting === `preview-${scriptItemAudio(script).item_id}`" class="script-item-listen"
                    @click.stop="previewBatchItem(scriptItemAudio(script))">
                    <Volume2 :size="14" /> 试听
                </SfxButton>
            </div>
        </div>
        <div v-else class="rail-empty">
            <Sparkles :size="22" />
            <strong>还没有可用讲稿</strong>
            <p>先在第 03 步生成并确认一个有正文的讲稿知识点。</p>
        </div>
    </aside>
</template>

<style scoped>
.script-rail {
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--surface-panel);
    border-right: 1px solid var(--border-default);
}

.rail-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-3);
    border-bottom: 1px solid var(--border-subtle);
}

.rail-header>div {
    display: grid;
    gap: 1px;
}

.rail-header span {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
    font-weight: 650;
}

.rail-header small,
.rail-note {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.rail-note {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-subtle);
    line-height: 1.45;
}

.script-list {
    display: grid;
    align-content: start;
    gap: var(--space-1);
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-2);
}

.script-item-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 54px;
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background var(--duration-fast) var(--ease-out);
}

.script-item-row:hover {
    background: var(--surface-cool);
}

.script-item-row.selected {
    background: var(--ink-100);
    color: var(--ink-900);
}

.script-item-row.selected::before {
    position: absolute;
    left: 0;
    top: var(--space-2);
    bottom: var(--space-2);
    width: 3px;
    background: var(--ink-900);
    content: "";
    border-radius: var(--radius-full);
}

.script-check {
    display: grid;
    place-items: center;
    flex-shrink: 0;
}

.script-check input {
    width: 16px;
    height: 16px;
    margin: 0;
    accent-color: var(--ink-700);
    cursor: pointer;
}

.script-item-copy {
    display: grid;
    min-width: 0;
    flex: 1;
    gap: 2px;
}

.script-item-copy strong {
    font-size: var(--ui-sm-size);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.script-item-copy small {
    font-size: var(--caption-size);
    opacity: .8;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.script-item-listen {
    flex-shrink: 0;
}

.rail-empty {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    margin: auto;
    padding: var(--space-6);
    color: var(--text-muted);
    text-align: center;
}

.rail-empty strong {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
}

.rail-empty p {
    margin: 0;
    font-size: var(--caption-size);
    line-height: 1.5;
}

@media (max-width: 700px) {
    .script-rail {
        max-height: 260px;
        border-right: 0;
        border-bottom: 1px solid var(--border-default);
    }
}
</style>
