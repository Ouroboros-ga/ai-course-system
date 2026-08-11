<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, ExternalLink, FileText, Quote, X } from 'lucide-vue-next'
import {
  confirmEvidenceSpan,
  listCourseCitations,
  listEvidence,
  listEvidenceSpans,
  rejectEvidenceSpan,
} from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)
const status = ref('loading')
const forbidden = ref(false)
const filter = ref('all')
const spans = ref([])
const formalEvidence = ref([])
const citations = ref([])
const acting = ref('')
const actionError = ref('')

const filters = [
  { value: 'all', label: '全部' },
  { value: 'candidate', label: '待确认' },
  { value: 'confirmed', label: '已转正' },
  { value: 'stale', label: '来源已更新' },
  { value: 'orphaned', label: '来源失效' },
  { value: 'rejected', label: '已拒绝' },
]

const statusMeta = {
  candidate: { label: '待教师确认', tone: 'amber' },
  confirmed: { label: '已转正', tone: 'green' },
  active: { label: '学生可读', tone: 'green' },
  stale: { label: '来源已更新', tone: 'red' },
  orphaned: { label: '来源失效', tone: 'red' },
  rejected: { label: '已拒绝', tone: 'neutral' },
}

const citationByEvidence = computed(() => new Map(
  citations.value.filter((item) => item.evidence_id).map((item) => [item.evidence_id, item]),
))

const rows = computed(() => {
  const formalIds = new Set(formalEvidence.value.map((item) => item.span_id).filter(Boolean))
  const formalRows = formalEvidence.value.map((item) => ({
    ...item,
    rowType: 'formal',
    displayStatus: item.status === 'active' ? 'confirmed' : item.status,
    citation: citationByEvidence.value.get(item.evidence_id),
  }))
  const candidateRows = spans.value
    .filter((item) => !formalIds.has(item.span_id))
    .map((item) => ({ ...item, rowType: 'span', displayStatus: item.status }))
  const all = [...formalRows, ...candidateRows]
  if (filter.value === 'all') return all
  return all.filter((item) => item.displayStatus === filter.value)
})

const counts = computed(() => ({
  candidate: spans.value.filter((item) => item.status === 'candidate').length,
  confirmed: formalEvidence.value.filter((item) => item.status === 'active').length,
  citations: citations.value.filter((item) => item.status === 'exact' || item.status === 'approximate').length,
}))

function errorIsForbidden(error) {
  return /403|权限|拒绝/.test(String(error?.message || ''))
}

async function load() {
  status.value = 'loading'
  forbidden.value = false
  actionError.value = ''
  try {
    const [spanData, evidenceData, citationData] = await Promise.all([
      listEvidenceSpans(courseId),
      listEvidence(courseId, { status: undefined }),
      listCourseCitations(courseId, { include_stale: true }),
    ])
    spans.value = Array.isArray(spanData?.items) ? spanData.items : []
    formalEvidence.value = Array.isArray(evidenceData?.items) ? evidenceData.items : []
    citations.value = Array.isArray(citationData?.items) ? citationData.items : []
    status.value = rows.value.length ? 'ready' : 'empty'
  } catch (error) {
    forbidden.value = errorIsForbidden(error)
    status.value = 'error'
  }
}

function openViewer(item) {
  if (!item.run_id) return
  router.push({
    name: 'evidence-viewer',
    params: { courseId: String(courseId), runId: item.run_id },
    query: { page: String(item.page_number || 1) },
  })
}

async function confirm(item) {
  if (acting.value || item.rowType !== 'span') return
  acting.value = item.span_id
  actionError.value = ''
  try {
    await confirmEvidenceSpan(courseId, item.span_id, {
      node_id: item.linked_node_ids?.[0] ?? undefined,
    })
    await load()
  } catch (error) {
    actionError.value = error?.message || '证据确认失败，请稍后重试。'
  } finally {
    acting.value = ''
  }
}

async function reject(item) {
  if (acting.value || item.rowType !== 'span') return
  acting.value = item.span_id
  actionError.value = ''
  try {
    await rejectEvidenceSpan(courseId, item.span_id, { reject_reason: '教师在原文治理页拒绝' })
    await load()
  } catch (error) {
    actionError.value = error?.message || '证据拒绝失败，请稍后重试。'
  } finally {
    acting.value = ''
  }
}

function formatPage(page) {
  return page == null || page === 0 ? '未定位' : `第 ${page} 页`
}

onMounted(load)
</script>

