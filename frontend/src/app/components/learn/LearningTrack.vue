<script setup>
import { nextTick, ref, watch } from 'vue'
import { Check, ChevronLeft, ChevronRight, CircleAlert, Clock3, HelpCircle, Info, KeyRound, TriangleAlert } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import { getCognitionDisplayState, getLearningDisplayState, getNodeDisplayState, summarizeLearningItems } from '@/features/student-learning/learningStatus.js'

/**
 * 学习轨道（page-design §6.9）：章节内知识点列表、当前节点、完成状态。
 * 分支状态下自动收缩为 56px 图标轨（§12.5）；与建设页 Local Rail 外观
 * 骨架一致但数据语义不同。
 * 状态词典：未学习 / 学习中 / 已完成；已掌握 / 待掌握 / 需要更多证据 /
 * 暂不可分析 / 认知暂不可用。具体映射集中在 learningStatus.js。
 */
const props = defineProps({
  nodes: { type: Array, default: () => [] },
  currentIndex: { type: Number, default: 0 },
  completedIds: { type: Array, default: () => [] },
  learningItems: { type: Array, default: () => [] },
  expandedNodeId: { type: [String, Number], default: null },
  cognitiveDetails: { type: Object, default: () => ({}) },
  cognitiveLoading: { type: Object, default: () => ({}) },
  collapsed: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'inspect', 'open-knowledge', 'recommendation-action', 'toggle'])
const itemRefs = ref([])

function setItemRef(element, index) {
  if (element) itemRefs.value[index] = element
}

async function revealCurrentItem() {
  if (props.collapsed) return
  await nextTick()
  const item = itemRefs.value[props.currentIndex]
  const element = item?.$el ?? item
  element?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
}

