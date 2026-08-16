<script setup>
import { inject } from 'vue'

const mediaBuild = inject('mediaBuild')
const { selectedScript, scriptLabel, selectedCharCount, selectedByteCount } = mediaBuild
</script>

<template>
    <section class="selected-script" aria-labelledby="selected-script-title">
        <div class="selected-script-heading">
            <span>当前讲稿</span>
            <h3 id="selected-script-title">{{ scriptLabel(selectedScript) }}</h3>
            <p>{{ selectedCharCount }} 字 · {{ selectedByteCount }} UTF-8 字节 · {{ selectedScript.locked ?
                '已锁定，不会在媒体处理中改写' : '草稿内容将按本次提交固定' }}</p>
        </div>
        <div class="script-preview">{{ selectedScript.content }}</div>
    </section>
</template>

<style scoped>
.selected-script {
    display: grid;
    grid-template-columns: minmax(180px, .6fr) minmax(0, 1.4fr);
    gap: var(--space-4);
    padding: var(--space-4);
    border-left: 3px solid var(--color-focus);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    background: var(--surface-cool);
    max-height: 340px;
    min-height: 140px;
    overflow: hidden;
    flex-shrink: 0;
}

.selected-script-heading {
    display: grid;
    align-content: start;
    gap: var(--space-1);
    overflow-y: auto;
    min-height: 0;
}

.selected-script-heading>span {
    color: var(--text-muted);
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
}

.selected-script-heading h3 {
    margin: 0;
    color: var(--text-primary);
    font-size: var(--title-3-size);
    line-height: var(--title-3-line);
}

.selected-script-heading p {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--caption-size);
    line-height: 1.5;
}

.script-preview {
    max-height: 100%;
    overflow-y: auto;
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
    line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

@media (max-width: 960px) {
    .selected-script {
        grid-template-columns: 1fr;
        max-height: none;
    }
}

@media (max-width: 700px) {
    .selected-script {
        max-height: none;
        overflow: visible;
    }

    .selected-script-heading {
        overflow: visible;
    }
}
</style>
