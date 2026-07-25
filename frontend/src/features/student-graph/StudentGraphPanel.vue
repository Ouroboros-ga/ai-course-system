<script setup>
/**
 * 学生只读知识图谱面板（批次3）。
 *
 * 数据契约：
 * - 调用 getCourseSnapshot(courseId) 拉取已发布快照（学生视角，后端只返 published）；
 * - 当前知识点变化时调用 getNodePrerequisites 获取一跳先修/后继；
 * - 推荐理由来自上层（policy_version / reason_codes / 置信度 / 数据不足语义），
 *   通过 props 传入；本组件不直接调用认知 API，保持职责单一；
 * - 无已发布快照时显示「暂无已发布图谱快照」，不伪造节点；
 * - 低置信度显示「建议核验/需要更多证据」，不武断判弱。
 *
 * 样式参考 evidence-viewer，使用 sfx- 前缀的 BEM 风格。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  CornerDownRight,
  GitFork,
  LoaderCircle,
  TriangleAlert,
} from 'lucide-vue-next'
import {
  getCourseSnapshot,
  getNodePrerequisites,
} from '@/api/graph.js'

const props = defineProps({
  /** 课程 ID，所有 API 调用必须携带 */
  courseId: { type: [Number, String], required: true },
  /** 当前知识点节点 ID（可选；缺失时仅展示快照概览） */
  nodeId: { type: [Number, String], default: null },
  /** 当前知识点标题（用于面板头部展示） */
  nodeTitle: { type: String, default: '' },
  /** 推荐理由上下文（来自认知层，可选） */
  recommendationContext: {
    type: Object,
    default: null,
  },
  /**
   * recommendationContext 形如：
   * {
   *   policy_version: 'v1.2',
   *   reason_codes: ['low_quiz_accuracy', 'high_hint_dependency'],
   *   confidence: 0.42,                  // 0..1，< 阈值视为低置信度
   *   abstain: false,                    // true 表示数据完全不足
   *   abstain_reason: 'evidence_count<3' // 可选
   * }
   */
})

const emit = defineEmits([
  /** 跳转到先修/后继节点，payload = node 对象 */
  'jump-node',
  /** 返回锚点（回到调用方记录的原学习位置） */
  'return-anchor',
])

const status = ref('idle') // idle | loading | ready | empty | error
const errorMessage = ref('')
const snapshot = ref(null)
const neighbors = ref({ incoming: [], outgoing: [] })
const neighborsStatus = ref('idle')
const neighborsError = ref('')

const LOW_CONFIDENCE_THRESHOLD = 0.5

const snapshotMeta = computed(() => {
  if (!snapshot.value) return null
  return {
    snapshotId: snapshot.value.snapshot_id ?? snapshot.value.id ?? null,
    policyVersion: snapshot.value.policy_version ?? '',
    publishedAt: snapshot.value.published_at ?? snapshot.value.created_at ?? '',
    nodeCount: Array.isArray(snapshot.value.nodes) ? snapshot.value.nodes.length : 0,
    edgeCount: Array.isArray(snapshot.value.edges) ? snapshot.value.edges.length : 0,
  }
})

const currentNodeInSnapshot = computed(() => {
  if (!snapshot.value?.nodes || props.nodeId == null) return null
  return (
    snapshot.value.nodes.find((n) => n.id === props.nodeId) ??
    snapshot.value.nodes.find((n) => String(n.id) === String(props.nodeId)) ??
    null
  )
})

const isLowConfidence = computed(() => {
  const ctx = props.recommendationContext
  if (!ctx) return false
  if (ctx.abstain) return true
  const c = Number(ctx.confidence)
  return Number.isFinite(c) && c < LOW_CONFIDENCE_THRESHOLD
})

const isAbstained = computed(() => Boolean(props.recommendationContext?.abstain))

