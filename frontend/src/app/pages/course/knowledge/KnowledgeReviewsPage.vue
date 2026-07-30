<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  CheckCircle2,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  Sparkles,
} from 'lucide-vue-next'
import {
  approveKnowledgeBundle,
  getKnowledgeBundleDraft,
  getKnowledgeBundleStatus,
  regenerateKnowledgeBundle,
} from '@/api/graph.js'
import KnowledgeGraphCanvas from '@/features/knowledge-bundle/KnowledgeGraphCanvas.vue'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)
const loading = ref(true)
const error = ref('')
const draft = ref(null)
const bundleStatus = ref(null)
const selectedId = ref('')
const feedbackOpen = ref(false)
const reason = ref('')
const instructions = ref('')
const submitting = ref(false)
const actionMessage = ref('')
let timer = 0

const nodes = computed(() => draft.value?.nodes || [])
const relations = computed(() => draft.value?.relations || [])
const selected = computed(() =>
  nodes.value.find((node) => String(node.id) === selectedId.value)
  || relations.value.find((relation) => String(relation.id) === selectedId.value)
  || null,
)
const selectedEvidence = computed(() => selected.value?.evidence_previews || [])
const canApprove = computed(() =>
  draft.value?.status === 'awaiting_review' && !submitting.value,
)
const isBuilding = computed(() => {
  const run = bundleStatus.value?.latest_run?.status
  const vector = bundleStatus.value?.vector_index?.status
  return ['queued', 'exporting', 'extracting', 'classifying', 'reconciling'].includes(run)
    || ['queued', 'building', 'validating'].includes(vector)
    || ['approved_pending_index', 'indexing'].includes(bundleStatus.value?.latest_bundle?.status)
})
const runtimeReady = computed(() => bundleStatus.value?.runtime?.ready !== false)

async function load() {
  try {
    const [draftResult, statusResult] = await Promise.all([
      getKnowledgeBundleDraft(courseId),
      getKnowledgeBundleStatus(courseId),
    ])
    draft.value = draftResult
    bundleStatus.value = statusResult
    if (!selectedId.value && nodes.value.length) {
      selectedId.value = String(nodes.value[0].id)
    }
    error.value = ''
  } catch (requestError) {
    error.value = requestError?.message || '知识包状态加载失败。'
  } finally {
    loading.value = false
  }
}

async function regenerate() {
  if (!reason.value.trim() || submitting.value || !runtimeReady.value) return
  submitting.value = true
  actionMessage.value = ''
  try {
    await regenerateKnowledgeBundle(courseId, {
      reason: reason.value.trim(),
      instructions: instructions.value.trim(),
      parent_run_id: draft.value?.run_id || null,
      preserve_existing_node_identity: true,
      relation_profile: [
        'PREREQUISITE_OF',
        'PART_OF',
        'EXPLAINS',
        'CAUSES',
        'CONTRASTS_WITH',
        'APPLIES_TO',
        'EXAMPLE_OF',
        'RELATED_TO',
      ],
    })
    feedbackOpen.value = false
    reason.value = ''
    instructions.value = ''
    actionMessage.value = '已创建新 GraphRAG 运行；当前 Active Bundle 会继续服务。'
    await load()
  } catch (requestError) {
    actionMessage.value = requestError?.message || '重新生成失败。'
  } finally {
    submitting.value = false
  }
}

async function approve() {
  if (!canApprove.value) return
  const evidenceCount = new Set([
    ...nodes.value.flatMap((node) => node.source_anchor_ids || []),
    ...relations.value.flatMap((relation) => relation.source_anchor_ids || []),
  ]).size
  const accepted = window.confirm(
    `确认通过整图？\n${nodes.value.length} 个节点，${relations.value.length} 条语义关系，`
    + `${evidenceCount} 个来源 Anchor。\n`
    + '系统会转正引用、冻结检索快照并构建真实 LanceDB；校验成功前不会切换学生端。',
  )
  if (!accepted) return
  submitting.value = true
  actionMessage.value = ''
  try {
    await approveKnowledgeBundle(courseId, {
      run_id: draft.value.run_id,
      label: `GraphRAG · ${new Date().toLocaleDateString('zh-CN')}`,
    })
    actionMessage.value = '整图已批准，正在转正 Evidence 并构建向量索引。'
    await load()
  } catch (requestError) {
    actionMessage.value = requestError?.message || '整图审批失败。'
  } finally {
    submitting.value = false
  }
}

function selectGraphItem(item) {
  if (item?.id) selectedId.value = String(item.id)
}

function openEvidence(item) {
  if (!item?.run_id) return
  router.push({
    name: 'evidence-viewer',
    params: { courseId: String(courseId), runId: item.run_id },
    query: { page: String(item.page_number || 1) },
  })
}

