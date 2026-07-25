<script setup>
/**
 * 认知仪表盘（批次3）。
 *
 * 接收 courseId 与 studentId，调用 getCognitiveState 拉取六维认知状态：
 * - observed_performance_score：观测表现分（练习/测验）
 * - evidence_confidence：证据置信度
 * - confusion_risk：困惑风险
 * - inquiry_depth：主动探究深度
 * - hint_dependency：提示依赖度
 * - explanation_need：讲解需求度
 *
 * 数据不足维度（confidence < 阈值 或 abstain=true）显示「需要更多证据」，
 * 不武断判弱。同时展示 mastery_level 与 policy_version 以便追溯。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  Activity,
  Gauge,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
} from 'lucide-vue-next'
import { getCognitiveState } from '@/api/cognitive.js'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  studentId: { type: [Number, String], required: true },
  /** 是否展示刷新按钮 */
  refreshable: { type: Boolean, default: true },
})

const emit = defineEmits(['loaded', 'error'])

const status = ref('idle') // idle | loading | ready | empty | error
const errorMessage = ref('')
const state = ref(null)

const LOW_CONFIDENCE_THRESHOLD = 0.5

// 六维定义：key / 标签 / 描述 / 是否「越高越好」
const DIMENSIONS = Object.freeze([
  {
    key: 'observed_performance_score',
    label: '观测表现',
    desc: '基于练习与测验的客观表现',
    higherIsBetter: true,
  },
  {
    key: 'evidence_confidence',
    label: '证据置信度',
    desc: '可用学习证据对结论的支持度',
    higherIsBetter: true,
  },
  {
    key: 'confusion_risk',
    label: '困惑风险',
    desc: '错误聚集/反复出错的信号',
    higherIsBetter: false,
  },
  {
    key: 'inquiry_depth',
    label: '探究深度',
    desc: '主动提问与延伸思考程度',
    higherIsBetter: true,
  },
  {
    key: 'hint_dependency',
    label: '提示依赖',
    desc: '依赖提示而非独立作答的程度',
    higherIsBetter: false,
  },
  {
    key: 'explanation_need',
    label: '讲解需求',
    desc: '反复请求讲解的程度',
    higherIsBetter: false,
  },
])

const dimensions = computed(() => {
  if (!state.value) return []
  const dims = state.value.dimensions ?? state.value
  return DIMENSIONS.map((def) => {
    const raw = dims?.[def.key] ?? null
    // P1-1: 保留 null 语义——后端以 null 表示「数据不足/unknown」，
    // 禁止 Number(null)=0 与默认 confidence=1 把「未知」误报成「0 分、100% 置信」。
    const rawValue = raw?.value ?? raw
    const value =
      rawValue == null || rawValue === '' ? null : Number(rawValue)
    const rawConfidence = raw?.confidence ?? raw?.confidence_score
    const confidence =
      rawConfidence == null || rawConfidence === ''
        ? null
        : Number(rawConfidence)
    const abstain = Boolean(raw?.abstain)
    // 数据不足判定：abstain / value 缺失 / confidence 缺失 / confidence 低于阈值
    // 任一成立即视为「需要更多证据」，绝不武断判弱。
    const insufficient =
      abstain ||
      value == null ||
      !Number.isFinite(value) ||
      confidence == null ||
      !Number.isFinite(confidence) ||
      confidence < LOW_CONFIDENCE_THRESHOLD
    return {
      key: def.key,
      label: def.label,
      desc: def.desc,
      higherIsBetter: def.higherIsBetter,
      value: Number.isFinite(value) ? value : null,
      confidence: Number.isFinite(confidence) ? confidence : null,
      abstain,
      insufficient,
    }
  })
})

const masteryLevel = computed(() => state.value?.mastery_level ?? null)
const policyVersion = computed(() => state.value?.policy_version ?? '')
const computedAt = computed(
  () => state.value?.computed_at ?? state.value?.updated_at ?? '',
)