const readableReasonCodes = computed(() => {
  const codes = props.recommendationContext?.reason_codes
  if (!Array.isArray(codes) || codes.length === 0) return []
  return codes.map((code) => humanizeReasonCode(code))
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
  }
  return map[code] || code.replace(/_/g, ' ')
}

function mapLoadError(err) {
  const msg = String(err?.message || '')
  if (/403|401|forbidden|权限|拒绝/.test(msg)) return 'forbidden'
  if (/503|unavailable|未配置|not configured/.test(msg)) return 'unavailable'
  return 'error'
}

async function loadSnapshot() {
  if (props.courseId == null || props.courseId === '') {
    status.value = 'empty'
    return
  }
  status.value = 'loading'
  errorMessage.value = ''
  try {
    const res = await getCourseSnapshot(props.courseId)
    // 后端可能返回 null（无已发布快照）—— 显式空态，不伪造
    if (!res || (Array.isArray(res.nodes) && res.nodes.length === 0 && !res.snapshot_id && !res.id)) {
      snapshot.value = null
      status.value = 'empty'
      return
    }
    snapshot.value = res
    status.value = 'ready'
  } catch (err) {
    status.value = mapLoadError(err)
    errorMessage.value = err?.message || '快照加载失败'
  }
}

async function loadNeighbors() {
  if (props.nodeId == null || !snapshot.value) {
    neighbors.value = { incoming: [], outgoing: [] }
    return
  }
  neighborsStatus.value = 'loading'
  neighborsError.value = ''
  // 并行拉取先修与后继，互不阻塞
  const [incomingRes, outgoingRes] = await Promise.allSettled([
    getNodePrerequisites(props.courseId, props.nodeId, 'incoming'),
    getNodePrerequisites(props.courseId, props.nodeId, 'outgoing'),
  ])
  const incoming =
    incomingRes.status === 'fulfilled'
      ? (incomingRes.value?.items ?? incomingRes.value?.nodes ?? [])
      : []
  const outgoing =
    outgoingRes.status === 'fulfilled'
      ? (outgoingRes.value?.items ?? outgoingRes.value?.nodes ?? [])
      : []
  neighbors.value = { incoming, outgoing }
  if (incomingRes.status === 'rejected' && outgoingRes.status === 'rejected') {
    neighborsStatus.value = 'error'
    neighborsError.value =
      incomingRes.reason?.message || '相邻节点加载失败'
  } else {
    neighborsStatus.value = 'ready'
  }
}

function handleJump(node) {
  if (!node) return
  emit('jump-node', node)
}

function handleReturn() {
  emit('return-anchor')
}

watch(
  () => props.courseId,
  () => loadSnapshot(),
)

watch(
  () => props.nodeId,
  () => loadNeighbors(),
)

onMounted(async () => {
  await loadSnapshot()
  if (props.nodeId != null) {
    loadNeighbors()
  }
})
</script>

