<script setup>
import { inject, nextTick, ref, watch } from 'vue'

const mediaBuild = inject('mediaBuild')
const { previewItem } = mediaBuild

const audioEl = ref(null)
// 播放器元素由 `:key` 随 audio_url 重建；元素就绪后向组合式函数注册，
// 让试听/自动预览能触发 `audio.play()`（组合式函数不直接持有 DOM）。
watch(() => previewItem?.value?.audio_url, async () => {
    await nextTick()
    mediaBuild.registerPreviewAudio(audioEl.value)
}, { immediate: true })
</script>

<template>
    <div v-if="previewItem?.audio_url" class="preview-dock" role="region" aria-label="试听播放器">
        <span class="preview-dock-label">试听</span>
        <audio ref="audioEl" :key="previewItem.audio_url" :src="previewItem.audio_url" controls preload="metadata" />
    </div>
</template>

<style scoped>
.preview-dock {
    position: sticky;
    bottom: calc(var(--space-3) * -1);
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: 0 calc(var(--space-6) * -1) calc(var(--space-3) * -1);
    padding: var(--space-2) var(--space-4);
    background: var(--surface-panel);
    border-top: 1px solid var(--border-default);
    flex-shrink: 0;
    z-index: 5;
}

.preview-dock-label {
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
    color: var(--text-muted);
    flex-shrink: 0;
}

.preview-dock audio {
    flex: 1;
    min-width: 0;
    height: 36px;
}
</style>
