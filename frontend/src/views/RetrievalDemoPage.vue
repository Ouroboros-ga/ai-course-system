<template>
  <main class="demo-root">
    <header class="demo-header">
      <div>
        <p class="eyebrow">本地演示 / Shadow-1</p>
        <h1>可信检索与课程图谱演示</h1>
        <p class="subtitle">R2 BM25 + 本地 BGE Dense + RRF；与正式 V1 问答链路隔离。</p>
      </div>
      <div class="header-badges">
        <span class="badge experimental"><FlaskConical :size="15" />实验模式</span>
        <span class="badge neutral">{{ status?.effective_mode || 'v1_only' }}</span>
      </div>
    </header>

    <section v-if="!featureEnabled" class="state-card" role="status">
      <ShieldOff :size="28" />
      <div><h2>前端 Demo Flag 未启用</h2><p>设置 <code>VITE_ENABLE_RETRIEVAL_DEMO=true</code> 后重启前端；默认不会改变正式 V1 页面。</p></div>
    </section>
    <section v-else-if="loading" class="state-card" role="status"><LoaderCircle class="spin" :size="28" />正在检查本地演示状态…</section>
    <section v-else-if="disabledMessage" class="state-card warning" role="status">
      <ShieldOff :size="28" />
      <div><h2>Demo 当前已关闭</h2><p>{{ disabledMessage }}</p><p>回退状态等价于 <code>v1_only</code>；正式 V1 未被修改。</p></div>
    </section>

    <template v-else>
      <section class="disclosure" aria-label="实验范围说明">
        <Info :size="18" />
        <p><strong>实验回答，拒答校准尚未完成。</strong> Reviewed Silver 仅用于离线研究演示，不是正式 Human Gold；R3 图扩展没有被调用，也不声称提升检索指标。</p>
      </section>

      <form class="query-card" @submit.prevent="runQuery">
        <div class="query-fields">
          <label>课程范围
            <select v-model="courseId" :disabled="running || !courses.length" @change="loadCourseAssets">
              <option v-for="course in courses" :key="course" :value="course">{{ course }}</option>
            </select>
          </label>
          <label class="question-label">演示问题
            <textarea v-model.trim="question" rows="3" maxlength="2000" placeholder="输入课程范围内的问题；仅调用本地 R2 检索。" />
          </label>
        </div>
        <div class="preset-row" aria-label="预设演示问题">
          <span>预设问题</span>
          <button v-for="preset in presets" :key="preset.research_query_id" type="button" class="preset" :disabled="running" @click="question = preset.text">{{ preset.text }}</button>
        </div>
        <label v-if="isCompareMode" class="v1-reference">V1 参考回答（可选，由操作员粘贴；不会自动调用 V1）
          <textarea v-model.trim="v1Reference" rows="2" maxlength="12000" placeholder="可粘贴当前 V1 的已获取回答，用于保存并排对比。" />
        </label>
        <div class="actions">
          <button class="primary" type="submit" :disabled="running || !question"><Search :size="17" />{{ running ? '正在本地检索…' : '运行 R2 检索' }}</button>
          <button class="secondary" type="button" :disabled="running" @click="reset"><RotateCcw :size="16" />清空重置</button>
          <button class="danger" type="button" :disabled="running" @click="rollback"><ShieldOff :size="16" />一键回退 v1_only</button>
        </div>
      </form>

      <p v-if="requestError" class="error-message" role="alert"><AlertTriangle :size="17" />{{ requestError }}</p>

      <section class="result-grid">
        <article class="panel answer-panel">
          <div class="panel-title"><div><p>实验回答</p><small>Evidence-led extract · 非已验证答案</small></div><span :class="['badge', result?.confidence_label === 'abstain' ? 'warning-badge' : 'experimental']">{{ result?.confidence_label || '等待检索' }}</span></div>
          <template v-if="result">
            <p class="answer-disclaimer">{{ result.experimental_answer?.disclaimer }}</p>
            <p class="answer-copy">{{ result.experimental_answer?.content }}</p>
            <div class="compare-box">
              <div><strong>V1</strong><p>{{ comparisonText }}</p></div>
              <div><strong>V2 Shadow</strong><p>R2 结果已保存在独立 demo run：{{ result.demo_run_id }}</p></div>
            </div>
          </template>
          <div v-else class="empty"><MessageSquareText :size="24" /><p>运行一个预设问题或自由输入，查看 R2 检索、Evidence 与 Citation。</p></div>
        </article>

        <article class="panel evidence-panel" id="ppt-evidence">
          <div class="panel-title"><div><p>PPT Evidence 定位</p><small>点击 Citation 后定位到真实课件页码与 Block</small></div></div>
          <template v-if="selectedLocator">
            <div class="page-locator"><Presentation :size="27" /><div><strong>{{ selectedLocator.courseId }} · PPT 第 {{ selectedLocator.pageOrSlide }} 页</strong><span>Block：{{ selectedLocator.blockId || '未提供' }}</span><span>Citation key：<code>{{ selectedLocator.citationKey }}</code></span></div></div>
            <p class="location-note">已定位到此 Citation 的冻结 Evidence 坐标。演示页不伪造 PPT 渲染图像。</p>
          </template>
          <div v-else class="empty"><MapPin :size="24" /><p>从检索命中的 Citation 点击“定位 PPT 页”，此处将显示准确页码、Block 与 citation key。</p></div>
        </article>
      </section>

      <section class="panel hits-panel">
        <div class="panel-title"><div><p>R2 真实检索结果</p><small>课程过滤 → BM25 → 本地精确余弦 → RRF → Evidence/Citation closure</small></div><span v-if="result" class="count">{{ result.result?.hits?.length || 0 }} hits</span></div>
        <div v-if="!result" class="empty compact">尚未运行检索。</div>
        <div v-else-if="result.result?.status === 'abstain'" class="empty compact">显式 abstain：{{ result.result?.abstain_reason }}</div>
        <ol v-else class="hits-list">
          <li v-for="hit in result.result?.hits || []" :key="hit.research_chunk_id" class="hit">
            <div class="hit-rank">{{ hit.rank }}</div>
            <div class="hit-body"><div class="hit-meta"><strong>{{ hit.course_id }} · PPT {{ hit.page_or_slide }} 页</strong><code>{{ hit.block_id }}</code><span>RRF {{ Number(hit.score).toFixed(6) }}</span></div><p>{{ hit.text_snippet }}</p>
              <div class="citation-row"><button v-for="citation in hit.citations" :key="citation.citation_key" type="button" class="citation" @click="locateCitation(hit, citation)"><MapPin :size="14" />定位 PPT {{ citation.page_or_slide }} 页 · {{ citation.citation_key }}</button></div>
            </div>
          </li>
        </ol>
      </section>

      <section class="graph-grid">
        <article class="panel graph-panel">
          <div class="panel-title"><div><p>确定性课程图谱快照</p><small>只展示当前 accepted 结构边；不进行 GraphRAG 或 R3 扩展。</small></div><span class="count">{{ graphCanvas.nodes.length }} 节点 / {{ graphCanvas.edges.length }} 边</span></div>
          <div v-if="graphLoading" class="canvas-state"><LoaderCircle class="spin" :size="22" />加载冻结 GraphSnapshot…</div>
          <GraphCanvas v-else-if="graphCanvas.nodes.length" class="demo-canvas" :nodes="graphCanvas.nodes" :edges="graphCanvas.edges" :selected-id="selectedGraphNode?.id || null" @select="selectedGraphNode = $event" />
          <div v-else class="canvas-state">没有可显示的确定性图谱节点。</div>
        </article>
        <aside class="panel graph-detail">
          <div class="panel-title"><div><p>图谱节点与关系</p><small>GraphSnapshot，不含推测语义边</small></div></div>
          <template v-if="selectedGraphNode"><dl><dt>类型</dt><dd>{{ selectedGraphNode.nodeType }}</dd><dt>来源 ID</dt><dd><code>{{ selectedGraphNode.sourceId }}</code></dd><dt>课程</dt><dd>{{ selectedGraphNode.courseId }}</dd></dl></template>
          <p v-else class="empty compact">在画布中选择节点查看来源。</p>
          <ul class="edge-list"><li v-for="edge in graphCanvas.edges.slice(0, 24)" :key="`${edge.source}-${edge.target}-${edge.predicate}`"><code>{{ edge.predicate }}</code><span>{{ edge.evidenceIds.length ? `${edge.evidenceIds.length} 个 Evidence` : '结构关系' }}</span></li></ul>
        </aside>
      </section>

      <section class="trace-grid">
        <article class="panel"><div class="panel-title"><div><p>运行 Trace</p><small>真实本次运行阶段；不伪造模型或图扩展阶段。</small></div></div><ol v-if="result" class="trace-list"><li v-for="stage in result.run_trace?.stages || []" :key="stage.name"><span></span><div><strong>{{ stage.name }}</strong><p>{{ stage.detail }}</p></div></li></ol><p v-else class="empty compact">等待一次演示运行。</p></article>
        <article class="panel"><div class="panel-title"><div><p>运行元数据</p><small>本地模型与延迟统计</small></div></div><dl v-if="result" class="metadata"><dt>P50 / P95</dt><dd>{{ result.runtime?.p50_ms }} / {{ result.runtime?.p95_ms }} ms</dd><dt>模型 revision</dt><dd><code>{{ result.runtime?.model?.revision }}</code></dd><dt>权重 SHA</dt><dd><code>{{ result.runtime?.model?.model_safetensors_sha256 }}</code></dd><dt>R2 config SHA</dt><dd><code>{{ result.runtime?.r2_config_sha256 }}</code></dd></dl><p v-else class="empty compact">等待一次演示运行。</p></article>
      </section>

      <section v-if="result?.warnings?.length" class="warnings" aria-label="实验风险提示"><AlertTriangle :size="18" /><ul><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul></section>
    </template>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { AlertTriangle, FlaskConical, Info, LoaderCircle, MapPin, MessageSquareText, Presentation, RotateCcw, Search, ShieldOff } from 'lucide-vue-next'
