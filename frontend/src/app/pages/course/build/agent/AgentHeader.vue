<script setup>
import { Sparkles, X } from 'lucide-vue-next'
import { useSettingsStore } from '@/stores/userSettings';

const settings = useSettingsStore();

defineEmits(['close'])
</script>

<template>
    <header class="agent-header">
        <div class="agent-heading">
            <span class="agent-mark">
                <!-- TODO:更改图标 -->
                <img :src="settings.currentAvatarPath" alt="助教智能体头像">
            </span>
            <div>
                <h2>助教智能体</h2>
                <p>受控提案模式</p>
            </div>
        </div>
        <button type="button" class="close-agent" aria-label="关闭助教智能体" @click="$emit('close')">
            <X :size="18" />
        </button>
    </header>
</template>

<style scoped>
/* ── 头部 ── */
.agent-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    min-height: 56px;
    padding: 0 var(--space-4);
    border-bottom: 1px solid var(--border-default);
    flex-shrink: 0;
}

.agent-heading {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.agent-mark {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: var(--radius-md);
    background: var(--ink-100);
    color: var(--ink-700);
    overflow: hidden;
}

.agent-mark img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: var(--radius-md);
}

.agent-heading h2 {
    margin: 0;
    font-size: var(--title-3-size);
    line-height: 1.2;
    color: var(--text-primary);
}

.agent-heading p {
    margin: 2px 0 0;
    color: var(--text-muted);
    font-size: var(--caption-size);
}

/* 关闭/收回按钮：任何断点都显示（桌面端收回为工具球） */
.close-agent {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
}

.close-agent:hover {
    background: var(--surface-cool);
}
</style>
