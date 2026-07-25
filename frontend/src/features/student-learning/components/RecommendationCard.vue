<script setup>
/**
 * 学习推荐卡片（批次3）。
 *
 * 接收一条 recommendation 对象（来自 /api/v1/cognitive/recommendations）：
 * - recommendation_type: 'review_prerequisite' | 'practice_more' | 'watch_visualization' | ...
 * - priority: 'high' | 'medium' | 'low'
 * - title, description: 展示文案
 * - reason_codes: 数组，需可读化
 * - evidence_refs: 引用的证据 ID 列表（可选展示）
 * - policy_version: 策略版本
 * - cognitive_snapshot: 认知快照摘要（含 confidence/abstain 等）
 * - is_locked: 教师锁定状态
 *
 * 数据不足语义：当 cognitive_snapshot.abstain===true 或 confidence<阈值时，
 * 显示「需要更多证据」而不是「判定弱」，避免武断结论。
 */
import { computed } from 'vue'
import {
  Check,
  ChevronRight,
  HelpCircle,
  Lightbulb,
  Lock,
  Sparkles,
  TriangleAlert,
} from 'lucide-vue-next'

const props = defineProps({
  recommendation: { type: Object, required: true },
  /** 是否禁用消费按钮（消费中） */
  consuming: { type: Boolean, default: false },
  /** 是否已消费（隐藏消费按钮） */
  consumed: { type: Boolean, default: false },
})

const emit = defineEmits(['consume'])

const LOW_CONFIDENCE_THRESHOLD = 0.5

const typeIcon = computed(() => {
  switch (props.recommendation?.recommendation_type) {
    case 'review_prerequisite':
      return HelpCircle
    case 'practice_more':
      return Check
    case 'watch_visualization':
      return Sparkles
    case 'ask_question':
      return Lightbulb
    default:
      return Lightbulb
  }
})

const priorityLabel = computed(() => {
  const p = props.recommendation?.priority
  if (p === 'high') return '高优先级'
  if (p === 'low') return '低优先级'
  return '常规'
})

const priorityTone = computed(() => {
  const p = props.recommendation?.priority
  if (p === 'high') return 'high'
  if (p === 'low') return 'low'
  return 'medium'
})

const isLocked = computed(() => Boolean(props.recommendation?.is_locked))

const cognitiveSnapshot = computed(() => props.recommendation?.cognitive_snapshot ?? null)

const confidence = computed(() => {
  const c = cognitiveSnapshot.value?.confidence
  const n = Number(c)
  return Number.isFinite(n) ? n : null
})

const isAbstained = computed(() => Boolean(cognitiveSnapshot.value?.abstain))

const isLowConfidence = computed(() => {
  if (isAbstained.value) return true
  return confidence.value !== null && confidence.value < LOW_CONFIDENCE_THRESHOLD
})

const readableReasonCodes = computed(() => {
  const codes = props.recommendation?.reason_codes
  if (!Array.isArray(codes) || codes.length === 0) return []
  return codes.map((code) => humanizeReasonCode(code))
})

const evidenceRefs = computed(() => {
  const refs = props.recommendation?.evidence_refs
  if (!Array.isArray(refs) || refs.length === 0) return []
  return refs
})

function humanizeReasonCode(code) {
  if (!code || typeof code !== 'string') return String(code ?? '')
  const map = {
    low_quiz_accuracy: '练习正确率偏低',
    high_hint_dependency: '对提示依赖较高',
    low_evidence_confidence: '证据置信度不足',
    high_confusion_risk: '存在困惑信号',
    low_inquiry_depth: '主动探究较少',
    high_explanation_need: '需要更多讲解',
    stale_evidence: '学习证据已陈旧',
    insufficient_evidence: '可用证据不足',
    weak_on_prerequisite: '先修知识掌握不牢',
    ready_for_advanced: '已具备进阶条件',
  }
  return map[code] || code.replace(/_/g, ' ')
}

function handleConsume() {
  if (props.consuming || props.consumed || isLocked.value) return
  emit('consume', props.recommendation)
}
</script>