watch(() => [props.currentIndex, props.collapsed, props.nodes.length], revealCurrentItem, { flush: 'post' })

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const m = Math.floor(value / 60)
  const s = Math.floor(value % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function nodeState(node, index, props) {
  if (index === props.currentIndex) return 'current'
  if (props.completedIds.includes(node.id)) return 'done'
  return 'todo'
}

function itemFor(node) {
  return props.learningItems.find(item => String(item.outline_node_id) === String(node?.outlineNodeId)) || null
}

function cognitionFor(node) {
  const item = itemFor(node)
  const detail = props.cognitiveDetails[String(node?.outlineNodeId)]
  if (detail && detail.status !== 'degraded') return { ...item?.cognition, ...detail }
  return item?.cognition || {}
}

function displayState(node) {
  const state = getNodeDisplayState({
    learning: itemFor(node)?.learning,
    cognition: cognitionFor(node),
  })
  return { ...state, icon: iconMap[state.iconName] || HelpCircle, nodeKey: itemFor(node)?.cognition?.node_key }
}

function cognitionState(node) {
  const state = getCognitionDisplayState(cognitionFor(node))
  return { ...state, icon: iconMap[state.iconName] || HelpCircle }
}

function learningState(node) {
  return getLearningDisplayState(itemFor(node)?.learning)
}

function formatPercent(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, n)) * 100)}%`
}

function completionSummary() { return summarizeLearningItems(props.learningItems) }

function knowledgeNodeId(node) {
  return itemFor(node)?.cognition?.node_key ?? null
}

function recommendationAction(node) {
  const recommendation = itemFor(node)?.recommendation
  if (!recommendation || recommendation.status !== 'available') return null
  const type = recommendation.type || recommendation.recommendation_type
  if (type === 'practice_quiz' || type === 'repeat_module' || type === 'prereq_review') return { label: '去练习', action: 'practice' }
  if (type === 'advance_next' || type === 'continue') return { label: '继续学习', action: 'continue' }
  return { label: '查看建议', action: 'continue' }
}

const iconMap = {
  completed: Check,
  mastered: Check,
  needsMastery: CircleAlert,
  'needs-mastery': CircleAlert,
  'not-started': TriangleAlert,
  'in-progress': Clock3,
  'completed-pending': HelpCircle,
  degraded: TriangleAlert,
  'not-available': Info,
  unknown: HelpCircle,
  'more-evidence': HelpCircle,
}

/**
 * 启发式层级分类（后端未下发 level/depth 时作为 fallback）：
 *   chapter  — 章标题（"一、二、三、四、..."或 type 包含 chapter）
 *   section  — 节标题（"1. 2. 3. / （一）..."或 type 包含 section）
 *   point    — 知识点（其余）
 * 同时给出缩进步长，用于子行对齐。
 */
const CHAPTER_RE = /^[\u4e00-\u9fa5]{1,3}[、．.]\s*/
const SECTION_RE = /^(\d{1,2}[、．.（.]|[（(][一二三四五六七八九十百][）)])\s*/

function hierarchyOf(node) {
  const type = String(node?.type || '').toLowerCase()
  if (type.includes('chapter')) return { level: 0, kind: 'chapter' }
  if (type.includes('section') || type.includes('subsection')) return { level: 1, kind: 'section' }
  const title = String(node?.title || '')
  if (CHAPTER_RE.test(title)) return { level: 0, kind: 'chapter' }
  if (SECTION_RE.test(title)) return { level: 1, kind: 'section' }
  return { level: 2, kind: 'point' }
}

const indentStep = 12
</script>

<template>
  <aside class="sfx-track" :class="{ 'is-collapsed': collapsed }" aria-label="学习轨道">
    <button
      type="button"
      class="sfx-track-toggle"
      :aria-label="collapsed ? '展开学习轨道' : '收起学习轨道'"
      @click="emit('toggle')"
    >
      <ChevronRight v-if="collapsed" :size="16" />
      <ChevronLeft v-else :size="16" />
    </button>

    <div v-if="!collapsed && learningItems.length" class="sfx-track-summary" aria-label="学习进度摘要">
      <div class="sfx-track-summary-head">
        <span class="sfx-track-summary-kicker">学习进度</span>
        <span class="sfx-track-summary-rate">{{ completionSummary().rate }}%</span>
      </div>
      <div class="sfx-track-summary-bar" role="progressbar" :aria-valuenow="completionSummary().rate" aria-valuemin="0" aria-valuemax="100">
        <div class="sfx-track-summary-bar-fill" :style="{ width: completionSummary().rate + '%' }" />
      </div>
      <p class="sfx-track-summary-meta"><strong>{{ completionSummary().completed }} / {{ completionSummary().total }}</strong> 已完成 · 已掌握 {{ completionSummary().mastered }} · 待掌握 {{ completionSummary().needsMastery }}</p>
    </div>

    <ol class="sfx-track-list">
      <li
        v-for="(node, index) in nodes"
        :key="node.id"
        :class="`is-kind-${hierarchyOf(node).kind}`"
        :style="{ '--indent': hierarchyOf(node).level * indentStep + 'px' }"
      >
        <button
          type="button"
          class="sfx-track-item"
          :ref="element => setItemRef(element, index)"
          :class="[
            `is-${nodeState(node, index, { currentIndex, completedIds })}`,
            hierarchyOf(node).kind === 'chapter' ? 'is-chapter' : '',
            hierarchyOf(node).kind === 'section' ? 'is-section' : ''
          ]"
          :aria-current="index === currentIndex ? 'true' : undefined"
          :aria-label="`知识点 ${index + 1}：${node.title}（${displayState(node).label}）${index === currentIndex ? '（当前）' : ''}`"
          :title="collapsed ? node.title : undefined"
          @click="emit('select', index)"
        >
          <span
            class="sfx-track-item-status"
            :class="`is-status-${displayState(node).tone}`"
            :title="`${displayState(node).label}：${node.title}`"
            :aria-label="displayState(node).label"
            role="img"
          >
            <component :is="displayState(node).icon" :size="14" :stroke-width="2.4" />
          </span>
          <template v-if="!collapsed">
            <span class="sfx-track-item-main">
              <span class="sfx-track-item-title-row">
                <span class="sfx-track-item-title">
                  <span class="sfx-track-item-title-text" :title="node.title">{{ node.title }}</span>
                  <KeyRound v-if="node.isKeyPoint" :size="12" class="sfx-track-key" aria-label="重点" />
                </span>
              </span>
              <span class="sfx-track-item-subrow">
                <span :class="`is-tone-${displayState(node).tone}`" class="sfx-track-item-state-label">
                  <component :is="displayState(node).icon" :size="11" :stroke-width="2" />
                  {{ displayState(node).label }}
                </span>
                <span class="sfx-track-item-sep">·</span>
                <Clock3 :size="11" :stroke-width="2" class="sfx-track-item-muted" />
                <span class="sfx-track-item-time sfx-track-item-muted">{{ formatDuration(node.duration) }}</span>
                <span class="sfx-track-item-sep sfx-track-item-muted">·</span>
                <span class="sfx-track-item-progress">{{ formatPercent(itemFor(node)?.learning?.completion_ratio) }}</span>
                <SfxButton
                  variant="tertiary"
                  size="sm"
                  class="sfx-track-item-detail-btn"
                  :aria-label="expandedNodeId === node.outlineNodeId ? `收起${node.title}状态详情` : `查看${node.title}状态详情`"
                  @click.stop="emit('inspect', node.outlineNodeId)"
                >{{ expandedNodeId === node.outlineNodeId ? '收起' : '详情' }}</SfxButton>
              </span>
            </span>
          </template>
        </button>
        <section v-if="!collapsed && expandedNodeId === node.outlineNodeId" class="sfx-track-detail" :aria-label="`${node.title}状态详情`">
          <div class="sfx-track-detail-section">
            <p class="sfx-track-detail-heading">学习状态</p>
            <p class="sfx-track-detail-value">{{ learningState(node).label }} · {{ formatPercent(itemFor(node)?.learning?.completion_ratio) }}</p>
            <p v-if="itemFor(node)?.learning?.completion_reason" class="sfx-track-detail-muted">完成原因：{{ itemFor(node).learning.completion_reason === 'threshold' ? '进度达到 80%' : '你已标记完成' }}</p>
          </div>
          <div class="sfx-track-detail-section">
            <p class="sfx-track-detail-heading">认知状态</p>
            <p v-if="cognitiveLoading[node.outlineNodeId]" class="sfx-track-detail-value">正在读取认知详情…</p>
            <template v-else-if="cognitiveDetails[node.outlineNodeId]?.status === 'degraded'">
              <p class="sfx-track-detail-value">认知详情暂时不可用，学习仍可继续。</p>
            </template>
            <template v-else>
              <p class="sfx-track-detail-value">{{ cognitionState(node).label }}</p>
              <div v-if="cognitionFor(node)?.mastery_score != null" class="sfx-track-detail-stat">
                <span class="sfx-track-detail-stat-label">掌握度</span>
                <div class="sfx-track-detail-stat-bar">
                  <div class="sfx-track-detail-stat-fill" :style="{ width: formatPercent(cognitionFor(node).mastery_score) }" />
                </div>
                <span class="sfx-track-detail-stat-value">{{ formatPercent(cognitionFor(node).mastery_score) }}</span>
              </div>
              <div v-if="cognitionFor(node)?.evidence_confidence != null" class="sfx-track-detail-stat">
                <span class="sfx-track-detail-stat-label">置信度</span>
                <div class="sfx-track-detail-stat-bar">
                  <div class="sfx-track-detail-stat-fill is-amber" :style="{ width: formatPercent(cognitionFor(node).evidence_confidence) }" />
                </div>
                <span class="sfx-track-detail-stat-value">{{ formatPercent(cognitionFor(node).evidence_confidence) }}</span>
              </div>
              <p class="sfx-track-detail-muted">正式证据：{{ cognitionFor(node)?.evidence_count ?? cognitionFor(node)?.sample_size ?? 0 }} 条</p>
            </template>
          </div>
          <div v-if="itemFor(node)?.recommendation?.status === 'available'" class="sfx-track-detail-section">
            <p class="sfx-track-detail-heading">下一步</p>
            <p class="sfx-track-detail-value">{{ itemFor(node).recommendation.title || itemFor(node).recommendation.description || '建议完成一次针对该知识点的练习' }}</p>
            <SfxButton
              v-if="recommendationAction(node)"
              size="sm"
              variant="secondary"
              :aria-label="`${recommendationAction(node).label}：${node.title}`"
              @click.stop="emit('recommendation-action', { node, recommendation: itemFor(node).recommendation, action: recommendationAction(node).action })"
            >{{ recommendationAction(node).label }}</SfxButton>
          </div>
          <div v-if="knowledgeNodeId(node) != null" class="sfx-track-detail-actions">
            <SfxButton
              size="sm"
              variant="tertiary"
              :aria-label="`查看${node.title}的知识依据`"
              @click.stop="emit('open-knowledge', knowledgeNodeId(node))"
            >查看知识依据</SfxButton>
          </div>
        </section>
      </li>
    </ol>
  </aside>
</template>

<style scoped>
.sfx-track {
  position: relative;
  z-index: 1;
  width: var(--rail-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-soft);
  border-right: 1px solid var(--border-default);
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-track.is-collapsed {
  width: var(--rail-width-collapsed);
}

/* ============ 收起按钮：原生 button，圆形浮按钮 ============ */
.sfx-track-toggle {
  position: absolute;
  top: var(--space-4);
  right: -13px;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 30;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  appearance: none;
  font: inherit;
  padding: 0;
  flex-shrink: 0;
}

.sfx-track-toggle:hover { color: var(--ink-700); border-color: var(--border-strong); }

/* ============ 摘要区 ============ */
.sfx-track-summary {
  flex: 0 0 auto;
  margin: var(--space-4) var(--space-3) var(--space-2);
  padding: var(--space-3);
  background: var(--surface-canvas);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.sfx-track-summary-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.sfx-track-summary-kicker {
  color: var(--text-muted);
  font-size: var(--caption-size);
  font-weight: 500;
}

.sfx-track-summary-rate {
  color: var(--ink-900);
  font-size: var(--title-3-size);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.sfx-track-summary-bar {
  height: 4px;
  margin-top: var(--space-2);
  background: var(--border-subtle);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.sfx-track-summary-bar-fill {
  height: 100%;
  background: var(--ink-900);
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-track-summary-meta {
  margin: var(--space-2) 0 0;
  color: var(--text-muted);
  font-size: var(--caption-size);
  line-height: 1.5;
}

.sfx-track-summary-meta strong {
  color: var(--text-secondary);
  font-weight: 600;
}

/* ============ 列表 ============ */
.sfx-track-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: var(--space-2) var(--space-2) var(--space-4);
  gap: 2px;
  margin: 0;
  list-style: none;
}

.sfx-track-list > li.is-kind-chapter { margin-top: var(--space-3); }
.sfx-track-list > li.is-kind-chapter:first-child { margin-top: 0; }

/* ============ 轨道项 ============ */
.sfx-track-item {
  position: relative;
  width: 100%;
  appearance: none;
  border: 0;
  background: transparent;
  font: inherit;
  cursor: pointer;
  text-align: left;
  color: var(--text-secondary);
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 8px var(--space-3) 8px calc(var(--indent) + var(--space-3));
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}

.sfx-track-item:hover { background: var(--surface-cool); }
.sfx-track-item:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--color-focus), 0 0 0 4px var(--ink-100);
}

/* 章 */
.sfx-track-item.is-chapter { padding-top: 10px; padding-bottom: 10px; }
.sfx-track-item.is-chapter .sfx-track-item-title {
  font-size: var(--ui-md-size);
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.35;
}

/* 节 */
.sfx-track-item.is-section .sfx-track-item-title { font-weight: 500; }

/* 当前项 */
.sfx-track-item.is-current {
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-track-item.is-current::before {
  position: absolute;
  left: calc(var(--indent) + 3px);
  top: 10px;
  bottom: 10px;
  width: 3px;
  background: var(--ink-900);
  content: "";
  border-radius: var(--radius-full);
}
.sfx-track-item.is-chapter.is-current::before { top: 12px; bottom: 12px; }

.sfx-track-item.is-current .sfx-track-item-status {
  background: var(--ink-900);
  color: var(--surface-panel);
  border-radius: var(--radius-full);
}

.sfx-track-item.is-done .sfx-track-item-title { color: var(--green-700); }

/* 状态徽章 */
.sfx-track-item-status {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.sfx-track-item-status.is-status-green { color: var(--green-700); }
.sfx-track-item-status.is-status-amber { color: var(--amber-700); }
.sfx-track-item-status.is-status-ink { color: var(--ink-500); }
.sfx-track-item-status.is-status-neutral { color: var(--text-muted); }

/* item-main */
.sfx-track-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

/* title-row：标题 + 详情按钮（同一行，space-between） */
.sfx-track-item-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}

.sfx-track-item-title {
  flex: 1;
  min-width: 0;
  font-size: var(--ui-sm-size);
  font-weight: 500;
  line-height: 1.4;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: inherit;
  overflow: hidden;
}

.sfx-track-item-title-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  line-height: 1.45;
}

/* 详情按钮：次行右端，让出标题空间 + 紧凑型适配 */
.sfx-track-item-detail-btn {
  margin-left: auto;
  flex-shrink: 0;
  height: 22px !important;
  padding: 0 6px !important;
  font-size: var(--caption-size) !important;
  border-radius: var(--radius-sm) !important;
  min-width: 0;
}

/* subrow：状态 + 时间 + 进度 + 详情按钮（详情按钮右端常驻） */
.sfx-track-item-subrow {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--caption-size);
  line-height: 1.2;
  color: var(--text-muted);
  min-width: 0;
}

.sfx-track-item-state-label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.sfx-track-item-state-label > svg { flex-shrink: 0; }

.sfx-track-item-muted { color: var(--text-muted); opacity: 0.8; }
.sfx-track-item-sep { opacity: 0.45; flex-shrink: 0; padding: 0 1px; }
.sfx-track-item-time { flex-shrink: 0; white-space: nowrap; }
.sfx-track-item-progress {
  flex-shrink: 0;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.is-tone-green { color: var(--green-700); }
.is-tone-amber { color: var(--amber-700); }
.is-tone-ink { color: var(--ink-500); }
.is-tone-neutral { color: var(--text-muted); }

/* ============ 详情面板 ============ */
.sfx-track-detail {
  margin: 2px var(--space-2) var(--space-2) calc(var(--indent) + var(--space-3) + 22px + var(--space-2) + var(--space-3));
  padding: var(--space-3);
  background: var(--surface-canvas);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--caption-size);
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-track-detail-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-track-detail p { margin: 0; }

.sfx-track-detail-heading {
  color: var(--text-primary);
  font-weight: 600;
  font-size: var(--ui-sm-size);
  margin: 0 0 2px;
}

.sfx-track-detail-value {
  color: var(--text-secondary);
}

.sfx-track-detail-muted { color: var(--text-muted); }

/* 统计条：掌握度 / 置信度 */
.sfx-track-detail-stat {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 2px;
}

.sfx-track-detail-stat-label {
  flex-shrink: 0;
  color: var(--text-muted);
  white-space: nowrap;
}

.sfx-track-detail-stat-bar {
  flex: 1;
  height: 4px;
  min-width: 40px;
  background: var(--border-subtle);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.sfx-track-detail-stat-fill {
  height: 100%;
  background: var(--ink-900);
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease-out);
}
.sfx-track-detail-stat-fill.is-amber { background: var(--amber-500); }

.sfx-track-detail-stat-value {
  flex-shrink: 0;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

/* 底部操作区 */
.sfx-track-detail-actions {
  display: flex;
  gap: var(--space-2);
  padding-top: 2px;
  border-top: 1px solid var(--border-subtle);
  margin-top: 2px;
}

.sfx-track-key { color: var(--amber-500); flex-shrink: 0; }

/* 收缩态 */
.sfx-track.is-collapsed .sfx-track-list { padding: var(--space-3) var(--space-1); gap: var(--space-1); }
.sfx-track.is-collapsed .sfx-track-item {
  justify-content: center;
  padding: var(--space-2);
  align-items: center;
}
.sfx-track.is-collapsed .sfx-track-item-status { margin-top: 0; }
</style>