import { featureFlags } from '@/config/featureFlags.js'
import { getRetrievalDemoCourses, getRetrievalDemoGraph, getRetrievalDemoPresets, getRetrievalDemoStatus, rollbackRetrievalDemo, runRetrievalDemo } from '@/api/retrieval_demo.js'
import GraphCanvas from '@/features/graph-browser/components/GraphCanvas.vue'
import { citationToPptLocator, snapshotToCanvasGraph } from '@/features/retrieval-demo/contracts.js'

const featureEnabled = featureFlags.retrievalDemo
const loading = ref(false)
const graphLoading = ref(false)
const running = ref(false)
const requestError = ref('')
const disabledMessage = ref('')
const status = ref(null)
const courses = ref([])
const courseId = ref('')
const presets = ref([])
const question = ref('')
const v1Reference = ref('')
const result = ref(null)
const graphCanvas = ref({ nodes: [], edges: [] })
const selectedLocator = ref(null)
const selectedGraphNode = ref(null)

const isCompareMode = computed(() => status.value?.effective_mode === 'demo_compare')
const comparisonText = computed(() => {
  const comparison = result.value?.v1_v2_comparison
  if (!comparison) return '尚未运行。'
  return comparison.status === 'operator_supplied_v1_reference' ? comparison.v1_text : comparison.warning
})