<template>
  <article
    class="sfx-rec-card"
    :class="[
      `is-priority-${priorityTone}`,
      {
        'is-locked': isLocked,
        'is-consumed': consumed,
        'is-low-confidence': isLowConfidence,
      },
    ]"
  >
    <header class="sfx-rec-card__header">
      <component :is="typeIcon" :size="16" class="sfx-rec-card__type-icon" />
      <span class="sfx-rec-card__priority" :class="`tone-${priorityTone}`">
        {{ priorityLabel }}
      </span>
      <span
        v-if="recommendation.policy_version"
        class="sfx-rec-card__policy"
      >
        策略 v{{ recommendation.policy_version }}
      </span>
      <span v-if="isLocked" class="sfx-rec-card__lock">
        <Lock :size="13" /> 教师已锁定
      </span>
      <span v-if="consumed" class="sfx-rec-card__consumed">
        <Check :size="13" /> 已采用
      </span>
    </header>

    <h3 class="sfx-rec-card__title">
      {{ recommendation.title || '学习推荐' }}
    </h3>

    <p v-if="recommendation.description" class="sfx-rec-card__desc">
      {{ recommendation.description }}
    </p>

    <!-- 推荐理由（可读化 reason_codes） -->
    <section
      v-if="readableReasonCodes.length"
      class="sfx-rec-card__rationale"
      aria-label="推荐理由"
    >
      <h4 class="sfx-rec-card__rationale-title">推荐理由</h4>
      <ul class="sfx-rec-card__reason-list">
        <li v-for="(code, i) in readableReasonCodes" :key="i">{{ code }}</li>
      </ul>
    </section>

    <!-- 置信度 / 数据不足语义 -->
    <section
      v-if="cognitiveSnapshot"
      class="sfx-rec-card__confidence-row"
      :class="{ 'is-abstained': isAbstained, 'is-low': isLowConfidence && !isAbstained }"
    >
      <TriangleAlert v-if="isAbstained" :size="14" />
      <TriangleAlert v-else-if="isLowConfidence" :size="14" />
      <Check v-else :size="14" />
      <span v-if="isAbstained" class="sfx-rec-card__confidence-text">
        需要更多证据：当前可用证据不足以做出可靠判断，建议核验后再决策。
      </span>
      <span v-else-if="isLowConfidence" class="sfx-rec-card__confidence-text">
        建议核验：置信度较低（约 {{ Math.round((confidence ?? 0) * 100) }}%），结论可能不稳定。
      </span>
      <span v-else class="sfx-rec-card__confidence-text">
        置信度 {{ Math.round((confidence ?? 0) * 100) }}%
      </span>
    </section>

    <!-- 证据引用（可折叠展示，此处仅展示数量与 ID） -->
    <section v-if="evidenceRefs.length" class="sfx-rec-card__evidence">
      <h4 class="sfx-rec-card__evidence-title">
        关联证据（{{ evidenceRefs.length }} 条）
      </h4>
      <ul class="sfx-rec-card__evidence-list">
        <li v-for="(ref, i) in evidenceRefs" :key="i" class="sfx-rec-card__evidence-item">
          <code>{{ typeof ref === 'string' ? ref : (ref.id || ref.evidence_id || JSON.stringify(ref)) }}</code>
        </li>
      </ul>
    </section>

    <!-- 操作区 -->
    <footer class="sfx-rec-card__footer">
      <button
        type="button"
        class="sfx-rec-card__consume-btn"
        :disabled="consuming || consumed || isLocked"
        @click="handleConsume"
      >
        <template v-if="consumed">已采用</template>
        <template v-else-if="consuming">处理中…</template>
        <template v-else-if="isLocked">教师已锁定</template>
        <template v-else>
          采纳并继续
          <ChevronRight :size="14" />
        </template>
      </button>
    </footer>
  </article>
</template>

<style scoped>
.sfx-rec-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 10px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.sfx-rec-card:hover:not(.is-locked):not(.is-consumed) {
  border-color: var(--accent-primary, #4f8cf7);
  box-shadow: 0 1px 4px rgba(79, 140, 247, 0.12);
}

.sfx-rec-card.is-priority-high {
  border-left: 3px solid var(--red-700, #c62828);
}

.sfx-rec-card.is-priority-medium {
  border-left: 3px solid var(--accent-primary, #4f8cf7);
}

.sfx-rec-card.is-priority-low {
  border-left: 3px solid var(--text-muted, #9ca3af);
}

.sfx-rec-card.is-locked {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-rec-card.is-consumed {
  opacity: 0.7;
}

.sfx-rec-card__header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sfx-rec-card__type-icon {
  color: var(--accent-primary, #4f8cf7);
}

.sfx-rec-card__priority {
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.sfx-rec-card__priority.tone-high {
  background: #fee2e2;
  color: #b91c1c;
}

.sfx-rec-card__priority.tone-medium {
  background: #dbeafe;
  color: #1d4ed8;
}

.sfx-rec-card__priority.tone-low {
  background: #f3f4f6;
  color: #6b7280;
}

.sfx-rec-card__policy {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--text-muted, #9ca3af);
}

.sfx-rec-card__lock {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  color: #b45309;
  background: #fef3c7;
  padding: 2px 8px;
  border-radius: 999px;
}

.sfx-rec-card__consumed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  color: #047857;
  background: #d1fae5;
  padding: 2px 8px;
  border-radius: 999px;
}

.sfx-rec-card__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-rec-card__desc {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--text-secondary, #4b5563);
}

.sfx-rec-card__rationale {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: var(--surface-cool, #f5f7fa);
  border-radius: 6px;
}

.sfx-rec-card__rationale-title {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sfx-rec-card__reason-list {
  margin: 0;
  padding-left: 18px;
  font-size: 0.82rem;
  line-height: 1.5;
  color: var(--text-secondary, #4b5563);
}

.sfx-rec-card__confidence-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 0.8rem;
  background: #ecfdf5;
  color: #047857;
}

.sfx-rec-card__confidence-row.is-low {
  background: #fffbeb;
  color: #b45309;
}

.sfx-rec-card__confidence-row.is-abstained {
  background: #fff7ed;
  color: #c2410c;
}

.sfx-rec-card__confidence-text {
  line-height: 1.4;
}

.sfx-rec-card__evidence {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sfx-rec-card__evidence-title {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted, #6b7280);
}

.sfx-rec-card__evidence-list {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.sfx-rec-card__evidence-item code {
  font-size: 0.7rem;
  padding: 2px 6px;
  background: var(--surface-cool, #f0f0f0);
  border-radius: 4px;
  color: var(--text-secondary, #4b5563);
}

.sfx-rec-card__footer {
  display: flex;
  justify-content: flex-end;
}

.sfx-rec-card__consume-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}

.sfx-rec-card__consume-btn:hover:not(:disabled) {
  background: var(--accent-primary-hover, #3b7be0);
}

.sfx-rec-card__consume-btn:disabled {
  background: var(--surface-muted, #e0e0e0);
  color: var(--text-muted, #9ca3af);
  cursor: not-allowed;
}
</style>
