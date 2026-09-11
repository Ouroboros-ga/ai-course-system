<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  LoaderCircle,
  Search,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-vue-next'
import {
  getActiveKnowledgeGraph,
  getActiveKnowledgeNode,
} from '@/api/graph.js'
import { getPlayerInitData } from '@/api/player.js'
import { normalizePlayerData } from '@/features/student-learning/adapters/playerWorkspaceAdapter.js'
import { nodeTypeLabel } from '@/features/knowledge-bundle/nodeTypeLabels.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import KnowledgeGraphCanvas from '@/features/knowledge-bundle/KnowledgeGraphCanvas.vue'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], default: null },
  nodeTitle: { type: String, default: '' },
  recommendationContext: { type: Object, default: null },
})
const emit = defineEmits(['jump-node', 'open-learn-node'])

const status = ref('loading')
const errorMessage = ref('')
const graph = ref(null)
const selectedKey = ref('')
const selectedNode = ref(null)
const loadingKey = ref('')
const query = ref('')
const detailOpen = ref(true)
// 学习页节点（/player/init）：只用于把原文引用页码映射到学习页节点，
// 不参与图谱渲染，也不写入任何学习状态。
const learnNodeStatus = ref('idle')
const learnNodes = ref([])

// Keep the public GraphSnapshot vocabulary explicit at the view boundary.
// The API returns the snapshot fields at the top level, while older callers
// may still wrap them in `snapshot`; both shapes are normalized here.
const snapshot = computed(() => graph.value?.snapshot || graph.value || null)
const snapshotMeta = computed(() => {
  return {
    relations: snapshot.value.relations || [],
    relation_count: snapshot.value.relation_count ?? 0,
    version: snapshot.value.version ?? null,
    ontology_version: snapshot.value.ontology_version ?? null,
  }
})
const nodes = computed(() => Array.isArray(snapshot.value?.nodes) ? snapshot.value.nodes : [])
const relations = computed(() => Array.isArray(snapshot.value?.relations) ? snapshot.value.relations : [])
const bundle = computed(() => graph.value?.bundle || null)
const nodeByKey = computed(() =>
  new Map(nodes.value.map((node) => [String(node.id), node])),
)
const filteredNodes = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  if (!term) return nodes.value
  return nodes.value.filter((node) =>
    `${node.title || ''} ${node.label || ''} ${node.description || ''}`
      .toLocaleLowerCase()
      .includes(term),
  )
})
const prerequisiteNodes = computed(() =>
  (selectedNode.value?.prerequisites || [])
    .map((key) => nodeByKey.value.get(String(key)))
    .filter(Boolean),
)
const successorNodes = computed(() =>
  (selectedNode.value?.successors || [])
    .map((key) => nodeByKey.value.get(String(key)))
    .filter(Boolean),
)
const selectedCitations = computed(() =>
  Array.isArray(selectedNode.value?.citations) ? selectedNode.value.citations : [],
)
// 原文引用页 → 学习页节点：用 page_start / page_end 的区间包含关系做映射。
// 与学习页共用 normalizePlayerData，因此节点身份（index / outlineNodeId）与学习页一致。
const citationLearnNodes = computed(() => {
  if (!selectedCitations.value.length || !learnNodes.value.length) return []
  const matched = new Map()
  selectedCitations.value.forEach((citation) => {
    const page = Number(citation?.page_number)
    if (!Number.isFinite(page)) return
    learnNodes.value.forEach((node) => {
      if (page < node.pageStart || page > node.pageEnd) return
      const key = String(node.id)
      if (!matched.has(key)) matched.set(key, { node, pages: new Set() })
      matched.get(key).pages.add(page)
    })
  })
  return [...matched.values()].map(({ node, pages }) => {
    const sorted = [...pages].sort((a, b) => a - b)
    return { ...node, pages: sorted, pagesLabel: sorted.join('、') }
  })
})
const citationPagesLabel = computed(() =>
  [...new Set(
    selectedCitations.value
      .map((citation) => Number(citation?.page_number))
      .filter((page) => Number.isFinite(page)),
  )].sort((a, b) => a - b).join('、'),
)

