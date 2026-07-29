<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, ListChecks, Link2, Network, Unlink2 } from 'lucide-vue-next'
import { listCandidates, transitionReview } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading')
const forbidden = ref(false)
const items = ref([])
const selectedId = ref(null)
const comment = ref('')
const acting = ref(false)
const actionError = ref('')

const selected = computed(() => items.value.find((item) => item.id === selectedId.value) ?? null)
const nodeCount = computed(() => items.value.filter((item) => item.target_type === 'node').length)
const relationCount = computed(() => items.value.filter((item) => item.target_type === 'relation').length)

const decisionMeta = {
  proposed: { label: '待审核', tone: 'amber' },
  needs_review: { label: '需复核', tone: 'amber' },
  accepted: { label: '已接受', tone: 'green' },
  rejected: { label: '已驳回', tone: 'red' },
}

const targetTypeLabel = { node: '知识节点', relation: '知识关系' }
const isTerminal = computed(() => ['accepted', 'rejected'].includes(selected.value?.decision))
const selectedContent = computed(() => selected.value?.target_content ?? {})

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await listCandidates(courseId)
    items.value = Array.isArray(data?.items) ? data.items : []
    status.value = 'ready'
    if (items.value.length && !items.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = items.value[0].id
    }
    if (!items.value.length) selectedId.value = null
  } catch (error) {
    forbidden.value = /403|权限|拒绝/.test(String(error?.message || ''))
    status.value = 'error'
  }
}

function select(review) {
  selectedId.value = review.id
  comment.value = ''
  actionError.value = ''
}