function mapLoadError(err) {
  const msg = String(err?.message || '')
  if (/403|401|forbidden|权限|拒绝/.test(msg)) return 'forbidden'
  if (/503|unavailable|未配置|not configured/.test(msg)) return 'unavailable'
  if (/404|not found/.test(msg)) return 'empty'
  return 'error'
}

async function load() {
  if (props.courseId == null || props.studentId == null) {
    status.value = 'empty'
    return
  }
  status.value = 'loading'
  errorMessage.value = ''
  try {
    const res = await getCognitiveState(props.courseId, props.studentId)
    if (!res) {
      state.value = null
      status.value = 'empty'
      emit('loaded', null)
      return
    }
    state.value = res
    status.value = 'ready'
    emit('loaded', res)
  } catch (err) {
    status.value = mapLoadError(err)
    errorMessage.value = err?.message || '认知状态加载失败'
    emit('error', err)
  }
}

function formatPercent(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  // 值约定为 0..1，统一展示为百分比
  return Math.round(v * 100) + '%'
}

function valueTone(dim) {
  if (dim.insufficient) return 'insufficient'
  if (dim.value == null) return 'unknown'
  if (dim.higherIsBetter) {
    if (dim.value >= 0.7) return 'good'
    if (dim.value >= 0.4) return 'medium'
    return 'weak'
  }
  // 越低越好
  if (dim.value <= 0.3) return 'good'
  if (dim.value <= 0.6) return 'medium'
  return 'weak'
}

watch(
  () => [props.courseId, props.studentId],
  () => load(),
)

onMounted(load)
</script>

<template>
  <section class="sfx-cog" aria-label="认知仪表盘">
    <header class="sfx-cog__header">
      <div class="sfx-cog__heading">
        <Gauge :size="18" class="sfx-cog__icon" />
        <div class="sfx-cog__title-block">
          <h2 class="sfx-cog__title">认知仪表盘</h2>
          <p class="sfx-cog__subtitle">
            <span v-if="masteryLevel">掌握度：{{ masteryLevel }}</span>
            <span v-if="policyVersion"> · 策略 v{{ policyVersion }}</span>
            <span v-if="computedAt"> · 更新于 {{ computedAt }}</span>
          </p>
        </div>
      </div>
      <button
        v-if="refreshable"
        type="button"
        class="sfx-cog__refresh"
        :disabled="status === 'loading'"
        @click="load"
      >
        <RefreshCw :size="14" :class="{ 'is-spinning': status === 'loading' }" />
        刷新
      </button>
    </header>

    <!-- 加载中 -->
    <div v-if="status === 'loading'" class="sfx-cog__state" role="status">
      <LoaderCircle :size="20" class="sfx-cog__spinner" />
      <p class="sfx-cog__state-text">正在计算认知状态…</p>
    </div>

    <!-- 错误 / 权限 / 不可用 -->
    <div
      v-else-if="status === 'error' || status === 'forbidden' || status === 'unavailable'"
      class="sfx-cog__state sfx-cog__state--error"
      role="alert"
    >
      <TriangleAlert :size="20" />
      <p class="sfx-cog__state-text">
        {{ errorMessage || '认知状态暂时不可读' }}
      </p>
      <button type="button" class="sfx-cog__retry" @click="load">重试</button>
    </div>

    <!-- 空状态：尚无计算结果 -->
    <div v-else-if="status === 'empty'" class="sfx-cog__state sfx-cog__state--empty">
      <Activity :size="26" :stroke-width="1.6" />
      <strong>暂无认知状态数据</strong>
      <p class="sfx-cog__state-text">
        后端尚未为该学生计算认知状态。完成练习或提问后，系统会基于真实证据生成。
      </p>
    </div>

    <!-- 就绪：六维展示 -->
    <template v-else-if="status === 'ready' && dimensions.length">
      <ul class="sfx-cog__grid">
        <li
          v-for="dim in dimensions"
          :key="dim.key"
          class="sfx-cog__dim"
          :class="`tone-${valueTone(dim)}`"
        >
          <header class="sfx-cog__dim-head">
            <span class="sfx-cog__dim-label">{{ dim.label }}</span>
            <span
              v-if="dim.insufficient"
              class="sfx-cog__dim-tag sfx-cog__dim-tag--insufficient"
            >
              需要更多证据
            </span>
          </header>
          <p v-if="dim.insufficient" class="sfx-cog__dim-value sfx-cog__dim-value--insufficient">
            —
          </p>
          <p v-else-if="dim.value == null" class="sfx-cog__dim-value sfx-cog__dim-value--unknown">
            —
          </p>
          <p v-else class="sfx-cog__dim-value">{{ formatPercent(dim.value) }}</p>
          <p class="sfx-cog__dim-desc">{{ dim.desc }}</p>
          <p v-if="dim.confidence != null && !dim.insufficient" class="sfx-cog__dim-confidence">
            证据置信度 {{ formatPercent(dim.confidence) }}
          </p>
        </li>
      </ul>

      <footer v-if="policyVersion" class="sfx-cog__footer">
        策略版本 v{{ policyVersion }} · 数据不足维度已显式标注，不进行武断判弱
      </footer>
    </template>
  </section>