async function loadGraph() {
  status.value = 'loading'
  errorMessage.value = ''
  try {
    const result = await getActiveKnowledgeGraph(props.courseId)
    if (!result?.bundle || !Array.isArray(result.nodes) || !result.nodes.length) {
      graph.value = null
      status.value = 'empty'
      return
    }
    graph.value = result
    status.value = 'ready'
    const requested = props.nodeId ? String(props.nodeId) : ''
    const initial = nodeByKey.value.has(requested)
      ? requested
      : String(result.nodes[0].id)
    await selectNode(initial, false)
  } catch (error) {
    status.value = 'error'
    errorMessage.value = error?.message || '知识图谱暂时无法读取。'
  }
}

async function selectNode(nodeOrKey, navigate = true) {
  const key = String(nodeOrKey?.id || nodeOrKey || '')
  if (!key.startsWith('kn_')) return
  // 去重：点击节点列表会 emit('jump-node') 触发路由变化，路由 watch 又回调
  // selectNode(key, false)。若 key 已是当前选中且正在加载或已加载，跳过重复请求，
  // 避免 canvas 抖动。若该节点加载失败（selectedNode 为 null 且未在加载），允许重试。
  if (key === selectedKey.value && (selectedNode.value || loadingKey.value === key)) {
    if (navigate) emit('jump-node', nodeByKey.value.get(key) || { id: key })
    return
  }
  loadingKey.value = key
  selectedKey.value = key
  detailOpen.value = true
  selectedNode.value = null
  try {
    selectedNode.value = await getActiveKnowledgeNode(props.courseId, key)
  } catch (error) {
    errorMessage.value = error?.message || '知识节点暂时无法读取。'
  } finally {
    if (loadingKey.value === key) loadingKey.value = ''
  }
  if (navigate) emit('jump-node', nodeByKey.value.get(key) || { id: key })
}

// 首次选中带引用（citations）的节点时再读取学习页节点，避免无关浏览产生额外请求。
async function loadLearnNodes() {
  if (learnNodeStatus.value === 'loading' || learnNodeStatus.value === 'ready') return
  learnNodeStatus.value = 'loading'
  try {
    const response = await getPlayerInitData(props.courseId)
    const normalized = normalizePlayerData(response)
    learnNodes.value = Array.isArray(normalized?.nodes) ? normalized.nodes : []
    learnNodeStatus.value = 'ready'
  } catch {
    learnNodes.value = []
    learnNodeStatus.value = 'error'
  }
}

watch(() => props.courseId, () => {
  learnNodes.value = []
  learnNodeStatus.value = 'idle'
  loadGraph()
})
watch(() => props.nodeId, (value) => {
  if (value && graph.value) selectNode(String(value), false)
})
watch(selectedNode, (node) => {
  if (Array.isArray(node?.citations) && node.citations.length) loadLearnNodes()
})
onMounted(loadGraph)
</script>

