<script setup>
import { BookMarked, CornerUpLeft, MapPinned, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
    message: { type: Object, required: true },
    activeAdjustment: { type: Object, default: null },
    adjustmentBusy: { type: Boolean, default: false },
})
const emit = defineEmits([
    'accept-adjustment',
    'dismiss-adjustment',
    'return-adjustment',
    'retry-opening-review',
    'abandon-adjustment',
    'retry',
])

function reviewPage(adjustment) {
    return adjustment?.review_target?.page ?? null
}

function isActiveAdjustment(adjustment) {
    return String(props.activeAdjustment?.proposal?.adjustment_id || '') === String(adjustment?.adjustment_id || '')
}

function isReviewingAdjustment(adjustment) {
    return isActiveAdjustment(adjustment) && props.activeAdjustment?.navigationStatus === 'reviewing'
}

function isVisibleProposal(adjustment) {
    return adjustment?.status === 'proposed'
        && !adjustment?.declined_at
        && !adjustment?.invalidated_at
        && !isActiveAdjustment(adjustment)
}

function retry() {
    if (props.message?.retryQuestion) emit('retry', props.message)
}
</script>

<template>
    <div class="sfx-agent-msg-row is-assistant">
        <span class="sfx-agent-avatar sfx-agent-avatar-ai" aria-hidden="true">
            <span class="sfx-agent-avatar-initials">AI</span>
        </span>
        <div class="sfx-agent-msg-bubble-wrap is-assistant">
            <div class="sfx-agent-answer" :class="{ 'is-error': message.error }">
                <!-- ① 系统观察（§6.7）：弱化显示为元信息 -->
                <div class="sfx-agent-observe sfx-t-caption" v-if="message.nodeId != null">
                    <span class="sfx-agent-seg-label">系统观察</span>
                    <span>结合当前知识点<template v-if="message.page"> · 第 {{ message.page }} 页</template></span>
                </div>

                <!-- ③ 回答 - 更宽松的正文排版 -->
                <div class="sfx-agent-answer-text sfx-t-body">{{ message.content }}</div>

                <div v-if="message.lowConfidence" class="sfx-agent-lowconf sfx-t-caption">
                    <TriangleAlert :size="13" /> 本次回答置信度较低，建议核对下方原文引用。
                </div>
                <div v-if="message.fallbackNotice" class="sfx-agent-lowconf sfx-t-caption">
                    <TriangleAlert :size="13" /> {{ message.fallbackNotice }}
                </div>

                <!-- ② 依据：原文引用（design.md 4.5 左 3px 墨蓝边） -->
                <ul v-if="message.citations?.length" class="sfx-agent-citations">
                    <li class="sfx-agent-seg-label sfx-agent-citations-title">依据</li>
                    <li v-for="(citation, index) in message.citations" :key="citation.id || index"
                        class="sfx-agent-citation">
                        <BookMarked :size="13" />
                        <span>{{ citation.title || citation.source || '课程资料' }}</span>
                        <span v-if="citation.page != null" class="sfx-t-caption">p.{{ citation.page }}</span>
                    </li>
                </ul>

                <!-- 回顾建议：仅在消息内出现，不额外持久化到页面底部 -->
                <section v-if="isVisibleProposal(message.learningAdjustment)" class="sfx-agent-adjustment"
                    aria-label="学习回顾建议">
                    <p class="sfx-agent-adjustment-title sfx-t-ui">
                        <MapPinned :size="15" /> 建议回顾第 {{ reviewPage(message.learningAdjustment) }} 页
                    </p>
                    <p class="sfx-t-caption">
                        回顾后由你自行选择何时返回原学习位置。
                    </p>
                    <div class="sfx-agent-adjustment-actions">
                        <SfxButton variant="secondary" size="sm" :loading="adjustmentBusy" :disabled="adjustmentBusy"
                            @click="$emit('accept-adjustment', message.learningAdjustment)">回顾并补充讲解</SfxButton>
                        <SfxButton variant="tertiary" size="sm" :disabled="adjustmentBusy"
                            @click="$emit('dismiss-adjustment', message.learningAdjustment)">继续当前位置</SfxButton>
                    </div>
                </section>

                <section v-if="isActiveAdjustment(message.learningAdjustment)" class="sfx-agent-adjustment is-active"
                    aria-label="正在回顾">
                    <template v-if="isReviewingAdjustment(message.learningAdjustment)">
                        <p class="sfx-agent-adjustment-title sfx-t-ui">
                            <CornerUpLeft :size="15" /> 正在回顾，原学习位置已保留
                        </p>
                        <SfxButton variant="secondary" size="sm" :loading="adjustmentBusy" :disabled="adjustmentBusy"
                            @click="$emit('return-adjustment')">返回原学习位置</SfxButton>
                    </template>
                    <template v-else>
                        <p class="sfx-agent-adjustment-title sfx-t-ui">
                            <TriangleAlert :size="15" /> 已确认回顾，尚未打开内容
                        </p>
                        <p class="sfx-t-caption">原学习位置仍已保留，打开成功后可自行返回。</p>
                        <div class="sfx-agent-adjustment-actions">
                            <SfxButton variant="secondary" size="sm" :loading="adjustmentBusy"
                                :disabled="adjustmentBusy" @click="$emit('retry-opening-review')">重试打开回顾</SfxButton>
                            <SfxButton variant="tertiary" size="sm" :disabled="adjustmentBusy"
                                @click="$emit('abandon-adjustment')">放弃回顾</SfxButton>
                        </div>
                    </template>
                </section>

                <button v-if="message.error" type="button" class="sfx-agent-retry sfx-t-ui" @click="retry">
                    <RefreshCw :size="13" /> 重试
                </button>
            </div>
        </div>
    </div>
