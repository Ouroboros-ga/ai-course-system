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
  X,
} from 'lucide-vue-next'
import {
  approveKnowledgeBundle,
  getKnowledgeBundleDraft,
  getKnowledgeBundleStatus,
  regenerateKnowledgeBundle,
} from '@/api/graph.js'
import KnowledgeGraphCanvas from '@/features/knowledge-bundle/KnowledgeGraphCanvas.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

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
    + '确认后，系统会正式启用这版图谱并更新学生端内容；校验通过前学生看到的不会变化。',
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
  // 点击画布空白处时 item 为 null，取消选择
  selectedId.value = item?.id ? String(item.id) : ''
}

// warnings 里可能是字符串，也可能是整份质量报告对象（code=QUALITY_REFINEMENT_REPORT）；
// 对象转为精简自然语言摘要，避免页面上出现大段原始 JSON。
function warningText(warning) {
  if (typeof warning === 'string') return warning
  if (!warning || typeof warning !== 'object') return String(warning ?? '')
  if (warning.code !== 'QUALITY_REFINEMENT_REPORT') {
    return warning.message || warning.code || JSON.stringify(warning)
  }
  const focus = warning.focus_selection
  const parts = []
  parts.push(`质量精炼完成：${warning.source_entity_count ?? '—'} 个实体对齐，快照 ${warning.snapshot_node_count ?? '—'} 节点 / ${warning.snapshot_relationship_count ?? '—'} 关系`)
  if (focus) {
    parts.push(`重点筛选 ${focus.source_node_count} → ${focus.selected_node_count} 节点（归并至 ${focus.merged_node_count}，剔除噪声 ${focus.noise_filtered_count} 个），关系 ${focus.source_relation_count} → ${focus.selected_relation_count}`)
  } else {
    const cleaned = (warning.rejected_placeholder_count || 0)
      + (warning.removed_placeholder_relationship_count || 0)
      + (warning.removed_self_loop_count || 0)
      + (warning.deduplicated_relationship_count || 0)
    parts.push(`清理占位/自环/重复 ${cleaned} 项`)
  }
  parts.push(`零模型调用，来源运行 ${String(warning.artifact_source_run_id || '').slice(0, 12)}…`)
  return parts.join('；')
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
        <p class="eyebrow">知识图谱审批</p>
        <h1>知识图谱整图审批</h1>
        <p>
          知识图谱根据课程材料自动生成。教师可核对来源、通过审核，或附上反馈后重新生成。
        </p>
      </div>
      <div class="actions">
        <SfxButton
          variant="secondary"
          size="sm"
          :disabled="!runtimeReady"
          @click="feedbackOpen = true"
        >
          <template #icon><RefreshCw :size="16" /></template>
          重新生成
        </SfxButton>
        <SfxButton variant="primary" size="sm" :disabled="!canApprove" :loading="submitting" @click="approve">
          <template #icon><CheckCircle2 :size="16" /></template>
          通过整图
        </SfxButton>
      </div>
    </header>

    <div v-if="loading" class="state">
      <LoaderCircle class="spin" :size="22" /> 正在读取 GraphRAG 草稿…
    </div>
    <div v-else-if="error" class="state state--error">
      <ShieldAlert :size="21" /> {{ error }}
      <SfxButton variant="secondary" @click="load">重试</SfxButton>
    </div>

    <template v-else>
      <section v-if="!runtimeReady" class="runtime-warning">
        <ShieldAlert :size="18" />
        <div>
          <strong>图谱生成所需的 AI 服务尚未配置完成</strong>
          <p>文本生成与向量化服务需分别配置，配置完成前不会产生费用。</p>
        </div>
      </section>

      <section class="metrics">
        <div><span>草稿状态</span><strong>{{ draft?.status || '尚未生成' }}</strong></div>
        <div><span>节点 / 关系</span><strong>{{ nodes.length }} / {{ relations.length }}</strong></div>
        <div><span>类型化关系</span><strong>{{ draft?.typed_relationship_count || 0 }}</strong></div>
        <div><span>Active Bundle</span><strong>{{ bundleStatus?.active_bundle_id || '无' }}</strong></div>
        <div><span>向量索引</span><strong>{{ bundleStatus?.vector_index?.status || '未构建' }}</strong></div>
      </section>

      <p v-if="actionMessage" class="notice">{{ actionMessage }}</p>

      <section v-if="!draft" class="state">
        <Sparkles :size="30" />
        <div>
          <h2>尚无知识图谱草稿</h2>
          <p>完成配置后，可填写生成原因，从课程材料中生成知识图谱。</p>
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
                <SfxButton variant="tertiary" size="sm" @click="openEvidence(item)">
                  打开原文
                </SfxButton>
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
          <li v-for="(warning, index) in draft.warnings" :key="index">{{ warningText(warning) }}</li>
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
          <SfxButton variant="tertiary" size="sm" aria-label="关闭" @click="feedbackOpen = false">
            <template #icon><X :size="16" /></template>
          </SfxButton>
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
        <SfxButton type="submit" variant="primary" :disabled="!reason.trim() || submitting" :loading="submitting">
          <template #icon><Sparkles :size="16" /></template>
          创建新运行
        </SfxButton>
      </form>
    </div>
  </main>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); color: var(--text-primary); }