<template>
  <section class="sfx-student-graph" aria-label="知识图谱">
    <header class="sfx-student-graph__header">
      <div class="sfx-student-graph__heading">
        <GitFork :size="18" class="sfx-student-graph__icon" />
        <div class="sfx-student-graph__title-block">
          <h2 class="sfx-student-graph__title">知识图谱</h2>
          <p class="sfx-student-graph__subtitle">
            <span v-if="nodeTitle">{{ nodeTitle }}</span>
            <span v-else>当前课程已发布快照</span>
            <span
              v-if="snapshotMeta?.policyVersion"
              class="sfx-student-graph__policy"
            >
              · 策略 v{{ snapshotMeta.policyVersion }}
            </span>
          </p>
        </div>
      </div>
      <button
        type="button"
        class="sfx-student-graph__return-btn"
        @click="handleReturn"
      >
        <ArrowLeft :size="15" /> 返回锚点
      </button>
    </header>

    <!-- 加载中 -->
    <div v-if="status === 'loading'" class="sfx-student-graph__state" role="status">
      <LoaderCircle :size="22" class="sfx-student-graph__spinner" />
      <p class="sfx-student-graph__state-text">正在加载已发布图谱快照…</p>
    </div>

    <!-- 错误 / 服务不可用 / 权限 -->
    <div
      v-else-if="status === 'error' || status === 'forbidden' || status === 'unavailable'"
      class="sfx-student-graph__state sfx-student-graph__state--error"
      role="alert"
    >
      <TriangleAlert :size="22" />
      <p class="sfx-student-graph__state-text">
        {{ errorMessage || '图谱快照暂时无法读取' }}
      </p>
      <button
        type="button"
        class="sfx-student-graph__retry"
        @click="loadSnapshot"
      >
        重试
      </button>
    </div>

    <!-- 空状态：无已发布快照 -->
    <div v-else-if="status === 'empty'" class="sfx-student-graph__state sfx-student-graph__state--empty">
      <GitFork :size="28" :stroke-width="1.6" />
      <strong>暂无已发布图谱快照</strong>
      <p class="sfx-student-graph__state-text">
        教师尚未发布当前课程的知识图谱。系统不会展示未发布或未核验的节点关系。
      </p>
    </div>

    <!-- 就绪 -->
    <template v-else-if="status === 'ready'">
      <!-- 推荐理由（可选） -->
      <aside
        v-if="recommendationContext"
        class="sfx-student-graph__rationale"
        :class="{
          'is-low-confidence': isLowConfidence,
          'is-abstained': isAbstained,
        }"
      >
        <div class="sfx-student-graph__rationale-head">
          <CornerDownRight :size="15" />
          <span class="sfx-student-graph__rationale-title">推荐理由</span>
          <span
            v-if="recommendationContext.confidence != null && !isAbstained"
            class="sfx-student-graph__confidence"
          >
            置信度 {{ Math.round((recommendationContext.confidence ?? 0) * 100) }}%
          </span>
        </div>
        <ul v-if="readableReasonCodes.length" class="sfx-student-graph__reason-list">
          <li v-for="(code, i) in readableReasonCodes" :key="i">{{ code }}</li>
        </ul>
        <p v-if="isAbstained" class="sfx-student-graph__rationale-note">
          需要更多证据：当前可用学习证据不足以做出可靠判断，建议核验后再决策。
        </p>
        <p v-else-if="isLowConfidence" class="sfx-student-graph__rationale-note">
          建议核验：当前置信度较低，结论可能不稳定，可结合原文或练习进一步确认。
        </p>
        <p
          v-if="recommendationContext.policy_version"
          class="sfx-student-graph__rationale-meta"
        >
          策略版本 v{{ recommendationContext.policy_version }}
        </p>
      </aside>

      <!-- 快照概览 -->
      <div class="sfx-student-graph__overview">
        <span v-if="snapshotMeta?.nodeCount != null" class="sfx-student-graph__metric">
          <strong>{{ snapshotMeta.nodeCount }}</strong> 节点
        </span>
        <span v-if="snapshotMeta?.edgeCount != null" class="sfx-student-graph__metric">
          <strong>{{ snapshotMeta.edgeCount }}</strong> 关系
        </span>
        <span
          v-if="snapshotMeta?.publishedAt"
          class="sfx-student-graph__metric sfx-student-graph__metric--muted"
        >
          发布于 {{ snapshotMeta.publishedAt }}
        </span>
      </div>

      <!-- 当前知识点 -->
      <article v-if="currentNodeInSnapshot" class="sfx-student-graph__current">
        <header class="sfx-student-graph__section-head">
          <span>当前知识点</span>
        </header>
        <h3 class="sfx-student-graph__current-title">
          {{ currentNodeInSnapshot.title || currentNodeInSnapshot.name || `节点 #${currentNodeInSnapshot.id}` }}
        </h3>
        <p
          v-if="currentNodeInSnapshot.summary || currentNodeInSnapshot.description"
          class="sfx-student-graph__current-summary"
        >
          {{ currentNodeInSnapshot.summary || currentNodeInSnapshot.description }}
        </p>
      </article>

      <!-- 一跳先修 / 后继 -->
      <div class="sfx-student-graph__neighbors">
        <div class="sfx-student-graph__neighbor-col">
          <header class="sfx-student-graph__section-head">
            <span>先修节点</span>
            <small class="sfx-student-graph__section-count">
              {{ neighbors.incoming.length }}
            </small>
          </header>
          <ul v-if="neighbors.incoming.length" class="sfx-student-graph__neighbor-list">
            <li
              v-for="node in neighbors.incoming"
              :key="node.id"
              class="sfx-student-graph__neighbor-item"
            >
              <button
                type="button"
                class="sfx-student-graph__neighbor-btn"
                @click="handleJump(node)"
              >
                <span class="sfx-student-graph__neighbor-title">
                  {{ node.title || node.name || `节点 #${node.id}` }}
                </span>
                <span v-if="node.summary" class="sfx-student-graph__neighbor-summary">
                  {{ node.summary }}
                </span>
              </button>
            </li>
          </ul>
          <p
            v-else-if="neighborsStatus === 'loading'"
            class="sfx-student-graph__neighbor-empty"
          >
            加载中…
          </p>
          <p
            v-else-if="neighborsStatus === 'error'"
            class="sfx-student-graph__neighbor-empty sfx-student-graph__neighbor-empty--error"
          >
            {{ neighborsError || '相邻节点加载失败' }}
          </p>
          <p v-else class="sfx-student-graph__neighbor-empty">无先修节点</p>
        </div>

        <div class="sfx-student-graph__neighbor-col">
          <header class="sfx-student-graph__section-head">
            <span>后继节点</span>
            <small class="sfx-student-graph__section-count">
              {{ neighbors.outgoing.length }}
            </small>
          </header>
          <ul v-if="neighbors.outgoing.length" class="sfx-student-graph__neighbor-list">
            <li
              v-for="node in neighbors.outgoing"
              :key="node.id"
              class="sfx-student-graph__neighbor-item"
            >
              <button
                type="button"
                class="sfx-student-graph__neighbor-btn"
                @click="handleJump(node)"
              >
                <span class="sfx-student-graph__neighbor-title">
                  {{ node.title || node.name || `节点 #${node.id}` }}
                </span>
                <span v-if="node.summary" class="sfx-student-graph__neighbor-summary">
                  {{ node.summary }}
                </span>
              </button>
            </li>
          </ul>
          <p
            v-else-if="neighborsStatus === 'loading'"
            class="sfx-student-graph__neighbor-empty"
          >
            加载中…
          </p>
          <p
            v-else-if="neighborsStatus === 'error'"
            class="sfx-student-graph__neighbor-empty sfx-student-graph__neighbor-empty--error"
          >
            {{ neighborsError || '相邻节点加载失败' }}
          </p>
          <p v-else class="sfx-student-graph__neighbor-empty">无后继节点</p>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sfx-student-graph {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  padding: 16px;
  background: var(--surface-canvas, #fafbfc);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: var(--radius-lg, 10px);
  overflow-y: auto;
}

.sfx-student-graph__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3, 12px);
}