function errorText(error) {
  const payload = error?.response?.data
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') return detail.reason || detail.code || JSON.stringify(detail)
  const message = payload?.message
  if (typeof message === 'string') return message
  if (message && typeof message === 'object') return message.reason || message.code || JSON.stringify(message)
  return error?.message || '演示服务暂时不可用。'
}

async function loadCourseAssets() {
  if (!courseId.value) return
  graphLoading.value = true
  requestError.value = ''
  try {
    const [presetData, graphData] = await Promise.all([getRetrievalDemoPresets(courseId.value), getRetrievalDemoGraph(courseId.value)])
    presets.value = presetData?.presets || []
    graphCanvas.value = snapshotToCanvasGraph(graphData)
    selectedGraphNode.value = null
  } catch (error) {
    requestError.value = errorText(error)
  } finally {
    graphLoading.value = false
  }
}

async function initialize() {
  if (!featureEnabled) return
  loading.value = true
  try {
    const nextStatus = await getRetrievalDemoStatus()
    status.value = nextStatus
    if (!nextStatus?.enabled) {
      disabledMessage.value = nextStatus?.reason || '后端处于 v1_only 或非演示环境。'
      return
    }
    const courseData = await getRetrievalDemoCourses()
    courses.value = courseData?.course_ids || []
    courseId.value = courses.value[0] || ''
    await loadCourseAssets()
  } catch (error) {
    disabledMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function runQuery() {
  if (!question.value || !courseId.value) return
  running.value = true
  requestError.value = ''
  try {
    result.value = await runRetrievalDemo({ course_id: courseId.value, question: question.value, v1_reference: v1Reference.value || null })
    selectedLocator.value = null
  } catch (error) {
    requestError.value = errorText(error)
  } finally {
    running.value = false
  }
}

async function locateCitation(hit, citation) {
  selectedLocator.value = citationToPptLocator(hit, citation)
  await nextTick()
  document.getElementById('ppt-evidence')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function reset() {
  question.value = ''
  v1Reference.value = ''
  result.value = null
  requestError.value = ''
  selectedLocator.value = null
  selectedGraphNode.value = null
}

async function rollback() {
  try {
    const rollbackState = await rollbackRetrievalDemo()
    disabledMessage.value = rollbackState?.reason || '已回退至 v1_only。'
    status.value = rollbackState
    reset()
  } catch (error) {
    requestError.value = errorText(error)
  }
}

onMounted(initialize)
</script>

<style scoped>
.demo-root { --demo-primary: #4f46e5; --demo-ink: #1e1b4b; --demo-bg: #eef2ff; --demo-border: #c7d2fe; --demo-accent: #c2410c; min-height: 100dvh; box-sizing: border-box; padding: 28px; background: var(--demo-bg); color: var(--demo-ink); }
.demo-header { max-width: 1440px; margin: 0 auto 20px; display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }.eyebrow { margin: 0; font-size: 12px; font-weight: 700; letter-spacing: .08em; color: var(--demo-primary); }.demo-header h1 { margin: 4px 0; font-size: clamp(26px, 4vw, 38px); line-height: 1.15; }.subtitle { margin: 0; color: #4338ca; }.header-badges,.actions,.preset-row,.citation-row { display: flex; gap: 8px; flex-wrap: wrap; }.badge,.count { display: inline-flex; align-items: center; gap: 5px; min-height: 28px; box-sizing: border-box; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; }.experimental { background: #ede9fe; color: #4338ca; border: 1px solid #a5b4fc; }.neutral,.count { background: #fff; color: #3730a3; border: 1px solid var(--demo-border); }.warning-badge { background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; }.state-card,.disclosure,.warnings { max-width: 1440px; margin: 0 auto 16px; display: flex; gap: 12px; align-items: flex-start; box-sizing: border-box; padding: 18px; border-radius: 14px; background: #fff; border: 1px solid var(--demo-border); }.state-card { min-height: 120px; align-items: center; justify-content: center; text-align: left; }.state-card h2 { margin: 0 0 5px; }.state-card p,.disclosure p { margin: 0; line-height: 1.6; }.warning,.warnings { border-color: #fdba74; background: #fff7ed; color: #7c2d12; }.query-card,.panel { box-sizing: border-box; background: #fff; border: 1px solid var(--demo-border); border-radius: 16px; box-shadow: 0 8px 24px rgba(79,70,229,.08); }.query-card { max-width: 1440px; margin: 0 auto 16px; padding: 18px; }.query-fields { display: grid; grid-template-columns: 180px minmax(0,1fr); gap: 16px; }.query-fields label,.v1-reference { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 700; }.query-fields select,.query-fields textarea,.v1-reference textarea { width: 100%; box-sizing: border-box; min-height: 44px; border: 1px solid #a5b4fc; border-radius: 10px; background: #fff; color: #1e1b4b; padding: 10px; font: inherit; line-height: 1.5; }.query-fields textarea,.v1-reference textarea { resize: vertical; }.query-fields select:focus,.query-fields textarea:focus,.v1-reference textarea:focus,button:focus-visible { outline: 3px solid rgba(79,70,229,.35); outline-offset: 2px; }.preset-row { align-items: center; margin: 14px 0; font-size: 13px; }.preset-row > span { font-weight: 700; color: #4338ca; }.preset,.citation { min-height: 36px; border-radius: 8px; border: 1px solid #c7d2fe; background: #f8faff; color: #3730a3; padding: 6px 10px; cursor: pointer; font: inherit; }.preset:hover,.citation:hover { background: #ede9fe; border-color: #818cf8; }.v1-reference { margin-bottom: 14px; }.actions { justify-content: flex-end; }.primary,.secondary,.danger { min-height: 44px; border-radius: 10px; padding: 0 14px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; font: inherit; font-weight: 700; cursor: pointer; }.primary { color: #fff; background: var(--demo-primary); border: 1px solid var(--demo-primary); }.secondary { color: #3730a3; background: #fff; border: 1px solid #a5b4fc; }.danger { color: #9a3412; background: #fff7ed; border: 1px solid #fdba74; }.primary:disabled,.secondary:disabled,.danger:disabled,.preset:disabled { cursor: not-allowed; opacity: .55; }.error-message { max-width: 1440px; margin: 0 auto 16px; display: flex; gap: 8px; padding: 12px; color: #991b1b; background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; }.result-grid,.graph-grid,.trace-grid { max-width: 1440px; margin: 0 auto 16px; display: grid; gap: 16px; }.result-grid { grid-template-columns: minmax(0,1.3fr) minmax(320px,.7fr); }.graph-grid { grid-template-columns: minmax(0,1fr) 340px; }.trace-grid { grid-template-columns: 1fr 1fr; }.panel { padding: 16px; min-width: 0; }.panel-title { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }.panel-title p { margin: 0; font-size: 16px; font-weight: 800; }.panel-title small { display: block; margin-top: 3px; color: #6366a6; font-size: 12px; line-height: 1.4; }.answer-disclaimer { margin: 16px 0 8px; padding: 9px; color: #9a3412; background: #fff7ed; border-left: 3px solid #ea580c; line-height: 1.5; font-size: 13px; }.answer-copy { white-space: pre-wrap; line-height: 1.7; }.compare-box { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.compare-box > div { padding: 10px; background: #f8faff; border: 1px solid #e0e7ff; border-radius: 10px; }.compare-box p { margin: 5px 0 0; line-height: 1.5; font-size: 13px; }.empty { min-height: 160px; display: flex; flex-direction: column; gap: 8px; align-items: center; justify-content: center; text-align: center; color: #6366a6; line-height: 1.5; }.compact { min-height: 70px; }.page-locator { margin-top: 16px; display: flex; gap: 12px; align-items: flex-start; padding: 14px; background: #fff7ed; border: 1px solid #fdba74; border-radius: 12px; color: #7c2d12; }.page-locator div { display: flex; flex-direction: column; gap: 4px; }.location-note { color: #9a3412; font-size: 13px; line-height: 1.5; }.hits-panel { max-width: 1440px; margin: 0 auto 16px; }.hits-list { margin: 14px 0 0; padding: 0; list-style: none; }.hit { display: grid; grid-template-columns: 34px minmax(0,1fr); gap: 10px; padding: 13px 0; border-top: 1px solid #e0e7ff; }.hit-rank { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: var(--demo-primary); font-weight: 800; }.hit-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; color: #4338ca; }.hit-body p { margin: 7px 0; line-height: 1.6; white-space: pre-wrap; }.citation { display: inline-flex; align-items: center; gap: 5px; min-height: 38px; font-size: 12px; }.graph-panel { min-height: 540px; display: flex; flex-direction: column; }.demo-canvas { flex: 1; min-height: 450px; margin-top: 14px; }.canvas-state { min-height: 420px; display: flex; align-items: center; justify-content: center; gap: 8px; color: #6366a6; }.graph-detail dl,.metadata { display: grid; grid-template-columns: max-content minmax(0,1fr); gap: 9px 12px; margin: 16px 0; font-size: 13px; }.graph-detail dt,.metadata dt { color: #6366a6; }.graph-detail dd,.metadata dd { margin: 0; overflow-wrap: anywhere; }.edge-list { margin: 14px 0 0; padding: 0; list-style: none; max-height: 270px; overflow: auto; }.edge-list li { display: flex; justify-content: space-between; gap: 8px; padding: 8px 0; border-top: 1px solid #e0e7ff; font-size: 12px; }.edge-list span { color: #6366a6; }.trace-list { margin: 14px 0 0; padding: 0; list-style: none; }.trace-list li { display: grid; grid-template-columns: 12px minmax(0,1fr); gap: 9px; padding: 8px 0; border-top: 1px solid #e0e7ff; }.trace-list span { width: 9px; height: 9px; margin-top: 5px; border-radius: 50%; background: #4f46e5; }.trace-list p { margin: 3px 0 0; color: #6366a6; font-size: 12px; line-height: 1.5; }.warnings ul { margin: 0; padding-left: 20px; line-height: 1.6; }.spin { animation: spin 1s linear infinite; }code { font-family: ui-monospace,SFMono-Regular,Consolas,monospace; overflow-wrap: anywhere; }@keyframes spin { to { transform: rotate(360deg); } }@media (max-width: 980px) { .demo-root { padding: 16px; }.demo-header,.result-grid,.graph-grid,.trace-grid { grid-template-columns: 1fr; }.demo-header { display: flex; flex-direction: column; }.query-fields { grid-template-columns: 1fr; }.graph-panel { min-height: 420px; }.demo-canvas { min-height: 360px; }.actions { justify-content: stretch; }.actions button { flex: 1; }.compare-box { grid-template-columns: 1fr; } }@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; animation-duration: .01ms !important; } }
</style>
