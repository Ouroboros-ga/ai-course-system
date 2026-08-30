<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  CheckCircle2,
  ExternalLink,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  Tag,
  X,
} from 'lucide-vue-next'
import {
  listCandidates,
  listEvidence,
  transitionReview,
  publishReviewedSnapshot,
} from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 节点/关系候选审核（GraphNodeReview，来自 /graph/course/{id}/candidates）。
 *
 * XH-202620：候选经"学科知识库名称锚定"对齐后，超库(未命中知识库)的知识点会被后端
 * 自动分流为 needs_review——教师必须逐条确认后才可发布（fail-closed）。本页把
 * 这类"需人工确认（超库）"候选置顶，并加 out_of_kb 徽标，让教师优先处理。
 */
const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)

const status = ref('loading')
const error = ref('')
const all = ref([])
const evidence = ref([])
const selectedId = ref('')
const acting = ref('')
const actionError = ref('')
const actionMessage = ref('')
const showPublished = ref(false)
let timer = 0

const DECISION_META = {
  proposed: { label: '待审核', tone: 'amber' },
  needs_review: { label: '需人工确认', tone: 'red' },
  accepted: { label: '已通过', tone: 'green' },
  rejected: { label: '已驳回', tone: 'neutral' },
}

/** 需人工确认（超库）的候选排在前面，其次是待审核，最后是已定论 */
const sorted = computed(() => {
  const rank = { needs_review: 0, proposed: 1, accepted: 2, rejected: 3 }
  return [...all.value].sort((a, b) => {
    const ra = rank[a.decision] ?? 1
    const rb = rank[b.decision] ?? 1
    if (ra !== rb) return ra - rb
    return String(a.target_type).localeCompare(String(b.target_type))
  })
})

const pendingCount = computed(() =>
  all.value.filter((item) => ['proposed', 'needs_review'].includes(item.decision)).length,
)
const outOfKbCount = computed(() =>
  all.value.filter((item) => item.kbsource_type === 'out_of_kb').length,
)
const selected = computed(() =>
  sorted.value.find((item) => String(item.id) === selectedId.value) ?? null,
)
const selectedContent = computed(() => selected.value?.target_content ?? {})
const canPublish = computed(() => pendingCount.value === 0 && all.value.length > 0)

function labelOf(item) {
  return item?.target_content?.label ?? item?.target_id ?? '未命名'
}

function sourceMeta(item) {
  switch (item.kbsource_type) {
    case 'kb_aligned':
      return { label: '知识库已收录', tone: 'green', detail: item.kb_matched_name || item.kb_node_key }
    case 'out_of_kb':
      return { label: '超库·需人工', tone: 'red', detail: '未命中学科知识库' }
    default:
      return { label: '未对齐', tone: 'neutral', detail: '对齐未启用或知识库为空' }
  }
}

async function load() {
  status.value = 'loading'
  error.value = ''
  try {
    const [candRes, evidRes] = await Promise.all([
      listCandidates(courseId),
      listEvidence(courseId).catch(() => ({ items: [] })),
    ])
    all.value = candRes?.items ?? []
    evidence.value = evidRes?.items ?? []
    if (!selectedId.value && all.value.length) {
      selectedId.value = String(all.value[0].id)
    }
    status.value = 'ready'
  } catch (requestError) {
    error.value = requestError?.message || '候选加载失败。'
    status.value = 'error'
  }
}

async function act(item, newDecision) {
  if (acting.value) return
  acting.value = String(item.id)
  actionError.value = ''
  actionMessage.value = ''
  try {
    // 仅当确认接受并已存在可关联证据时传入；否则交由发布门做最终校验。
    const payload = { new_decision: newDecision }
    if (newDecision === 'accepted') {
      const linked = evidence.value
        .filter((e) => e.node_id != null && String(e.node_id) === String(item.identity_node_id))
        .map((e) => e.evidence_id)
      if (linked.length) payload.evidence_ids = linked
    }
    const updated = await transitionReview(courseId, item.id, payload)
    all.value = all.value.map((it) => (String(it.id) === String(item.id) ? { ...it, ...updated } : it))
    actionMessage.value = newDecision === 'accepted' ? '已通过该候选。' : '已驳回该候选。'
  } catch (requestError) {
    actionError.value = requestError?.message || '流转失败。'
  } finally {
    acting.value = ''
  }
}

