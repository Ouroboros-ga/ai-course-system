<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  FileText,
  LoaderCircle,
  Search,
  TriangleAlert,
  X,
} from 'lucide-vue-next'
import {
  fetchProtectedImageUrl,
  getActiveKnowledgeGraph,
  getActiveKnowledgeNode,
} from '@/api/graph.js'
import KnowledgeGraphCanvas from '@/features/knowledge-bundle/KnowledgeGraphCanvas.vue'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], default: null },
  nodeTitle: { type: String, default: '' },
  recommendationContext: { type: Object, default: null },
})
const emit = defineEmits(['jump-node', 'return-anchor'])

const status = ref('loading')
const errorMessage = ref('')
const graph = ref(null)
const selectedKey = ref('')
const selectedNode = ref(null)
const query = ref('')
const selectedCitation = ref(null)
const citationImageUrl = ref('')
const imageStatus = ref('idle')

const nodes = computed(() => Array.isArray(graph.value?.nodes) ? graph.value.nodes : [])
const relations = computed(() => Array.isArray(graph.value?.relations) ? graph.value.relations : [])
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
const citations = computed(() => selectedNode.value?.citations || [])

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
  selectedKey.value = key
  selectedNode.value = null
  try {
    selectedNode.value = await getActiveKnowledgeNode(props.courseId, key)
  } catch (error) {
    errorMessage.value = error?.message || '知识节点暂时无法读取。'
  }
  if (navigate) emit('jump-node', nodeByKey.value.get(key) || { id: key })
}

async function openCitation(citation) {
  closeCitation()
  selectedCitation.value = citation
  if (!citation.render_url) return
  imageStatus.value = 'loading'
  try {
    citationImageUrl.value = await fetchProtectedImageUrl(citation.render_url)
    imageStatus.value = 'ready'
  } catch {
    imageStatus.value = 'error'
  }
}

function closeCitation() {
  if (citationImageUrl.value) URL.revokeObjectURL(citationImageUrl.value)
  citationImageUrl.value = ''
  imageStatus.value = 'idle'
  selectedCitation.value = null
}

watch(() => props.courseId, loadGraph)
watch(() => props.nodeId, (value) => {
  if (value && graph.value) selectNode(String(value), false)
})
onMounted(loadGraph)
onBeforeUnmount(closeCitation)
</script>

