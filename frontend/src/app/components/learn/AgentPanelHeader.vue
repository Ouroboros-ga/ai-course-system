<script setup>
import { ExternalLink, Sparkles, X } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useSettingsStore } from '@/stores/userSettings';

const settings = useSettingsStore();
const router = useRouter();

const props = defineProps({
    anchor: { type: Object, default: null },
    courseId: { type: [String, Number], default: null },
})
defineEmits(['exit'])

function formatTime(seconds) {
    const value = Math.max(0, Number(seconds) || 0)
    return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
}

function goToNexus() {
    const query = {}
    if (props.courseId) query.courseId = props.courseId
    if (props.anchor?.sourceNodeTitle) query.contextNode = props.anchor.sourceNodeTitle
    router.push({ path: '/app/nexus', query })
}
</script>

<template>
    <header class="sfx-agent-header">
        <div class="sfx-agent-anchor">
            <div class="sfx-agent-title-row">
                <!-- TODO:替换图标 -->
                <span class="sfx-agent-avatar sfx-agent-avatar-ai">
                    <img :src="settings.currentAvatarPath" alt="课程智能体头像">
                </span>
                <div class="sfx-agent-title-col">
                    <span class="sfx-agent-title sfx-t-ui">课程智能体</span>
                    <span class="sfx-agent-anchor-text sfx-t-caption" v-if="anchor">
                        锚点：{{ anchor.sourceNodeTitle }}<template v-if="anchor.sourcePage"> · 第 {{ anchor.sourcePage }}
                            页</template><template v-if="anchor.sourceTime != null"> · {{ formatTime(anchor.sourceTime)
                            }}</template>
                    </span>
                </div>
            </div>
        </div>
        <div class="sfx-agent-header-actions">
            <!-- 学习页 Nexus 引流 CTA（idea 决策：带当前章节与课程去 Nexus 深入，不与助教 dock 发生布局冲突） -->
            <button
                type="button"
                class="sfx-agent-nexus-cta"
                title="把当前学习上下文带到 Nexus 工作区进行深度拆解或论文研究"
                @click="goToNexus"
            >
                <Sparkles :size="13" class="sfx-nexus-icon" />
                <span>Nexus 深入</span>
                <ExternalLink :size="12" />
            </button>
            <button type="button" class="sfx-agent-close" aria-label="关闭提问面板（Esc）" @click="$emit('exit')">
                <X :size="18" />
            </button>
        </div>
    </header>
</template>

<style scoped>
/* ========== 头部：智能体身份卡片 ========== */
.sfx-agent-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4);
    background: var(--surface-panel);
    border-bottom: 1px solid var(--border-subtle);
}

.sfx-agent-title-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
}

.sfx-agent-title-col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
}

.sfx-agent-title {
    font-weight: 600;
    color: var(--ink-900);
    font-size: var(--ui-md-size);
}

.sfx-agent-anchor-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-muted);
    max-width: 280px;
}

.sfx-agent-header-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.sfx-agent-nexus-cta {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    background: var(--nexus-accent-soft, #E8F2FE);
    color: var(--nexus-accent, #007AF4);
    border: 1px solid var(--nexus-accent-line, #A1D0FF);
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--duration-fast, 120ms);
}

.sfx-agent-nexus-cta:hover {
    background: var(--nexus-accent, #007AF4);
    color: #fff;
    border-color: var(--nexus-accent, #007AF4);
}

.sfx-nexus-icon {
    flex-shrink: 0;
}

.sfx-agent-close {
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    flex-shrink: 0;
}

.sfx-agent-close:hover {
    background: var(--surface-cool);
    color: var(--ink-700);
}

/* ========== 通用头像（与消息区共用，作用域内自持） ========== */
.sfx-agent-avatar {
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-full);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: var(--caption-size);
    line-height: 1;
    user-select: none;
}

.sfx-agent-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: var(--radius-full);
}

/* .sfx-agent-avatar-ai {
    background: linear-gradient(135deg, var(--ink-700), var(--ink-500));
    color: var(--text-inverse);
    box-shadow: 0 1px 2px rgb(20 33 61 / 18%);
} */

.sfx-agent-avatar-initials {
    letter-spacing: 0.02em;
}

/* 响应式：窄屏下头像缩小 */
@media (max-width: 900px) {
    .sfx-agent-avatar {
        width: 32px;
        height: 32px;
    }
}
</style>