.review__header { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-4); }
.review__header h1 { margin: var(--space-1) 0 var(--space-2); }
.review__header > div > p:last-child { max-width: 780px; margin: 0; color: var(--text-muted); }
.eyebrow { margin: 0; color: var(--ink-700); font-size: var(--caption-size); font-weight: 750; letter-spacing: .11em; text-transform: uppercase; }
.actions { display: flex; gap: var(--space-2); }
.primary, .secondary { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); font-weight: 650; cursor: pointer; }
.primary { border: 1px solid var(--ink-700); background: var(--ink-700); color: var(--surface-panel); }
.secondary { border: 1px solid var(--border-default); background: var(--surface-panel); color: var(--text-secondary); }
button:disabled { opacity: .5; cursor: not-allowed; }
.state { display: flex; min-height: 260px; align-items: center; justify-content: center; gap: var(--space-2); border: 1px dashed var(--border-default); border-radius: var(--radius-lg); color: var(--text-muted); }
.state--error { color: var(--red-700); }
.runtime-warning { display: flex; gap: var(--space-2); border: 1px solid var(--amber-500); border-radius: var(--radius-md); padding: var(--space-3); background: var(--amber-100); color: var(--amber-700); }
.runtime-warning p { margin: var(--space-1) 0 0; }
.metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-2); }
.metrics div { display: flex; min-width: 0; flex-direction: column; gap: var(--space-1); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-3); }
.metrics span, .muted { color: var(--text-muted); }
.metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notice { margin: 0; border: 1px solid var(--ink-100); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); background: var(--surface-cool); color: var(--ink-700); }
.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: var(--space-4); }
.canvas { min-width: 0; }
.detail { max-height: 560px; overflow: auto; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: var(--space-4); }
.detail h2 { margin: var(--space-1) 0 var(--space-2); }
.detail > p { color: var(--text-secondary); line-height: 1.65; }
.detail dl { display: grid; grid-template-columns: 92px 1fr; gap: var(--space-2); font-size: var(--ui-sm-size); }
.detail dt { color: var(--text-muted); }
.detail dd { margin: 0; overflow-wrap: anywhere; }
.evidence { border-top: 1px solid var(--border-subtle); margin-top: var(--space-3); padding-top: var(--space-3); }
.evidence h3 { display: flex; align-items: center; gap: var(--space-2); }
.evidence article { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); margin-top: var(--space-2); padding: var(--space-2); }
.evidence article p { margin: var(--space-2) 0; line-height: 1.55; }
.evidence small { color: var(--text-muted); }
.evidence-link { display: block; margin-top: var(--space-2); border: 0; padding: 0; background: transparent; color: var(--ink-700); font-weight: 650; cursor: pointer; }
.runtime { border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: var(--space-3); }
.runtime h2 { margin: 0 0 var(--space-2); font-size: var(--title-3-size); }
.runtime > div { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4); color: var(--text-secondary); }
.modal-backdrop { position: fixed; z-index: 70; inset: 0; display: grid; place-items: center; background: rgb(15 23 42 / 45%); }
.modal { width: min(560px, 92vw); display: grid; gap: var(--space-3); border-radius: var(--radius-lg); padding: var(--space-4); background: var(--surface-panel); }
.modal header { display: flex; align-items: flex-start; justify-content: space-between; }
.modal header h2 { margin: var(--space-1) 0 0; }
.modal header button { border: 0; background: transparent; font-size: var(--title-2-size); cursor: pointer; }
.modal label { display: grid; gap: var(--space-1); font-weight: 600; }
.modal input, .modal textarea { border: 1px solid var(--border-default); border-radius: var(--radius-sm); padding: var(--space-2); font: inherit; }
.modal > p { margin: 0; color: var(--text-muted); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .review__header, .workspace { grid-template-columns: 1fr; flex-direction: column; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
