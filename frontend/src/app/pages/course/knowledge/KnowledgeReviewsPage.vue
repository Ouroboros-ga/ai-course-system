<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ListChecks } from 'lucide-vue-next'
import { listCandidates, transitionReview } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 知识空间 · 候选审核（page-design §15.4，仅教师）。
 * 数据源（available）：GET /graph/course/{id}/candidates（待治理候选）、
 * POST /graph/course/{id}/reviews/{rid}/transition（接受/驳回/挂起）。
 * 纪律：accepted/rejected 为终态不可回退；禁止「一键全部通过」成为主操作（§15.4）。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading')
const forbidden = ref(false)
const items = ref([])
const selectedId = ref(null)
const comment = ref('')
const acting = ref(false)
const actionError = ref('')

const selected = computed(() => items.value.find((r) => r.id === selectedId.value) ?? null)

const decisionMeta = {
  proposed: { label: '待审核', tone: 'amber' },
  needs_review: { label: '需复核', tone: 'amber' },
  accepted: { label: '已接受', tone: 'green' },
  rejected: { label: '已驳回', tone: 'red' },
}

const targetTypeLabel = { node: '知识点', relation: '知识关系' }

const isTerminal = computed(() => ['accepted', 'rejected'].includes(selected.value?.decision))

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await listCandidates(courseId)
    items.value = Array.isArray(data?.items) ? data.items : []
    status.value = 'ready'
    if (items.value.length && !selectedId.value) selectedId.value = items.value[0].id
    if (!items.value.length) selectedId.value = null
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
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
  } catch (e) {
    actionError.value = e?.message || '操作失败，请稍后重试。'
  } finally {
    acting.value = false
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="sfx-reviews">
    <header class="sfx-reviews-head">
      <div>
        <h1 class="sfx-t-title2">候选审核</h1>
        <p class="sfx-t-ui sfx-t-secondary">审核 AI 提出的节点与关系候选；接受/驳回为终态，全程可追溯</p>
      </div>
      <SfxBadge v-if="items.length" tone="amber">{{ items.length }} 条待处理</SfxBadge>
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
      description="AI 从课程资料中解析出的节点与关系候选，会在这里等待教师逐条确认。"
    >
      <template #icon><ListChecks :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <div v-else class="sfx-reviews-grid">
      <!-- 左：候选列表 -->
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
          <span class="sfx-t-ui sfx-reviews-item-target">{{ review.target_id }}</span>
          <span class="sfx-t-caption">{{ formatTime(review.created_at) }}</span>
        </button>
      </aside>

      <!-- 中右：候选详情与操作 -->
      <section v-if="selected" class="sfx-reviews-detail" aria-label="候选详情">
        <h2 class="sfx-t-title3">候选详情</h2>

        <dl class="sfx-desc">
          <dt>候选类型</dt><dd>{{ targetTypeLabel[selected.target_type] ?? selected.target_type }}</dd>
          <dt>目标标识</dt><dd class="sfx-mono">{{ selected.target_id }}</dd>
          <dt>当前状态</dt>
          <dd>
            <SfxBadge :tone="decisionMeta[selected.decision]?.tone ?? 'neutral'">
              {{ decisionMeta[selected.decision]?.label ?? selected.decision }}
            </SfxBadge>
          </dd>
          <dt>关联快照</dt><dd class="sfx-mono">{{ selected.snapshot_id || '—' }}</dd>
          <dt>关联证据</dt>
          <dd>{{ selected.evidence_ids?.length ? `${selected.evidence_ids.length} 条` : '无关联证据' }}</dd>
          <dt>审核人</dt><dd>{{ selected.reviewer ?? '—' }}</dd>
          <dt>审核意见</dt><dd>{{ selected.review_comment || '—' }}</dd>
        </dl>

        <template v-if="!isTerminal">
          <div class="sfx-reviews-comment">
            <label class="sfx-t-caption" for="sfx-review-comment">审核意见（可选）</label>
            <textarea
              id="sfx-review-comment"
              v-model="comment"
              class="sfx-textarea"
              rows="3"
              placeholder="记录接受或驳回的理由，保留在审核轨迹中"
            ></textarea>
          </div>

          <p v-if="actionError" class="sfx-reviews-error sfx-t-ui" role="alert">{{ actionError }}</p>

          <div class="sfx-reviews-actions">
            <SfxButton variant="primary" size="sm" :loading="acting" @click="act('accepted')">接受</SfxButton>
            <SfxButton variant="danger" size="sm" :disabled="acting" @click="act('rejected')">驳回</SfxButton>
            <SfxButton
              v-if="selected.decision === 'proposed'"
              variant="tertiary"
              size="sm"
              :disabled="acting"
              @click="act('needs_review')"
            >暂缓（标记需复核）</SfxButton>
          </div>
          <p class="sfx-t-caption sfx-t-muted">
            接受或驳回后不可回退；「一键全部通过」按设计纪律不提供。
          </p>
        </template>
        <p v-else class="sfx-t-ui sfx-t-secondary">该候选已终态（{{ decisionMeta[selected.decision]?.label }}），不可再变更。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.sfx-reviews {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.sfx-reviews-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-reviews-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: var(--space-4);
  align-items: start;
}

.sfx-reviews-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 68vh;
  overflow-y: auto;
}

.sfx-reviews-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  text-align: left;
  cursor: pointer;
}

.sfx-reviews-item:hover { border-color: var(--border-strong); }
.sfx-reviews-item.is-active { border-color: var(--ink-500); background: var(--ink-100); }

.sfx-reviews-item-top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-reviews-item-target { color: var(--text-primary); }

.sfx-reviews-detail {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-reviews-comment {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-reviews-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.sfx-reviews-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

@media (max-width: 900px) {
  .sfx-reviews-grid { grid-template-columns: 1fr; }
}
</style>
