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
  if (detail && detail.status !== 'degraded') return { ...(item?.cognition || {}), ...detail }
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
</script>

<template>
  <aside class="sfx-track" :class="{ 'is-collapsed': collapsed }" aria-label="学习轨道">
    <SfxButton
      class="sfx-track-toggle"
      variant="tertiary"
      size="sm"
      :aria-label="collapsed ? '展开学习轨道' : '收起学习轨道'"
      @click="emit('toggle')"
    >
      <template #icon>
        <ChevronRight v-if="collapsed" :size="16" />
        <ChevronLeft v-else :size="16" />
      </template>
    </SfxButton>

    <div v-if="!collapsed && learningItems.length" class="sfx-track-summary" aria-label="学习进度摘要">
      <p class="sfx-track-summary-kicker">学习进度</p>
      <p class="sfx-track-summary-main"><strong>{{ completionSummary().completed }} / {{ completionSummary().total }}</strong> 个知识点已完成 · {{ completionSummary().rate }}%</p>
      <p class="sfx-track-summary-meta">已掌握 {{ completionSummary().mastered }} · 待掌握 {{ completionSummary().needsMastery }} · 待验证 {{ completionSummary().pending }}</p>
    </div>

    <ol class="sfx-track-list">
      <li v-for="(node, index) in nodes" :key="node.id">
        <SfxButton
          type="button"
          class="sfx-track-item"
          variant="tertiary"
          size="sm"
          :ref="element => setItemRef(element, index)"
          :class="`is-${nodeState(node, index, { currentIndex, completedIds })}`"
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
            <span class="sfx-track-item-title">
              <span class="sfx-track-item-title-text">{{ node.title }}</span>
              <KeyRound v-if="node.isKeyPoint" :size="12" class="sfx-track-key" aria-label="重点" />
            </span>
            <span class="sfx-track-item-meta">
              <span class="sfx-track-item-time sfx-t-caption">{{ formatDuration(node.duration) }}</span>
              <span class="sfx-track-item-progress sfx-t-caption">{{ formatPercent(itemFor(node)?.learning?.completion_ratio) }}</span>
            </span>
          </template>
        </SfxButton>
        <div v-if="!collapsed" class="sfx-track-item-subline">
          <span :class="`is-tone-${displayState(node).tone}`">{{ displayState(node).label }}</span>
          <SfxButton
            size="sm"
            variant="tertiary"
            :aria-label="expandedNodeId === node.outlineNodeId ? `收起${node.title}状态详情` : `查看${node.title}状态详情`"
            @click.stop="emit('inspect', node.outlineNodeId)"
          >{{ expandedNodeId === node.outlineNodeId ? '收起详情' : '看状态' }}</SfxButton>
        </div>
        <section v-if="!collapsed && expandedNodeId === node.outlineNodeId" class="sfx-track-detail" :aria-label="`${node.title}状态详情`">
          <p class="sfx-track-detail-heading">学习状态</p>
          <p>{{ learningState(node).label }} · {{ formatPercent(itemFor(node)?.learning?.completion_ratio) }}</p>
          <p v-if="itemFor(node)?.learning?.completion_reason" class="sfx-track-detail-muted">完成原因：{{ itemFor(node).learning.completion_reason === 'threshold' ? '进度达到 80%' : '你已标记完成' }}</p>
          <p class="sfx-track-detail-heading">认知状态</p>
          <p v-if="cognitiveLoading[node.outlineNodeId]">正在读取认知详情…</p>
          <template v-else-if="cognitiveDetails[node.outlineNodeId]?.status === 'degraded'">
            <p>认知详情暂时不可用，学习仍可继续。</p>
          </template>
          <template v-else>
            <p>{{ cognitionState(node).label }}</p>
            <p v-if="cognitionFor(node)?.mastery_score != null" class="sfx-track-detail-muted">掌握度：{{ formatPercent(cognitionFor(node).mastery_score) }}</p>
            <p v-if="cognitionFor(node)?.evidence_confidence != null" class="sfx-track-detail-muted">证据置信度：{{ formatPercent(cognitionFor(node).evidence_confidence) }}</p>
            <p class="sfx-track-detail-muted">正式证据：{{ cognitionFor(node)?.evidence_count ?? cognitionFor(node)?.sample_size ?? 0 }} 条</p>
          </template>
          <template v-if="itemFor(node)?.recommendation?.status === 'available'">
            <p class="sfx-track-detail-heading">下一步</p>
            <p>{{ itemFor(node).recommendation.title || itemFor(node).recommendation.description || '建议完成一次针对该知识点的练习' }}</p>
            <SfxButton
              v-if="recommendationAction(node)"
              size="sm"
              variant="secondary"
              :aria-label="`${recommendationAction(node).label}：${node.title}`"
              @click.stop="emit('recommendation-action', { node, recommendation: itemFor(node).recommendation, action: recommendationAction(node).action })"
            >{{ recommendationAction(node).label }}</SfxButton>
          </template>
          <SfxButton
            v-if="knowledgeNodeId(node) != null"
            size="sm"
            variant="tertiary"
            :aria-label="`查看${node.title}的知识依据`"
            @click.stop="emit('open-knowledge', knowledgeNodeId(node))"
          >查看知识依据</SfxButton>
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