async function act(decision) {
  if (!selected.value || acting.value) return
  acting.value = true
  actionError.value = ''
  try {
    await transitionReview(courseId, selected.value.id, {
      new_decision: decision,
      review_comment: comment.value.trim() || undefined,
    })
    await load()
  } catch (error) {
    actionError.value = error?.message || '操作失败，请稍后重试。'
  } finally {
    acting.value = false
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function displayTitle(review) {
  return review.target_content?.title || review.target_content?.label || review.target_id
}

function relationEndpoint(review, key) {
  const value = review.target_content?.[key]
  return value || '未解析'
}

onMounted(load)
</script>

<template>
  <div class="sfx-reviews">
    <header class="sfx-reviews-head">
      <div>
        <h1 class="sfx-t-title2">候选审核</h1>
        <p class="sfx-t-ui sfx-t-secondary">
          解析候选已桥接为课程正式节点身份；教师审核只改变治理状态，不会自动发布学生可见图谱。
        </p>
      </div>
      <div class="sfx-reviews-summary" aria-label="候选统计">
        <SfxBadge tone="ink"><Network :size="13" aria-hidden="true" />{{ nodeCount }} 个节点</SfxBadge>
        <SfxBadge tone="ink"><Link2 :size="13" aria-hidden="true" />{{ relationCount }} 条关系</SfxBadge>
        <SfxBadge v-if="items.length" tone="amber">{{ items.length }} 条待处理</SfxBadge>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" block />

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '候选审核需要课程的 knowledge.review 权限（教师）。' : '候选列表暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="!items.length"
      title="没有待审核的候选"
      description="解析成功后，节点和关系候选会自动进入这里；审核接受后才能进入后续发布流程。"
    >
      <template #icon><ListChecks :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <div v-else class="sfx-reviews-grid">
      <aside class="sfx-reviews-list" aria-label="候选列表">
        <button
          v-for="review in items"
          :key="review.id"
          type="button"
          class="sfx-reviews-item"
          :class="{ 'is-active': review.id === selectedId }"
          @click="select(review)"
        >
          <div class="sfx-reviews-item-top">
            <SfxBadge tone="ink">{{ targetTypeLabel[review.target_type] ?? review.target_type }}</SfxBadge>
            <SfxBadge :tone="decisionMeta[review.decision]?.tone ?? 'neutral'">
              {{ decisionMeta[review.decision]?.label ?? review.decision }}
            </SfxBadge>
          </div>
          <strong class="sfx-t-ui sfx-reviews-item-title">{{ displayTitle(review) }}</strong>
          <span class="sfx-t-caption sfx-mono">{{ review.target_id }}</span>
          <span class="sfx-t-caption">{{ formatTime(review.created_at) }}</span>
        </button>
      </aside>

      <section v-if="selected" class="sfx-reviews-detail" aria-label="候选详情">
        <div class="sfx-reviews-detail-head">
          <div>
            <p class="sfx-t-caption sfx-t-secondary">{{ targetTypeLabel[selected.target_type] }}</p>
            <h2 class="sfx-t-title3">{{ displayTitle(selected) }}</h2>
          </div>
          <SfxBadge :tone="decisionMeta[selected.decision]?.tone ?? 'neutral'">
            {{ decisionMeta[selected.decision]?.label ?? selected.decision }}
          </SfxBadge>
        </div>

        <dl class="sfx-desc">
          <dt>正式节点身份</dt>
          <dd v-if="selected.target_type === 'node'" class="sfx-mono">{{ selected.target_id }}</dd>
          <dd v-else class="sfx-mono">{{ selectedContent.id || selected.target_id }}</dd>
          <dt v-if="selected.target_type === 'node'">身份主键</dt>
          <dd v-if="selected.target_type === 'node'">{{ selected.identity_node_id || '—' }}</dd>
          <dt v-if="selected.target_type === 'relation'">关系端点</dt>
          <dd v-if="selected.target_type === 'relation'" class="sfx-relation-endpoints">
            <span class="sfx-mono">{{ relationEndpoint(selected, 'source') }}</span>
            <span aria-hidden="true">→</span>
            <span class="sfx-mono">{{ relationEndpoint(selected, 'target') }}</span>
          </dd>
          <dt>候选批次</dt><dd class="sfx-mono">{{ selected.candidate_batch_id || '手工治理' }}</dd>
          <dt>解析候选 ID</dt><dd class="sfx-mono">{{ selected.candidate_id || selected.target_id }}</dd>
          <dt>来源锚点</dt><dd>{{ selectedContent.anchor_ids?.length || 0 }} 个</dd>
          <dt>置信度</dt><dd>{{ selectedContent.confidence ?? '—' }}</dd>
          <dt>审核意见</dt><dd>{{ selected.review_comment || '—' }}</dd>
        </dl>

        <div v-if="selected.target_type === 'relation' && selectedContent.unresolved_endpoint" class="sfx-reviews-warning" role="alert">
          <Unlink2 :size="17" aria-hidden="true" />
          <span>关系端点尚未解析到正式节点，当前只能标记为需复核。</span>
        </div>

        <template v-if="!isTerminal">
          <div class="sfx-reviews-comment">
            <label class="sfx-t-caption" for="sfx-review-comment">审核意见（可选）</label>
            <textarea
              id="sfx-review-comment"
              v-model="comment"
              class="sfx-textarea"
              rows="3"
              placeholder="记录接受、驳回或挂起的理由，保留在审核轨迹中。"
            />
          </div>

          <p v-if="actionError" class="sfx-reviews-error sfx-t-ui" role="alert">{{ actionError }}</p>

          <div class="sfx-reviews-actions">
            <SfxButton variant="primary" size="sm" :loading="acting" @click="act('accepted')">
              <template #icon><CheckCircle2 :size="16" aria-hidden="true" /></template>
              接受
            </SfxButton>
            <SfxButton variant="danger" size="sm" :disabled="acting" @click="act('rejected')">驳回</SfxButton>
            <SfxButton
              v-if="selected.decision === 'proposed'"
              variant="tertiary"
              size="sm"
              :disabled="acting"
              @click="act('needs_review')"
            >暂缓，标记需复核</SfxButton>
          </div>
          <p class="sfx-t-caption sfx-t-muted">接受或驳回后不可回退；本页不会提供“一键全部通过”。</p>
        </template>
        <p v-else class="sfx-t-ui sfx-t-secondary">该候选已终态处理，保留审核记录但不能再次变更。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.sfx-reviews { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); }
.sfx-reviews-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.sfx-reviews-summary { display: flex; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
.sfx-reviews-summary :deep(.sfx-badge) { gap: 5px; }
.sfx-reviews-grid { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.sfx-reviews-list { display: flex; flex-direction: column; gap: var(--space-2); max-height: 68vh; overflow-y: auto; }
.sfx-reviews-item { display: flex; flex-direction: column; gap: var(--space-1); min-height: 88px; padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); text-align: left; cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out); }
.sfx-reviews-item:hover, .sfx-reviews-item:focus-visible { border-color: var(--border-strong); }
.sfx-reviews-item:focus-visible { outline: 3px solid var(--ink-300); outline-offset: 2px; }
.sfx-reviews-item.is-active { border-color: var(--ink-500); background: var(--ink-100); }
.sfx-reviews-item-top { display: flex; align-items: center; gap: var(--space-2); }
.sfx-reviews-item-title { color: var(--text-primary); line-height: 1.45; }
.sfx-reviews-detail { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); background: var(--surface-panel); border: 1px solid var(--border-default); border-radius: var(--radius-lg); }
.sfx-reviews-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.sfx-relation-endpoints { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.sfx-reviews-warning { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--amber-300); border-radius: var(--radius-md); background: var(--amber-100); color: var(--amber-700); }
.sfx-reviews-comment { display: flex; flex-direction: column; gap: var(--space-2); }
.sfx-reviews-error { padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--red-100); color: var(--red-700); }
.sfx-reviews-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
@media (max-width: 900px) { .sfx-reviews-grid { grid-template-columns: 1fr; } .sfx-reviews-head { align-items: flex-start; flex-direction: column; } .sfx-reviews-summary { justify-content: flex-start; } }
@media (prefers-reduced-motion: reduce) { .sfx-reviews-item { transition: none; } }
</style>