</template>

<style scoped>
.sfx-cog {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  padding: 16px;
  background: var(--surface-canvas, #fafbfc);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: var(--radius-lg, 10px);
}

.sfx-cog__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3, 12px);
}

.sfx-cog__heading {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2, 8px);
}

.sfx-cog__icon {
  color: var(--accent-primary, #4f8cf7);
  margin-top: 2px;
}

.sfx-cog__title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-cog__title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-cog__subtitle {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-cog__refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-panel, #fff);
  color: var(--text-secondary, #374151);
  font-size: 0.82rem;
  cursor: pointer;
  flex-shrink: 0;
}

.sfx-cog__refresh:hover:not(:disabled) {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-cog__refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.is-spinning {
  animation: sfx-cog-spin 0.8s linear infinite;
}

@keyframes sfx-cog-spin {
  to { transform: rotate(360deg); }
}

.sfx-cog__state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: 32px 16px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-cog__state--error { color: var(--red-700, #c62828); }
.sfx-cog__state--empty { color: var(--text-muted, #9ca3af); }

.sfx-cog__state-text {
  margin: 0;
  font-size: 0.85rem;
}

.sfx-cog__spinner {
  color: var(--accent-primary, #4f8cf7);
}

.sfx-cog__retry {
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--ink-700, #1f2937);
}

.sfx-cog__retry:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-cog__grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.sfx-cog__dim {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 8px;
  border-left: 3px solid var(--text-muted, #9ca3af);
}

.sfx-cog__dim.tone-good { border-left-color: #10b981; }
.sfx-cog__dim.tone-medium { border-left-color: var(--accent-primary, #4f8cf7); }
.sfx-cog__dim.tone-weak { border-left-color: #f59e0b; }
.sfx-cog__dim.tone-insufficient { border-left-color: #f97316; }
.sfx-cog__dim.tone-unknown { border-left-color: var(--text-muted, #9ca3af); }

.sfx-cog__dim-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.sfx-cog__dim-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-cog__dim-tag {
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-cool, #f0f0f0);
  color: var(--text-muted, #6b7280);
}

.sfx-cog__dim-tag--insufficient {
  background: #fff7ed;
  color: #c2410c;
}

.sfx-cog__dim-value {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary, #1f2937);
  font-variant-numeric: tabular-nums;
}

.sfx-cog__dim-value--insufficient,
.sfx-cog__dim-value--unknown {
  color: var(--text-muted, #9ca3af);
  font-weight: 500;
}

.sfx-cog__dim-desc {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--text-secondary, #6b7280);
}

.sfx-cog__dim-confidence {
  margin: 0;
  font-size: 0.7rem;
  color: var(--text-muted, #9ca3af);
}

.sfx-cog__footer {
  padding-top: 6px;
  border-top: 1px solid var(--border-subtle, #f0f0f0);
  font-size: 0.72rem;
  color: var(--text-muted, #9ca3af);
  text-align: center;
}
</style>