<template>
  <section class="student-kg" aria-label="课程知识图谱">
    <header class="student-kg__header">
      <div class="student-kg__heading">
        <p class="eyebrow">已激活知识包</p>
        <h2 class="student-kg__title">课程知识图谱</h2>
        <p v-if="bundle" class="muted">
          Bundle v{{ bundle.version }} · {{ nodes.length }} 个节点 ·
          {{ relations.length }} 条语义关系
        </p>
      </div>
    </header>

    <div v-if="status === 'loading'" class="state" role="status">
      <LoaderCircle class="spin" :size="22" /> 正在读取已激活知识包…
    </div>
    <div v-else-if="status === 'error'" class="state state--error" role="alert">
      <TriangleAlert :size="21" /> {{ errorMessage }}
      <SfxButton variant="secondary" size="sm" @click="loadGraph">重试</SfxButton>
    </div>
    <div v-else-if="status === 'empty'" class="state">
      当前课程尚未激活可供学生读取的知识包。
    </div>

    <div v-else class="workspace">
      <aside class="rail">
        <label class="search">
          <Search :size="15" aria-hidden="true" />
          <input v-model="query" type="search" placeholder="搜索知识点" aria-label="搜索知识点" />
        </label>
        <div class="node-list">
          <button
            v-for="node in filteredNodes"
            :key="node.id"
            type="button"
            class="node-item"
            :class="{ active: String(node.id) === selectedKey }"
            @click="selectNode(node)"
          >
            <span class="node-item__title">{{ node.title || node.label || node.id }}</span>
            <small class="node-item__type">{{ nodeTypeLabel(node.type || node.kind) }}</small>
          </button>
        </div>
      </aside>

      <div class="canvas-shell">
        <KnowledgeGraphCanvas
          :nodes="nodes"
          :relations="relations"
          :selected-id="selectedKey"
          :right-inset="selectedKey && detailOpen ? 388 : 0"
          @select="selectNode"
        />
        <aside v-if="selectedNode && detailOpen" class="detail">
          <button type="button" class="detail__close" aria-label="收起节点详情" @click="detailOpen = false">
            <X :size="16" />
          </button>
        <template v-if="selectedNode">
          <p class="eyebrow">{{ nodeTypeLabel(selectedNode.entity_type) }}</p>
          <h3 class="detail__title">{{ selectedNode.title }}</h3>
          <p class="detail__desc">{{ selectedNode.description || '该知识点暂无补充描述。' }}</p>

          <section class="detail__section">
            <h4>先修知识</h4>
            <div v-if="prerequisiteNodes.length" class="chips">
              <SfxButton
                v-for="node in prerequisiteNodes"
                :key="node.id"
                variant="tertiary"
                size="sm"
                @click="selectNode(node)"
              >
                {{ node.title || node.label }}
              </SfxButton>
            </div>
            <p v-else class="muted">没有已确认的先修节点</p>
          </section>

          <section class="detail__section">
            <h4>后继知识</h4>
            <div v-if="successorNodes.length" class="chips">
              <SfxButton
                v-for="node in successorNodes"
                :key="node.id"
                variant="tertiary"
                size="sm"
                @click="selectNode(node)"
              >
                {{ node.title || node.label }}
              </SfxButton>
            </div>
            <p v-else class="muted">没有已确认的后继节点</p>
          </section>

          <section v-if="recommendationContext" class="detail__section">
            <h4>当前学习建议</h4>
            <p>{{ recommendationContext.description || recommendationContext.title }}</p>
            <small class="muted">
              {{ recommendationContext.degraded_reason || '已基于当前知识包生成' }}
            </small>
          </section>

          <section class="detail__section">
            <h4>对应学习节点</h4>
            <div v-if="citationLearnNodes.length" class="chips">
              <SfxButton
                v-for="entry in citationLearnNodes"
                :key="entry.id"
                variant="tertiary"
                size="sm"
                :title="`引用第 ${entry.pagesLabel} 页，进入《${entry.title}》`"
                @click="emit('open-learn-node', entry)"
              >
                {{ entry.title }}
              </SfxButton>
            </div>
            <p v-else-if="!selectedCitations.length" class="muted">
              该节点没有可定位到学习页的原文引用
            </p>
            <p v-else-if="learnNodeStatus === 'loading'" class="muted">正在匹配学习页节点…</p>
            <p v-else-if="learnNodeStatus === 'error'" class="muted">学习页节点暂时无法读取。</p>
            <p v-else class="muted">引用页面暂未映射到学习页节点</p>
            <p v-if="citationLearnNodes.length && citationPagesLabel" class="muted learn-entry__meta">
              依据原文引用第 {{ citationPagesLabel }} 页定位
            </p>
          </section>
        </template>
        </aside>
        <button v-else-if="selectedNode" type="button" class="detail-launcher" @click="detailOpen = true">
          <Sparkles :size="15" /> 查看当前节点
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* design.md §5.3 / §5.4：建设页面布局参考；内部滚动容器 min-height:0 */
.student-kg {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: var(--space-3, 12px);
  color: var(--text-primary, #172033);
}

.student-kg__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4, 16px);
  flex-shrink: 0;
}