function approveAll() {
  if (!canPublish.value) return
  const acceptedCount = all.value.filter((item) => item.decision === 'accepted').length
  const ok = window.confirm(
    `确认发布当前已通过候选？\n`
    + `共 ${all.value.length} 条候选，其中已通过 ${acceptedCount} 条。\n`
    + '未通过（待审核/需人工确认）的候选不会被发布；缺少正式证据的已通过候选也会被发布门拦截。',
  )
  if (!ok) return
  publishReviewedSnapshot(courseId, { label: `候选审核发布 · ${new Date().toLocaleDateString('zh-CN')}` })
    .then(() => {
      showPublished.value = true
      actionMessage.value = '已发布通过候选；新的不可变知识图谱快照已生成。'
    })
    .catch((requestError) => {
      actionError.value = requestError?.message || '发布失败，仍有未完成审核的证据或候选。'
    })
}

function openEvidence(item) {
  if (!item?.id) return
  router.push({ name: 'app-course-knowledge-evidence', params: { courseId: String(courseId) } })
}

onMounted(() => {
  load()
  timer = window.setInterval(() => {
    if (status.value === 'ready' && pendingCount.value > 0) load()
  }, 8000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <main class="review">
    <header class="review__header">
      <div>
        <p class="eyebrow">节点候选审核</p>
        <h1>候选知识节点审核</h1>
        <p>
          课件解析提取的知识点候选在此逐条确认。未命中学科知识库的"超库"候选会被强制进入
          <strong>需人工确认</strong>，教师不确认不会随图谱发布（fail-closed）。
        </p>
      </div>
      <div class="actions">
        <SfxBadge v-if="outOfKbCount" tone="red">{{ outOfKbCount }} 条超库待人工</SfxBadge>
        <SfxBadge v-if="pendingCount" tone="amber">{{ pendingCount }} 条待审核</SfxBadge>
        <SfxButton variant="secondary" size="sm" @click="load">
          <template #icon><RefreshCw :size="16" /></template>
          刷新
        </SfxButton>
        <SfxButton
          variant="primary"
          size="sm"
          :disabled="!canPublish"
          :loading="acting"
          @click="approveAll"
        >
          <template #icon><CheckCircle2 :size="16" /></template>
          发布已通过候选
        </SfxButton>
      </div>
    </header>

    <div v-if="status === 'loading'" class="state">
      <LoaderCircle class="spin" :size="22" /> 正在读取候选…
    </div>
    <div v-else-if="status === 'error'" class="state state--error">
      <ShieldAlert :size="21" /> {{ error }}
      <SfxButton variant="secondary" @click="load">重试</SfxButton>
    </div>

    <SfxEmpty
      v-else-if="!all.length"
      title="暂无候选"
      description="该课程尚未产生待审核的知识点候选。上传并解析课件后，提取出的候选会出现在这里。"
    />

    <div v-else class="review__body">
      <section class="list" aria-label="候选列表">
        <div
          v-for="item in sorted"
          :key="item.id"
          class="list__item"
          :class="{ 'is-selected': String(item.id) === selectedId, 'is-needs-review': item.decision === 'needs_review' }"
          @click="selectedId = String(item.id)"
        >
          <div class="list__row">
            <span class="list__type">{{ item.target_type === 'node' ? '节点' : '关系' }}</span>
            <span class="list__label">{{ labelOf(item) }}</span>
            <SfxBadge :tone="DECISION_META[item.decision]?.tone ?? 'neutral'">
              {{ DECISION_META[item.decision]?.label ?? item.decision }}
            </SfxBadge>
          </div>
          <div class="list__meta">
            <SfxBadge :tone="sourceMeta(item).tone">{{ sourceMeta(item).label }}</SfxBadge>
            <span v-if="item.kb_matched_name" class="list__kb">
              <Tag :size="12" /> {{ item.kb_matched_name }}
            </span>
          </div>
        </div>
      </section>

      <section v-if="selected" class="detail" aria-label="候选详情">
        <div class="detail__head">
          <h2>{{ labelOf(selected) }}</h2>
          <SfxBadge :tone="DECISION_META[selected.decision]?.tone ?? 'neutral'">
            {{ DECISION_META[selected.decision]?.label ?? selected.decision }}
          </SfxBadge>
        </div>

        <dl class="detail__grid">
          <dt>类型</dt>
          <dd>{{ selected.target_type === 'node' ? '知识节点' : '语义关系' }}</dd>
          <dt>知识库对齐</dt>
          <dd>
            <SfxBadge :tone="sourceMeta(selected).tone">{{ sourceMeta(selected).label }}</SfxBadge>
            <span v-if="selected.kb_matched_name" class="detail__source">
              命中：{{ selected.kb_matched_name }}
              <span v-if="selected.kb_node_key">（{{ selected.kb_node_key }}）</span>
            </span>
          </dd>
          <dt>权威来源</dt>
          <dd>
            <template v-if="selectedContent.source">
              {{ selectedContent.source.title || '' }}
              <span v-if="selectedContent.source.authors">· {{ selectedContent.source.authors }}</span>
              <span v-if="selectedContent.source.chapter">· {{ selectedContent.source.chapter }}</span>
            </template>
            <span v-else class="detail__muted">无（超库候选，等待教师确认）</span>
          </dd>
        </dl>

        <div v-if="selectedContent.definition" class="detail__block">
          <h3>知识库定义</h3>
          <p>{{ selectedContent.definition }}</p>
        </div>

        <p v-if="actionMessage" class="detail__notice">{{ actionMessage }}</p>
        <p v-if="actionError" class="detail__notice is-error">{{ actionError }}</p>

        <div class="detail__actions">
          <template v-if="['proposed', 'needs_review'].includes(selected.decision)">
            <SfxButton
              variant="primary"
              size="sm"
              :loading="acting === String(selected.id)"
              @click="act(selected, 'accepted')"
            >
              <template #icon><Check :size="16" /></template>
              通过
            </SfxButton>
            <SfxButton
              variant="danger"
              size="sm"
              :loading="acting === String(selected.id)"
              @click="act(selected, 'rejected')"
            >
              <template #icon><X :size="16" /></template>
              驳回
            </SfxButton>
          </template>
          <span v-else class="detail__final">该候选已定论，不可回退。</span>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.review {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-6);
  gap: var(--space-5);
}
.review__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.eyebrow {
  font-size: var(--caption-size);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-secondary);
  margin: 0 0 var(--space-1);
}
.review__header h1 { margin: 0 0 var(--space-2); font-size: var(--ui-lg-size); }
.review__header p { margin: 0; color: var(--text-secondary); max-width: 56ch; }
.actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.state { display: flex; align-items: center; gap: var(--space-2); color: var(--text-secondary); padding: var(--space-8); }
.state--error { color: var(--red-700); }

.review__body { display: flex; flex: 1; min-height: 0; gap: var(--space-4); }
.list { width: 320px; min-width: 0; display: flex; flex-direction: column; gap: var(--space-2); overflow-y: auto; }
.list__item {
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.list__item.is-selected { border-color: var(--ink-300); }
.list__item.is-needs-review { border-left: 3px solid var(--red-300); }
.list__row { display: flex; align-items: center; gap: var(--space-2); }
.list__type { font-size: var(--caption-size); color: var(--text-secondary); text-transform: uppercase; }
.list__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.list__meta { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-2); flex-wrap: wrap; }
.list__kb { display: inline-flex; align-items: center; gap: 4px; font-size: var(--caption-size); color: var(--text-secondary); }

.detail { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--space-4); }
.detail__head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.detail__head h2 { margin: 0; font-size: var(--ui-lg-size); }
.detail__grid { display: grid; grid-template-columns: 96px 1fr; gap: var(--space-3) var(--space-4); margin: 0; }
.detail__grid dt { color: var(--text-secondary); font-size: var(--ui-sm-size); }
.detail__grid dd { margin: 0; display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.detail__source { display: inline-flex; align-items: center; gap: 4px; font-size: var(--ui-sm-size); }
.detail__muted { color: var(--text-secondary); }
.detail__block { border-top: 1px solid var(--border-subtle); padding-top: var(--space-3); }
.detail__block h3 { margin: 0 0 var(--space-2); font-size: var(--ui-sm-size); }
.detail__block p { margin: 0; color: var(--text-secondary); }
.detail__notice { color: var(--green-700); margin: 0; }
.detail__notice.is-error { color: var(--red-700); }
.detail__actions { display: flex; gap: var(--space-2); margin-top: auto; }
.detail__final { color: var(--text-secondary); font-size: var(--ui-sm-size); }

@media (max-width: 760px) {
  .review__body { flex-direction: column; }
  .list { width: auto; }
}
</style>