<template>
  <section class="student-kg" aria-label="课程知识图谱">
    <header class="student-kg__header">
      <div>
        <p class="eyebrow">ACTIVE KNOWLEDGE BUNDLE</p>
        <h2>课程知识图谱</h2>
        <p v-if="bundle" class="muted">
          Bundle v{{ bundle.version }} · {{ nodes.length }} 个节点 ·
          {{ relations.length }} 条语义关系
        </p>
      </div>
      <button type="button" class="back" @click="emit('return-anchor')">
        <ArrowLeft :size="15" /> 返回课程
      </button>
    </header>

    <div v-if="status === 'loading'" class="state">
      <LoaderCircle class="spin" :size="22" /> 正在读取已激活知识包…
    </div>
    <div v-else-if="status === 'error'" class="state state--error">
      <TriangleAlert :size="21" /> {{ errorMessage }}
      <button type="button" @click="loadGraph">重试</button>
    </div>
    <div v-else-if="status === 'empty'" class="state">
      当前课程尚未激活可供学生读取的知识包。
    </div>

    <div v-else class="workspace">
      <aside class="rail">
        <label class="search">
          <Search :size="15" />
          <input v-model="query" type="search" placeholder="搜索知识点" />
        </label>
        <div class="node-list">
          <button
            v-for="node in filteredNodes"
            :key="node.id"
            type="button"
            :class="{ active: String(node.id) === selectedKey }"
            @click="selectNode(node)"
          >
            <span>{{ node.title || node.label || node.id }}</span>
            <small>{{ node.type || node.kind || 'concept' }}</small>
          </button>
        </div>
      </aside>

      <div class="canvas">
        <KnowledgeGraphCanvas
          :nodes="nodes"
          :relations="relations"
          :selected-id="selectedKey"
          @select="selectNode"
        />
      </div>

      <aside class="detail">
        <template v-if="selectedNode">
          <p class="eyebrow">{{ selectedNode.entity_type }}</p>
          <h3>{{ selectedNode.title }}</h3>
          <p>{{ selectedNode.description || '该知识点暂无补充描述。' }}</p>

          <section>
            <h4>先修知识</h4>
            <div v-if="prerequisiteNodes.length" class="chips">
              <button
                v-for="node in prerequisiteNodes"
                :key="node.id"
                type="button"
                @click="selectNode(node)"
              >
                {{ node.title || node.label }}
              </button>
            </div>
            <p v-else class="muted">没有已确认的先修节点</p>
          </section>

          <section>
            <h4>后继知识</h4>
            <div v-if="successorNodes.length" class="chips">
              <button
                v-for="node in successorNodes"
                :key="node.id"
                type="button"
                @click="selectNode(node)"
              >
                {{ node.title || node.label }}
              </button>
            </div>
            <p v-else class="muted">没有已确认的后继节点</p>
          </section>

          <section v-if="recommendationContext">
            <h4>当前学习建议</h4>
            <p>{{ recommendationContext.description || recommendationContext.title }}</p>
            <small class="muted">
              {{ recommendationContext.degraded_reason || '已基于当前知识包生成' }}
            </small>
          </section>

          <section>
            <h4>原文引用</h4>
            <div v-if="citations.length" class="citations">
              <button
                v-for="citation in citations"
                :key="citation.citation_id"
                type="button"
                @click="openCitation(citation)"
              >
                <FileText :size="14" />
                <span>{{ citation.source_file || '课程文件' }} · 第 {{ citation.page_number }} 页</span>
              </button>
            </div>
            <p v-else class="muted">该节点没有可公开的有效 Citation</p>
          </section>
        </template>
      </aside>
    </div>

    <div v-if="selectedCitation" class="drawer-backdrop" @click.self="closeCitation">
      <aside class="citation-drawer">
        <header>
          <div>
            <p class="eyebrow">SOURCE CITATION</p>
            <h3>{{ selectedCitation.source_file || '课程原文' }}</h3>
          </div>
          <button type="button" aria-label="关闭" @click="closeCitation"><X :size="18" /></button>
        </header>
        <p>第 {{ selectedCitation.page_number }} 页 · {{ selectedCitation.status }}</p>
        <blockquote>{{ selectedCitation.text_snippet }}</blockquote>
        <div v-if="imageStatus === 'loading'" class="state">正在加载受保护页图…</div>
        <img
          v-else-if="citationImageUrl"
          :src="citationImageUrl"
          alt="Citation 原文页"
        />
        <p v-else-if="imageStatus === 'error'" class="state state--error">
          原文页图加载失败，但引用文本仍可审计。
        </p>
        <p v-else class="muted">当前引用尚无页面渲染资产。</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.student-kg { container-type: inline-size; display: flex; min-height: 620px; flex-direction: column; gap: 14px; color: #0f172a; }
.student-kg__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.student-kg__header h2, .detail h3 { margin: 4px 0 6px; }
.eyebrow { margin: 0; color: #0f766e; font-size: 11px; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }
.muted { color: #64748b; }
.back, .state button, .chips button { border: 1px solid #cbd5e1; border-radius: 9px; background: #fff; padding: 7px 10px; cursor: pointer; }
.back { display: inline-flex; align-items: center; gap: 6px; }
.state { display: flex; min-height: 360px; align-items: center; justify-content: center; gap: 8px; border: 1px dashed #cbd5e1; border-radius: 14px; color: #64748b; }
.state--error { color: #b91c1c; }
.workspace { display: grid; min-height: 560px; grid-template-columns: 220px minmax(360px, 1fr) 300px; gap: 12px; }
.rail, .detail { overflow: auto; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; }
.rail { padding: 10px; }
.search { display: flex; align-items: center; gap: 7px; border: 1px solid #cbd5e1; border-radius: 9px; padding: 7px 9px; }
.search input { min-width: 0; flex: 1; border: 0; outline: 0; }
.node-list { display: grid; gap: 6px; margin-top: 9px; }
.node-list button { display: grid; gap: 3px; border: 1px solid transparent; border-radius: 9px; background: #fff; padding: 9px; text-align: left; cursor: pointer; }
.node-list button:hover, .node-list button.active { border-color: #5eead4; background: #f0fdfa; }
.node-list small { color: #64748b; }
.canvas { min-width: 0; overflow: hidden; border-radius: 14px; }
.detail { padding: 15px; }
.detail > p { line-height: 1.6; color: #475569; }
.detail section { border-top: 1px solid #e2e8f0; padding-top: 12px; }
.detail h4 { margin: 0 0 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.citations { display: grid; gap: 7px; }
.citations button { display: flex; align-items: center; gap: 7px; border: 1px solid #dbeafe; border-radius: 9px; background: #eff6ff; padding: 8px; color: #1e40af; text-align: left; cursor: pointer; }
.drawer-backdrop { position: fixed; z-index: 1200; inset: 0; display: flex; justify-content: flex-end; background: rgb(15 23 42 / 42%); }
.citation-drawer { width: min(520px, 92vw); overflow: auto; background: #fff; padding: 20px; box-shadow: -12px 0 34px rgb(15 23 42 / 18%); }
.citation-drawer header { display: flex; align-items: flex-start; justify-content: space-between; }
.citation-drawer header button { border: 0; background: transparent; cursor: pointer; }
.citation-drawer blockquote { margin: 14px 0; border-left: 3px solid #14b8a6; padding: 9px 12px; background: #f8fafc; line-height: 1.7; }
.citation-drawer img { width: 100%; border: 1px solid #e2e8f0; border-radius: 10px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1000px) {
  .workspace { grid-template-columns: 190px 1fr; }
  .detail { grid-column: 1 / -1; }
}
@container (max-width: 900px) {
  .workspace { grid-template-columns: 190px minmax(0, 1fr); }
  .detail { grid-column: 1 / -1; max-height: 420px; }
}
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