.sfx-student-graph__heading {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2, 8px);
}

.sfx-student-graph__icon {
  color: var(--accent-primary, #4f8cf7);
  margin-top: 2px;
}

.sfx-student-graph__title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-student-graph__title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-student-graph__subtitle {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-student-graph__policy {
  color: var(--text-muted, #9ca3af);
}

.sfx-student-graph__return-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1, 4px);
  padding: 6px 12px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-panel, #fff);
  color: var(--text-secondary, #374151);
  font-size: 0.85rem;
  cursor: pointer;
  flex-shrink: 0;
}

.sfx-student-graph__return-btn:hover {
  background: var(--surface-cool, #f5f5f5);
  color: var(--ink-700, #1f2937);
}

.sfx-student-graph__state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: 32px 16px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-student-graph__state--error {
  color: var(--red-700, #c62828);
}

.sfx-student-graph__state--empty {
  color: var(--text-muted, #9ca3af);
}

.sfx-student-graph__state-text {
  margin: 0;
  font-size: 0.85rem;
}

.sfx-student-graph__spinner {
  animation: sfx-student-graph-spin 0.8s linear infinite;
  color: var(--accent-primary, #4f8cf7);
}

@keyframes sfx-student-graph-spin {
  to { transform: rotate(360deg); }
}

.sfx-student-graph__retry {
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--ink-700, #1f2937);
}

.sfx-student-graph__retry:hover {
  background: var(--surface-cool, #f5f5f5);
}

/* 推荐理由 */
.sfx-student-graph__rationale {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: var(--surface-cool, #f5f7fa);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
}

.sfx-student-graph__rationale.is-low-confidence {
  background: #fffbeb;
  border-color: #fde68a;
}

.sfx-student-graph__rationale.is-abstained {
  background: #fff7ed;
  border-color: #fed7aa;
}

.sfx-student-graph__rationale-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sfx-student-graph__rationale-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-student-graph__confidence {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-student-graph__reason-list {
  margin: 0;
  padding-left: 18px;
  font-size: 0.82rem;
  line-height: 1.5;
  color: var(--text-secondary, #374151);
}

.sfx-student-graph__rationale-note {
  margin: 0;
  font-size: 0.8rem;
  color: var(--amber-700, #b45309);
}

.sfx-student-graph__rationale.is-abstained .sfx-student-graph__rationale-note {
  color: #c2410c;
}

.sfx-student-graph__rationale-meta {
  margin: 0;
  font-size: 0.72rem;
  color: var(--text-muted, #9ca3af);
}

/* 快照概览 */
.sfx-student-graph__overview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3, 12px);
  padding: 8px 12px;
  background: var(--surface-panel, #fff);
  border-radius: 6px;
  font-size: 0.8rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-student-graph__metric strong {
  color: var(--text-primary, #1f2937);
  font-weight: 600;
}

.sfx-student-graph__metric--muted {
  color: var(--text-muted, #9ca3af);
}

/* 当前知识点 */
.sfx-student-graph__current {
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 8px;
}

.sfx-student-graph__section-head {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  margin-bottom: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sfx-student-graph__section-count {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--surface-cool, #f0f0f0);
  color: var(--text-secondary, #6b7280);
  font-weight: 500;
}

.sfx-student-graph__current-title {
  margin: 0 0 4px 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-student-graph__current-summary {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-secondary, #4b5563);
}

/* 相邻节点 */
.sfx-student-graph__neighbors {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3, 12px);
}

@media (max-width: 720px) {
  .sfx-student-graph__neighbors {
    grid-template-columns: 1fr;
  }
}

.sfx-student-graph__neighbor-col {
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 8px;
}

.sfx-student-graph__neighbor-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sfx-student-graph__neighbor-btn {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-canvas, #fafbfc);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.sfx-student-graph__neighbor-btn:hover {
  border-color: var(--accent-primary, #4f8cf7);
  background: var(--accent-bg, #e8f0fe);
}

.sfx-student-graph__neighbor-title {
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--text-primary, #1f2937);
}

.sfx-student-graph__neighbor-summary {
  font-size: 0.78rem;
  color: var(--text-secondary, #6b7280);
  line-height: 1.4;
}

.sfx-student-graph__neighbor-empty {
  margin: 0;
  padding: 8px 10px;
  font-size: 0.82rem;
  color: var(--text-muted, #9ca3af);
  text-align: center;
}

.sfx-student-graph__neighbor-empty--error {
  color: var(--red-700, #c62828);
}
</style>