/* 收起按钮：与 BuildLayout .rail-toggle 一致的圆形浮按钮（浮在 rail 与 stage 边界上） */
.sfx-track-toggle {
  position: absolute;
  top: var(--space-3);
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
}

.sfx-track-toggle:hover { color: var(--ink-700); border-color: var(--border-strong); }

.sfx-track-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: var(--space-2);
  gap: 2px;
}

.sfx-track-summary {
  flex: 0 0 auto;
  margin: var(--space-3) var(--space-2) var(--space-2);
  padding: var(--space-3);
  background: var(--surface-canvas);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.sfx-track-summary-kicker,
.sfx-track-summary-main,
.sfx-track-summary-meta { margin: 0; }
.sfx-track-summary-kicker { color: var(--text-muted); font-size: var(--caption-size); }
.sfx-track-summary-main { margin-top: var(--space-1); color: var(--text-secondary); font-size: var(--ui-sm-size); line-height: 1.5; }
.sfx-track-summary-main strong { color: var(--ink-900); font-size: var(--title-3-size); }
.sfx-track-summary-meta { margin-top: var(--space-2); color: var(--text-muted); font-size: var(--caption-size); line-height: 1.5; }

.sfx-track-item {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  text-align: left;
  color: var(--text-secondary);
  transition: background var(--duration-fast) var(--ease-out);
}

.sfx-track-item .sfx-btn-label { display: contents; }

.sfx-track-item:hover { background: var(--surface-cool); }

/* 当前项：浅墨蓝背景 + 左侧 3px 状态线（与 BuildLayout .build-link.active 一致，不再用阴影模拟） */
.sfx-track-item.is-current {
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-track-item.is-current::before {
  position: absolute;
  left: 0;
  top: var(--space-2);
  bottom: var(--space-2);
  width: 3px;
  background: var(--ink-900);
  content: "";
  border-radius: var(--radius-full);
}

/* 左侧徽章：current 态 status 圆圈变实色反白徽章 */
.sfx-track-item.is-current .sfx-track-item-status {
  border-radius: var(--radius-full);
}

.sfx-track-item.is-done { color: var(--green-700); }

.sfx-track-item-status {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sfx-track-item-status.is-status-green { color: var(--green-700); }
.sfx-track-item-status.is-status-amber { color: var(--amber-700); }
.sfx-track-item-status.is-status-ink { color: var(--ink-500); }
.sfx-track-item-status.is-status-neutral { color: var(--text-muted); }

.sfx-track-item-index {
  font-size: var(--caption-size);
  font-weight: 600;
  color: inherit;
}

.sfx-track-item-title {
  flex: 1;
  min-width: 0;
  font-size: var(--ui-sm-size);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-track-item-title-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sfx-track-item-meta { display: inline-flex; flex-shrink: 0; align-items: center; gap: var(--space-2); }
.sfx-track-item-progress { color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.sfx-track-item-subline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: -2px var(--space-3) var(--space-1) calc(22px + var(--space-3));
  color: var(--text-muted);
  font-size: var(--caption-size);
}
.sfx-track-item-subline .sfx-btn { height: 24px; padding: 0 var(--space-1); font-size: var(--caption-size); }
.is-tone-green { color: var(--green-700); }
.is-tone-amber { color: var(--amber-700); }
.is-tone-ink { color: var(--ink-500); }
.is-tone-neutral { color: var(--text-muted); }

.sfx-track-detail {
  margin: 0 var(--space-2) var(--space-2) calc(22px + var(--space-3));
  padding: var(--space-3);
  background: var(--surface-cool);
  border-left: 2px solid var(--border-strong);
  color: var(--text-secondary);
  font-size: var(--caption-size);
  line-height: 1.5;
}
.sfx-track-detail p { margin: 0; }
.sfx-track-detail-heading { margin-top: var(--space-2) !important; color: var(--text-primary); font-weight: 600; }
.sfx-track-detail-heading:first-child { margin-top: 0 !important; }
.sfx-track-detail-muted { color: var(--text-muted); }

.sfx-track-key { color: var(--amber-500); flex-shrink: 0; }

.sfx-track-item-time { flex-shrink: 0; }
</style>