<template>
  <main class="sfx-evidence">
    <header class="sfx-evidence-head">
      <div>
        <p class="sfx-t-caption sfx-t-secondary">课程 {{ courseId }} · 来源治理</p>
        <h1 class="sfx-t-title2">Evidence / Citation 原文</h1>
        <p class="sfx-t-ui sfx-t-secondary">候选证据必须经过教师确认，才会转为学生可读引用。</p>
      </div>
      <div class="sfx-evidence-summary" aria-label="Evidence 摘要">
        <SfxBadge tone="amber">{{ counts.candidate }} 条待确认</SfxBadge>
        <SfxBadge tone="green">{{ counts.confirmed }} 条正式 Evidence</SfxBadge>
        <SfxBadge tone="ink">{{ counts.citations }} 条 Citation</SfxBadge>
      </div>
    </header>

    <nav class="sfx-evidence-filters" aria-label="Evidence 状态筛选">
      <button
        v-for="item in filters"
        :key="item.value"
        type="button"
        class="sfx-evidence-filter"
        :class="{ 'is-active': filter === item.value }"
        :aria-pressed="filter === item.value"
        @click="filter = item.value"
      >{{ item.label }}</button>
    </nav>

    <SfxSkeleton v-if="status === 'loading'" :lines="6" block />
    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '当前账号没有证据治理读取权限。' : 'Evidence 数据暂时无法读取，请重试。'"
      @retry="load"
    />
    <SfxEmpty
      v-else-if="status === 'empty' || !rows.length"
      :title="filter === 'all' ? '还没有可展示的原文证据' : '没有符合筛选条件的证据'"
      description="解析产物会先进入候选层；教师确认后，正式 Evidence 和 Citation 会出现在这里。"
    >
      <template #icon><Quote :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <template v-else>
      <p v-if="actionError" class="sfx-evidence-error" role="alert">{{ actionError }}</p>
      <div class="sfx-evidence-list" aria-live="polite">
        <article v-for="item in rows" :key="`${item.rowType}-${item.evidence_id || item.span_id}`" class="sfx-evidence-card">
          <div class="sfx-evidence-card-main">
            <div class="sfx-evidence-card-top">
              <SfxBadge :tone="statusMeta[item.displayStatus]?.tone ?? 'neutral'">
                {{ statusMeta[item.displayStatus]?.label ?? item.displayStatus }}
              </SfxBadge>
              <span class="sfx-t-caption sfx-mono">{{ item.evidence_id || item.span_id }}</span>
            </div>
            <h2 class="sfx-t-ui sfx-evidence-file"><FileText :size="16" aria-hidden="true" />{{ item.source_file || item.document_id || '未命名课件' }}</h2>
            <p class="sfx-t-caption sfx-t-secondary">{{ formatPage(item.page_number) }} · {{ item.source_type || '文档' }}</p>
            <p class="sfx-evidence-snippet">{{ item.text_snippet || '（无文本片段）' }}</p>
            <p v-if="item.citation" class="sfx-t-caption sfx-t-secondary">Citation：{{ item.citation.citation_id }} · {{ item.citation.status }}</p>
          </div>
          <div class="sfx-evidence-card-actions">
            <SfxButton v-if="item.rowType === 'span' && item.displayStatus === 'candidate'" variant="primary" size="sm" :loading="acting === item.span_id" @click="confirm(item)">
              <template #icon><Check :size="15" aria-hidden="true" /></template>确认并转正
            </SfxButton>
            <SfxButton v-if="item.rowType === 'span' && item.displayStatus === 'candidate'" variant="danger" size="sm" :disabled="Boolean(acting)" @click="reject(item)">
              <template #icon><X :size="15" aria-hidden="true" /></template>拒绝
            </SfxButton>
            <SfxButton v-if="item.run_id" variant="tertiary" size="sm" :disabled="Boolean(acting)" @click="openViewer(item)">
              <template #icon><ExternalLink :size="15" aria-hidden="true" /></template>打开原文
            </SfxButton>
          </div>
        </article>
      </div>
    </template>
  </main>
</template>

<style scoped>
.sfx-evidence { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); }
.sfx-evidence-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.sfx-evidence-summary { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.sfx-evidence-filters { display: flex; gap: var(--space-1); padding: 3px; background: var(--surface-soft); border-radius: var(--radius-md); overflow-x: auto; }
.sfx-evidence-filter { min-height: 40px; padding: 0 var(--space-3); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: var(--ui-sm-size); white-space: nowrap; }
.sfx-evidence-filter:hover, .sfx-evidence-filter:focus-visible { color: var(--ink-900); }
.sfx-evidence-filter.is-active { color: var(--ink-900); background: var(--surface-panel); box-shadow: var(--shadow-xs); }
.sfx-evidence-list { display: grid; gap: var(--space-3); }
.sfx-evidence-card { display: flex; gap: var(--space-4); justify-content: space-between; padding: var(--space-4); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-panel); box-shadow: var(--shadow-xs); }
.sfx-evidence-card-main { min-width: 0; flex: 1; }
.sfx-evidence-card-top { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.sfx-evidence-file { display: flex; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-1); }
.sfx-evidence-snippet { margin: var(--space-3) 0 0; color: var(--text-primary); line-height: 1.65; white-space: pre-wrap; }
.sfx-evidence-card-actions { display: flex; align-items: flex-start; gap: var(--space-2); flex-wrap: wrap; justify-content: flex-end; }
.sfx-evidence-error { color: var(--red-700); margin: 0; }
@media (max-width: 720px) { .sfx-evidence { padding: var(--space-4); } .sfx-evidence-card { flex-direction: column; } .sfx-evidence-card-actions { justify-content: flex-start; } }
@media (prefers-reduced-motion: reduce) { .sfx-evidence * { scroll-behavior: auto !important; transition-duration: 0.01ms !important; } }
</style>