.student-kg__title {
  margin: var(--space-1, 4px) 0;
  font-size: var(--title-2-size, 24px);
  line-height: var(--title-2-line, 32px);
  font-weight: var(--title-2-weight, 600);
  color: var(--text-primary, #172033);
}

.eyebrow {
  margin: 0;
  color: var(--ink-500, #355C7D);
  font-size: var(--caption-size, 12px);
  font-weight: 650;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.muted { color: var(--text-muted, #7B8494); }

/* design.md §5.1 L3：状态区独立，不参与整页滚动 */
.state {
  display: flex;
  min-height: 360px;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  border: 1px dashed var(--border-default, #DDE2E8);
  border-radius: var(--radius-lg, 14px);
  color: var(--text-muted, #7B8494);
}
.state--error { color: var(--red-700, #8B3A3A); }

/* 宽目录 + 主画布；节点详情作为画布上下文层，不再永久占用第三列。 */
.workspace {
  display: grid;
  grid-template-columns: 286px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: var(--space-3, 12px);
  flex: 1;
  min-height: 0;
  min-block-size: 650px;
}

.rail {
  overflow-y: auto;
  min-height: 0;
  border: 1px solid var(--border-default, #DDE2E8);
  border-radius: var(--radius-lg, 14px);
  background: var(--surface-panel, #FFFFFF);
}
.rail { padding: var(--space-3, 12px); }

/* design.md §12.3 输入框：40px 高、10px 圆角、focus 2px 墨蓝 */
.search {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  height: var(--control-height, 40px);
  padding: 0 var(--space-3, 12px);
  border: 1px solid var(--border-default, #DDE2E8);
  border-radius: var(--radius-md, 10px);
  background: var(--surface-panel, #FFFFFF);
  color: var(--text-secondary, #4E5969);
  transition: border-color var(--duration-fast, 120ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
}
.search:focus-within {
  border-color: var(--color-focus, #355C7D);
  box-shadow: 0 0 0 2px var(--ink-100, #E8EEF4);
}
.search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  font: inherit;
  color: var(--text-primary, #172033);
}

.node-list {
  display: grid;
  gap: var(--space-2, 8px);
  margin-top: var(--space-2, 8px);
}
.node-item {
  display: grid;
  gap: 3px;
  border: 1px solid transparent;
  border-radius: var(--radius-md, 10px);
  background: var(--surface-panel, #FFFFFF);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  text-align: left;
  cursor: pointer;
  position: relative;
  transition: background var(--duration-fast, 120ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
}
.node-item:hover {
  background: var(--surface-cool, #F7F8FA);
}
.node-item.active {
  border-color: var(--ink-300, #8EA7BE);
  background: var(--ink-100, #E8EEF4);
  color: var(--ink-900, #14213D);
  box-shadow: inset 3px 0 0 var(--ink-700, #203A5F);
}
.node-item__title {
  font-size: var(--ui-md-size, 14px);
  font-weight: 500;
}
.node-item__type {
  color: var(--text-muted, #7B8494);
  font-size: var(--caption-size, 12px);
}

.canvas-shell {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  border-radius: var(--radius-lg, 14px);
}

.detail {
  position: absolute;
  z-index: 5;
  top: 58px;
  right: 14px;
  bottom: 92px;
  width: min(360px, calc(100% - 28px));
  overflow-y: auto;
  border: 1px solid rgba(142, 167, 190, .75);
  border-radius: var(--radius-lg, 14px);
  background: rgba(255, 255, 255, .94);
  padding: var(--space-5, 20px);
  box-shadow: 0 16px 36px rgba(20, 33, 61, .12);
  backdrop-filter: blur(12px);
}
.detail__close {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  color: var(--text-muted, #7B8494);
}
.detail__close:hover { background: var(--surface-cool, #F7F8FA); color: var(--ink-700, #203A5F); }
.detail-launcher {
  position: absolute;
  z-index: 5;
  top: 62px;
  right: 14px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--ink-300, #8EA7BE);
  border-radius: 999px;
  padding: 8px 13px;
  background: rgba(255, 255, 255, .94);
  color: var(--ink-700, #203A5F);
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 8px 22px rgba(20, 33, 61, .10);
}
.detail__title {
  margin: var(--space-1, 4px) 0;
  font-size: var(--title-3-size, 18px);
  font-weight: var(--title-3-weight, 600);
  color: var(--text-primary, #172033);
}
.detail__desc {
  line-height: 1.6;
  color: var(--text-secondary, #4E5969);
}
.detail__section {
  border-top: 1px solid var(--border-subtle, #EDF0F3);
  padding-top: var(--space-3, 12px);
  margin-top: var(--space-3, 12px);
}
.detail__section h4 {
  margin: 0 0 var(--space-2, 8px);
  font-size: var(--ui-md-size, 14px);
  font-weight: 600;
  color: var(--text-primary, #172033);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2, 8px);
}
.learn-entry__meta {
  margin: var(--space-2, 8px) 0 0;
  font-size: var(--caption-size, 12px);
}

/* design.md §4 动效令牌：思考点动画例外 */
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1000px) {
  .workspace { grid-template-columns: 236px minmax(0, 1fr); }
}
@container (max-width: 900px) {
  .workspace { grid-template-columns: 236px minmax(0, 1fr); }
}
@container (max-width: 680px) {
  .workspace { grid-template-columns: 1fr; grid-template-rows: 250px minmax(430px, 1fr); }
  .detail { top: 52px; bottom: 132px; }
}
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
