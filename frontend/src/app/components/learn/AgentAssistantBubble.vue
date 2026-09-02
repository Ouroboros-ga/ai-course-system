<script setup>
import { computed } from 'vue'
import { BookMarked, BookOpen, CornerUpLeft, MapPinned, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import CodingChallengeCard from './CodingChallengeCard.vue'
import { useSettingsStore } from '@/stores/userSettings'
import { renderContent } from '@/utils/markdownRenderer'

const settings = useSettingsStore()

const props = defineProps({
    message: { type: Object, required: true },
    activeAdjustment: { type: Object, default: null },
    adjustmentBusy: { type: Boolean, default: false },
    challengeBusy: { type: Boolean, default: false },
})
const emit = defineEmits([
    'accept-adjustment',
    'dismiss-adjustment',
    'return-adjustment',
    'retry-opening-review',
    'abandon-adjustment',
    'retry',
    'challenge-start',
    'challenge-dismiss',
    'challenge-replace',
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
    // 完整的 proposal（有播放坐标）
    if (adjustment?.status === 'proposed'
        && adjustment?.review_target
        && !adjustment?.declined_at
        && !adjustment?.invalidated_at
        && !isActiveAdjustment(adjustment)) {
        return true
    }
    // 简化推荐（无播放坐标，仅文本提示）
    if (adjustment?.type === 'simple_recommendation'
        && adjustment?.recommended_concept_name) {
        return true
    }
    return false
}

function isSimpleRecommendation(adjustment) {
    return adjustment?.type === 'simple_recommendation'
}

function retry() {
    if (props.message?.retryQuestion) emit('retry', props.message)
}

// 渲染 Markdown 内容
const renderedContent = computed(() => {
    return renderContent(props.message?.content || '')
})
</script>

<template>
    <div class="sfx-agent-msg-row is-assistant">
        <span class="sfx-agent-avatar sfx-agent-avatar-ai" aria-hidden="true">
            <img :src="settings.currentAvatarPath" alt="课程智能体头像">
        </span>
        <div class="sfx-agent-msg-bubble-wrap is-assistant">
            <div class="sfx-agent-answer" :class="{ 'is-error': message.error }">
                <!-- ① 系统观察（§6.7）：弱化显示为元信息 -->
                <div class="sfx-agent-observe sfx-t-caption" v-if="message.nodeId != null">
                    <span class="sfx-agent-seg-label">系统观察</span>
                    <span>结合当前知识点<template v-if="message.page"> · 第 {{ message.page }} 页</template></span>
                </div>

                <!-- ③ 回答 - 更宽松的正文排版，支持 Markdown 渲染 -->
                <div class="sfx-agent-answer-text sfx-t-body" v-html="renderedContent"></div>

                <div v-if="message.lowConfidence" class="sfx-agent-lowconf sfx-t-caption">
                    <TriangleAlert :size="13" /> 本次回答置信度较低，建议核对下方原文引用。
                </div>
                <div v-if="message.fallbackNotice" class="sfx-agent-lowconf sfx-t-caption">
                    <TriangleAlert :size="13" /> {{ message.fallbackNotice }}
                </div>

                <CodingChallengeCard
                    v-if="message.codingChallengeOffer"
                    :offer="message.codingChallengeOffer"
                    :busy="challengeBusy"
                    @start="$emit('challenge-start', $event)"
                    @dismiss="$emit('challenge-dismiss', $event)"
                    @replace="$emit('challenge-replace', $event)"
                />

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

                <!-- 学科参考（R14）：权威教材补充参考，非课程正式证据 -->
                <ul v-if="message.disciplineReferences?.length" class="sfx-agent-discipline">
                    <li class="sfx-agent-seg-label sfx-agent-citations-title">学科参考</li>
                    <li v-for="(ref, index) in message.disciplineReferences" :key="ref.node_id || index"
                        class="sfx-agent-citation is-discipline">
                        <BookOpen :size="13" />
                        <span>{{ ref.name }}<template v-if="ref.course">（{{ ref.course }}）</template></span>
                        <span v-if="ref.source_title" class="sfx-t-caption">{{ ref.source_title }}</span>
                    </li>
                </ul>

                <!-- AI 生成内容标识（伦理声明 §三：明显标识 AI 输出） -->
                <p class="sfx-agent-ai-badge sfx-t-caption">
                    <BookOpen :size="12" /> 本回答由 AI 生成，供学习参考；课程依据以教师发布内容为准。
                </p>

                <!-- 回顾建议：仅在消息内出现，不额外持久化到页面底部 -->
                <section v-if="isVisibleProposal(message.learningAdjustment)" class="sfx-agent-adjustment"
                    aria-label="学习回顾建议">
                    <!-- 简化推荐：只显示文本提示，无播放跳转 -->
                    <template v-if="isSimpleRecommendation(message.learningAdjustment)">
                        <p class="sfx-agent-adjustment-title sfx-t-ui">
                            <MapPinned :size="15" /> 建议回顾：{{ message.learningAdjustment.recommended_concept_name }}
                        </p>
                        <p class="sfx-t-caption">{{ message.learningAdjustment.reason || '该知识点是理解当前内容的基础' }}</p>
                        <p class="sfx-t-caption" style="margin-top: var(--space-2); color: var(--text-tertiary); font-style: italic;">
                            💡 提示：在播放课程内容时提问，可以直接跳转到相关知识点
                        </p>
                    </template>
                    
                    <!-- 完整推荐：可以播放跳转 -->
                    <template v-else>
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
                    </template>
                </section>

                <!-- 2026-08-19 修复：只在当前消息真正有推荐提案时显示绿色框，避免显示上次残留状态 -->
                <section v-if="message.learningAdjustment && isActiveAdjustment(message.learningAdjustment)" class="sfx-agent-adjustment is-active"
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
                            <!-- 放弃回顾是无条件出口：busy 卡死时也必须可点击，否则无法解除卡死 -->
                            <SfxButton variant="tertiary" size="sm"
                                @click="$emit('abandon-adjustment')">放弃回顾</SfxButton>
                        </div>
                    </template>
                </section>

                <SfxButton v-if="message.error" variant="secondary" size="sm" @click="retry">
                    <template #icon><RefreshCw :size="13" /></template>
                    重试
                </SfxButton>
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

.sfx-agent-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: var(--radius-full);
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

/* Markdown 渲染样式 */
.sfx-agent-answer-text :deep(h1),
.sfx-agent-answer-text :deep(h2),
.sfx-agent-answer-text :deep(h3) {
    margin: var(--space-3) 0 var(--space-2) 0;
    font-weight: 600;
    color: var(--text-primary);
}

.sfx-agent-answer-text :deep(h1) { font-size: 1.5em; }
.sfx-agent-answer-text :deep(h2) { font-size: 1.3em; }
.sfx-agent-answer-text :deep(h3) { font-size: 1.15em; }

.sfx-agent-answer-text :deep(p) {
    margin: var(--space-2) 0;
}

.sfx-agent-answer-text :deep(ul),
.sfx-agent-answer-text :deep(ol) {
    margin: var(--space-2) 0;
    padding-left: var(--space-6);
}

.sfx-agent-answer-text :deep(li) {
    margin: var(--space-1) 0;
}

.sfx-agent-answer-text :deep(code) {
    padding: 2px 6px;
    background: var(--surface-cool);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 0.9em;
}

.sfx-agent-answer-text :deep(pre) {
    margin: var(--space-3) 0;
    padding: var(--space-4);
    background: var(--surface-cool);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    overflow-x: auto;
}

.sfx-agent-answer-text :deep(pre code) {
    padding: 0;
    background: none;
    border: none;
    font-size: 0.875em;
}

.sfx-agent-answer-text :deep(blockquote) {
    margin: var(--space-3) 0;
    padding-left: var(--space-4);
    border-left: 3px solid var(--border-default);
    color: var(--text-secondary);
}

.sfx-agent-answer-text :deep(strong) {
    font-weight: 600;
}

.sfx-agent-answer-text :deep(em) {
    font-style: italic;
}

.sfx-agent-answer-text :deep(a) {
    color: var(--ink-600);
    text-decoration: underline;
}

.sfx-agent-answer-text :deep(a:hover) {
    color: var(--ink-700);
}

/* KaTeX 公式样式 */
.sfx-agent-answer-text :deep(.katex-block) {
    margin: var(--space-3) 0;
    overflow-x: auto;
}

.sfx-agent-answer-text :deep(.katex-inline) {
    display: inline;
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

/* 学科参考（R14）：琥珀左边线区别于墨蓝"依据"，明示补充参考身份 */
.sfx-agent-discipline {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    list-style: none;
    border-left: 3px solid var(--amber-300);
    background: var(--amber-100);
    border-radius: var(--radius-sm);
}

.sfx-agent-citation.is-discipline {
    color: var(--text-secondary);
}

.sfx-agent-citation.is-discipline span:first-of-type {
    color: var(--text-primary);
}

/* AI 生成内容标识（伦理声明 §三） */
.sfx-agent-ai-badge {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    margin: 0;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--surface-soft);
    color: var(--text-muted);
    font-size: var(--caption-size);
    line-height: 1.5;
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