</template>

<style scoped>
/* ========== 通用头像（与头部/消息区共用，作用域内自持） ========== */
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

.sfx-agent-avatar-ai {
    background: linear-gradient(135deg, var(--ink-700), var(--ink-500));
    color: var(--text-inverse);
    box-shadow: 0 1px 2px rgb(20 33 61 / 18%);
}

.sfx-agent-avatar-initials {
    letter-spacing: 0.02em;
}

/* ========== 智能体气泡 ========== */
.sfx-agent-answer {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-4) var(--space-5);
    background: var(--surface-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 4px var(--radius-md) var(--radius-md) var(--radius-md);
    color: var(--text-primary);
    box-shadow: 0 1px 2px rgb(16 26 49 / 4%);
}

.sfx-agent-answer.is-error {
    background: var(--red-100);
    border-color: var(--red-300);
}

/* 结构化分段标签（§6.7） */
.sfx-agent-seg-label {
    font-size: var(--caption-size);
    font-weight: 600;
    color: var(--text-muted);
    text-transform: none;
    letter-spacing: 0.02em;
}

/* 系统观察：弱化元信息 */
.sfx-agent-observe {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--surface-cool);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    width: fit-content;
}

/* 回答正文：更宽松的阅读排版 */
.sfx-agent-answer-text {
    color: var(--text-primary);
    font-size: var(--body-md-size);
    line-height: 1.85;
    letter-spacing: 0.005em;
    word-break: break-word;
    white-space: pre-wrap;
}

/* 低置信度提示 */
.sfx-agent-lowconf {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--amber-100);
    border: 1px solid var(--amber-200);
    border-radius: var(--radius-sm);
    color: var(--amber-700);
    width: fit-content;
}

/* 依据：原文引用 */
.sfx-agent-citations {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    background: var(--surface-cool);
    border-left: 3px solid var(--ink-500);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    padding: var(--space-3) var(--space-4);
    margin: 0;
    list-style: none;
}

.sfx-agent-citations-title {
    margin-bottom: var(--space-1);
}

.sfx-agent-citation {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-sm-size);
    color: var(--text-secondary);
    line-height: 1.6;
}

/* 学习回顾建议/正在回顾卡片 */
.sfx-agent-adjustment {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--amber-300);
    border-radius: var(--radius-md);
    background: var(--amber-100);
}

.sfx-agent-adjustment.is-active {
    border-color: var(--green-300);
    background: var(--green-100);
}

.sfx-agent-adjustment-title {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
}

.sfx-agent-adjustment-title {
    color: var(--amber-800);
    font-weight: 600;
}

.sfx-agent-adjustment.is-active .sfx-agent-adjustment-title {
    color: var(--green-800);
}

.sfx-agent-adjustment>.sfx-t-caption {
    margin: 0;
    color: var(--text-secondary);
}

.sfx-agent-adjustment-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-1);
}

/* 重试按钮 */
.sfx-agent-retry {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    color: var(--red-700);
    font-weight: 500;
    align-self: flex-start;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--red-50);
}

/* 响应式：窄屏下回答气泡收窄 */
@media (max-width: 900px) {
    .sfx-agent-answer {
        padding: var(--space-3) var(--space-4);
        gap: var(--space-3);
    }

    .sfx-agent-avatar {
        width: 32px;
        height: 32px;
    }
}
</style>