onMounted(() => {
  load()
  timer = window.setInterval(() => {
    if (isBuilding.value) load()
  }, 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <main class="review">
    <header class="review__header">
      <div>
        <p class="eyebrow">GRAPHRAG GOVERNANCE</p>
        <h1>知识图谱整图审批</h1>
        <p>
          图谱由真实 DocumentIR 生成。教师可核验来源、通过整图，或带反馈重新生成；
          节点和关系不在此页面直接改写。
        </p>
      </div>
      <div class="actions">
        <button
          type="button"
          class="secondary"
          :disabled="!runtimeReady"
          @click="feedbackOpen = true"
        >
          <RefreshCw :size="16" /> 重新生成
        </button>
        <button type="button" class="primary" :disabled="!canApprove" @click="approve">
          <LoaderCircle v-if="submitting" class="spin" :size="16" />
          <CheckCircle2 v-else :size="16" /> 通过整图
        </button>
      </div>
    </header>

    <div v-if="loading" class="state">
      <LoaderCircle class="spin" :size="22" /> 正在读取 GraphRAG 草稿…
    </div>
    <div v-else-if="error" class="state state--error">
      <ShieldAlert :size="21" /> {{ error }}
      <button type="button" @click="load">重试</button>
    </div>

    <template v-else>
      <section v-if="!runtimeReady" class="runtime-warning">
        <ShieldAlert :size="18" />
        <div>
          <strong>GraphRAG 运行时尚未配置完成</strong>
          <p>Completion 与 Embedding 必须分别配置；在配置完成前不会发起付费构建。</p>
        </div>
      </section>

      <section class="metrics">
        <div><span>草稿状态</span><strong>{{ draft?.status || '尚未生成' }}</strong></div>
        <div><span>节点 / 关系</span><strong>{{ nodes.length }} / {{ relations.length }}</strong></div>
        <div><span>类型化关系</span><strong>{{ draft?.typed_relationship_count || 0 }}</strong></div>
        <div><span>Active Bundle</span><strong>{{ bundleStatus?.active_bundle_id || '无' }}</strong></div>
        <div><span>LanceDB</span><strong>{{ bundleStatus?.vector_index?.status || '未构建' }}</strong></div>
      </section>

      <p v-if="actionMessage" class="notice">{{ actionMessage }}</p>

      <section v-if="!draft" class="state">
        <Sparkles :size="30" />
        <div>
          <h2>尚无 GraphRAG 草稿</h2>
          <p>完成运行时配置后，可填写生成原因，从课程 DocumentIR 创建语义图谱。</p>
        </div>
      </section>

      <section v-else class="workspace">
        <div class="canvas">
          <KnowledgeGraphCanvas
            :nodes="nodes"
            :relations="relations"
            :selected-id="selectedId"
            @select="selectGraphItem"
          />
        </div>
        <aside class="detail">
          <template v-if="selected">
            <p class="eyebrow">
              {{ selected.source && selected.target ? selected.type : (selected.type || 'CONCEPT') }}
            </p>
            <h2>{{ selected.title || selected.label || selected.id }}</h2>
            <p>{{ selected.description || selected.reason || '暂无补充说明。' }}</p>
            <dl>
              <dt>稳定身份</dt><dd>{{ selected.id }}</dd>
              <dt v-if="selected.identity_id">数字身份</dt><dd v-if="selected.identity_id">{{ selected.identity_id }}</dd>
              <dt v-if="selected.source">关系端点</dt><dd v-if="selected.source">{{ selected.source }} → {{ selected.target }}</dd>
              <dt>来源 Anchor</dt><dd>{{ selected.source_anchor_ids?.length || 0 }}</dd>
              <dt v-if="selected.confidence != null">置信度</dt><dd v-if="selected.confidence != null">{{ selected.confidence }}</dd>
            </dl>
            <section class="evidence">
              <h3><FileSearch :size="16" /> 原文证据</h3>
              <article v-for="item in selectedEvidence" :key="item.anchor_id">
                <strong>第 {{ item.page_number || '—' }} 页</strong>
                <p>{{ item.text_snippet }}</p>
                <small>{{ item.anchor_id }} · {{ item.status }}</small>
                <button type="button" class="evidence-link" @click="openEvidence(item)">
                  打开原文
                </button>
              </article>
              <p v-if="!selectedEvidence.length" class="muted">
                该项没有可闭合来源，后端会拒绝整图审批。
              </p>
            </section>
          </template>
        </aside>
      </section>

      <section class="runtime">
        <h2>构建与发布边界</h2>
        <div>
          <span>策略 {{ draft?.prompt_policy_version || '—' }}</span>
          <span>Completion {{ draft?.completion_provider || '—' }} / {{ draft?.completion_model || '—' }}</span>
          <span>Embedding {{ draft?.embedding_provider || '—' }} / {{ draft?.embedding_model || '—' }}</span>
          <span>输入 {{ draft?.input_chunk_count || 0 }} chunks</span>
        </div>
        <p v-if="isBuilding">后台任务运行中；旧 Active Bundle 会持续服务到新索引校验成功。</p>
        <ul v-if="draft?.warnings?.length">
          <li v-for="(warning, index) in draft.warnings" :key="index">{{ warning }}</li>
        </ul>
      </section>
    </template>

    <div v-if="feedbackOpen" class="modal-backdrop" @click.self="feedbackOpen = false">
      <form class="modal" @submit.prevent="regenerate">
        <header>
          <div>
            <p class="eyebrow">NEW GRAPHRAG RUN</p>
            <h2>带反馈重新生成</h2>
          </div>
          <button type="button" @click="feedbackOpen = false">×</button>
        </header>
        <label>
          原因（必填）
          <input v-model="reason" required maxlength="1000" placeholder="例如：先修关系方向不准确" />
        </label>
        <label>
          教师微调说明
          <textarea
            v-model="instructions"
            rows="5"
            maxlength="8000"
            placeholder="例如：重点区分定义、原理、应用和先修关系；不得按章节顺序推断。"
          />
        </label>
        <p>新运行会保留可靠的 kn_* 身份，不覆盖当前 Active Bundle。</p>
        <button type="submit" class="primary" :disabled="!reason.trim() || submitting">
          <LoaderCircle v-if="submitting" class="spin" :size="16" />
          <Sparkles v-else :size="16" /> 创建新运行
        </button>
      </form>
    </div>
  </main>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: 18px; padding: 24px; color: #0f172a; }
.review__header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.review__header h1 { margin: 4px 0 8px; }
.review__header > div > p:last-child { max-width: 780px; margin: 0; color: #64748b; }
.eyebrow { margin: 0; color: #0f766e; font-size: 11px; font-weight: 750; letter-spacing: .11em; text-transform: uppercase; }
.actions { display: flex; gap: 8px; }
.primary, .secondary { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border-radius: 10px; padding: 9px 13px; font-weight: 650; cursor: pointer; }
.primary { border: 1px solid #0f766e; background: #0f766e; color: #fff; }
.secondary { border: 1px solid #cbd5e1; background: #fff; color: #334155; }
button:disabled { opacity: .5; cursor: not-allowed; }
.state { display: flex; min-height: 260px; align-items: center; justify-content: center; gap: 9px; border: 1px dashed #cbd5e1; border-radius: 16px; color: #64748b; }
.state--error { color: #b91c1c; }
.runtime-warning { display: flex; gap: 10px; border: 1px solid #fbbf24; border-radius: 12px; padding: 12px; background: #fffbeb; color: #92400e; }
.runtime-warning p { margin: 4px 0 0; }
.metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.metrics div { display: flex; min-width: 0; flex-direction: column; gap: 4px; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; }
.metrics span, .muted { color: #64748b; }
.metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notice { margin: 0; border: 1px solid #99f6e4; border-radius: 10px; padding: 10px 12px; background: #f0fdfa; color: #115e59; }
.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 15px; }
.canvas { min-width: 0; }
.detail { max-height: 560px; overflow: auto; border: 1px solid #e2e8f0; border-radius: 16px; padding: 17px; }
.detail h2 { margin: 4px 0 9px; }
.detail > p { color: #475569; line-height: 1.65; }
.detail dl { display: grid; grid-template-columns: 92px 1fr; gap: 7px 9px; font-size: 13px; }
.detail dt { color: #64748b; }
.detail dd { margin: 0; overflow-wrap: anywhere; }
.evidence { border-top: 1px solid #e2e8f0; margin-top: 14px; padding-top: 12px; }
.evidence h3 { display: flex; align-items: center; gap: 6px; }
.evidence article { border: 1px solid #e2e8f0; border-radius: 10px; margin-top: 8px; padding: 10px; }
.evidence article p { margin: 6px 0; line-height: 1.55; }
.evidence small { color: #64748b; }
.evidence-link { display: block; margin-top: 8px; border: 0; padding: 0; background: transparent; color: #0f766e; font-weight: 650; cursor: pointer; }
.runtime { border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px; }
.runtime h2 { margin: 0 0 9px; font-size: 16px; }
.runtime > div { display: flex; flex-wrap: wrap; gap: 8px 16px; color: #475569; }
.modal-backdrop { position: fixed; z-index: 70; inset: 0; display: grid; place-items: center; background: rgb(15 23 42 / 45%); }
.modal { width: min(560px, 92vw); display: grid; gap: 14px; border-radius: 16px; padding: 20px; background: #fff; }
.modal header { display: flex; align-items: flex-start; justify-content: space-between; }
.modal header h2 { margin: 4px 0 0; }
.modal header button { border: 0; background: transparent; font-size: 22px; cursor: pointer; }
.modal label { display: grid; gap: 6px; font-weight: 600; }
.modal input, .modal textarea { border: 1px solid #cbd5e1; border-radius: 9px; padding: 9px; font: inherit; }
.modal > p { margin: 0; color: #64748b; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .review__header, .workspace { grid-template-columns: 1fr; flex-direction: column; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
