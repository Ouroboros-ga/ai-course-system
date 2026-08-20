<script setup>
import { inject } from 'vue'
import { CircleAlert } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'

const mediaBuild = inject('mediaBuild')
const { providerReady, providerError, providerDisplayName, provider, notice, error } = mediaBuild
</script>

<template>
    <div class="provider-bar" aria-label="语音服务状态">
        <SfxBadge v-if="providerReady" tone="green">语音服务可用</SfxBadge>
        <SfxBadge v-else-if="providerError" tone="red">语音服务未确认</SfxBadge>
        <SfxBadge v-else tone="amber">正在确认语音服务</SfxBadge>
        <span v-if="providerReady" class="provider-bar-name">{{ providerDisplayName }}</span>
    </div>
    <p v-if="providerReady" class="provider-runtime-status" role="status">{{ providerDisplayName }}：{{ provider?.message
        }}</p>
    <p v-else-if="provider?.message" class="provider-runtime-status is-blocked" role="alert">{{ provider?.message }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="action-error" role="alert">
        <CircleAlert :size="16" /> {{ error }}
    </p>
    <p v-if="providerError" class="action-error" role="alert">
        <CircleAlert :size="16" /> {{ providerError }}
    </p>
</template>

<style scoped>
.provider-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
    flex-wrap: wrap;
}

.provider-bar-name {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--caption-size);
}

.provider-runtime-status {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--caption-size);
}

.provider-runtime-status.is-blocked {
    color: var(--red-700);
}

.notice,
.action-error {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-3);
    border-radius: var(--radius-md);
    font-size: var(--ui-sm-size);
    line-height: 1.5;
    flex-shrink: 0;
}

.notice {
    border: 1px solid var(--ink-300);
    background: var(--ink-100);
    color: var(--ink-700);
}

.action-error {
    border: 1px solid var(--red-300);
    background: var(--red-100);
    color: var(--red-700);
}
</style>
