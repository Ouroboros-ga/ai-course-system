<script setup>
import { inject, onMounted, ref } from 'vue'
import { Volume2 } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'

const mediaBuild = inject('mediaBuild')
const { previewPlayback, previewNodeLabel, scriptLabel, selectedScript, selectedBatchItem } = mediaBuild

const panelEl = ref(null)
onMounted(() => {
    mediaBuild.registerPreviewPanelScroll(() => panelEl.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
})
</script>

<template>
    <section ref="panelEl" class="preview-panel" aria-labelledby="preview-title">
        <header class="panel-heading">
            <div>
                <p>学习端同款预览</p>
                <h3 id="preview-title">{{ previewPlayback ? previewNodeLabel : scriptLabel(selectedScript) }}</h3>
            </div>
            <SfxBadge :tone="previewPlayback ? 'green' : 'neutral'">{{ previewPlayback ? '可试听' : '未生成' }}</SfxBadge>
        </header>
        <div v-if="previewPlayback" class="preview-body">
            <p v-if="previewPlayback.ppt_timeline?.length">PPT：{{previewPlayback.ppt_timeline.map(item => '第 ' +
                item.ppt_page + ' 页').join('、') }}</p>
            <p v-else>PPT 映射尚未完成；试听可正常进行，但最终发布需要先完成映射。</p>
            <p v-if="previewPlayback.subtitle_segments?.length">字幕：{{previewPlayback.subtitle_segments.map(item =>
                item.text).join('')}}</p>
            <p v-else>字幕与数字人时间轴尚未生成；试听可正常进行，但最终发布需要先生成。</p>
        </div>
        <div v-else class="preview-empty">
            <Volume2 :size="20" />
            <p>{{ selectedBatchItem?.audio_object_key ? '正在准备学习端同款预览…' :
                '该知识点尚未生成音频。在批量面板完成生成后，选中节点即可自动试听；也可在批量列表中点击“试听”。' }}</p>
        </div>
    </section>
</template>

<style scoped>
.preview-panel {
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: var(--surface-panel);
    overflow: hidden;
    flex-shrink: 0;
    scroll-margin-top: var(--space-3);
}

.panel-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.panel-heading p {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
}

.panel-heading h3 {
    margin: 2px 0 0;
    color: var(--text-primary);
    font-size: var(--ui-md-size);
}

.preview-body {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
}

.preview-body p {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
    line-height: 1.55;
    overflow-wrap: anywhere;
}

.preview-empty {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-4);
    color: var(--text-muted);
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.preview-empty p {
    margin: 0;
}

/* 移动端（design.md §12.5）：标题区允许换行，避免挤压状态 */
@media (max-width: 760px) {
    .panel-heading {
        flex-wrap: wrap;
    }
}
</style>
