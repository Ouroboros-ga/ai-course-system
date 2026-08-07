<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, ClipboardList, Loader2, XCircle } from 'lucide-vue-next'
import { approveDraft, listDrafts, rejectDraft } from '@/api/question_bank.js'
import SfxButton from '@/app/ui/SfxButton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))

// 状态筛选：'' 表示全部
const statusFilter = ref('')
const statusOptions = [
  { value: '', label: '全部' },
  { value: 'draft', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'stale', label: '已过期' },
]

const drafts = ref([])
const selectedId = ref(null)
const loading = ref(false)
const message = ref('')
const messageKind = ref('') // 'success' | 'error'

const selected = computed(() => drafts.value.find((d) => d.draft_id === selectedId.value) || null)

// 审核操作本地状态
const reviewComment = ref('')
const rejectReason = ref('')
const acting = ref(false)

const difficultyLabel = { easy: '简单', medium: '中等', hard: '困难' }
const purposeLabel = {
  diagnose: '诊断',
  remediation: '补救',
  hint_withdrawal: '提示撤离',
  post_explanation: '讲解后巩固',
}

async function loadDrafts() {
  loading.value = true
  message.value = ''
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await listDrafts(courseId.value, params)
    drafts.value = data?.items || []
    // 选中项失效时回退到首条
    if (!drafts.value.find((d) => d.draft_id === selectedId.value)) {
      selectedId.value = drafts.value[0]?.draft_id || null
    }
  } catch (error) {
    message.value = error?.message || '加载草稿失败'
    messageKind.value = 'error'
  } finally {
    loading.value = false
  }
}

function selectDraft(id) {
  selectedId.value = id
  reviewComment.value = ''
  rejectReason.value = ''
}

async function approve() {
  if (!selected.value || acting.value) return
  acting.value = true
  message.value = ''
  try {
    await approveDraft(courseId.value, selected.value.draft_id, {
      review_comment: reviewComment.value.trim(),
    })
    message.value = '已审核通过，题目已进入课程题库'
    messageKind.value = 'success'
    await loadDrafts()
  } catch (error) {
    message.value = error?.response?.data?.detail?.message || error?.message || '审核通过失败'
    messageKind.value = 'error'
  } finally {
    acting.value = false
  }
}

async function reject() {
  if (!selected.value || acting.value) return
  if (rejectReason.value.trim().length < 3) {
    message.value = '拒绝时请填写理由（至少 3 个字）'
    messageKind.value = 'error'
    return
  }
  acting.value = true
  message.value = ''
  try {
    await rejectDraft(courseId.value, selected.value.draft_id, {
      review_comment: rejectReason.value.trim(),
    })
    message.value = '已拒绝该草稿'
    messageKind.value = 'success'
    rejectReason.value = ''
    reviewComment.value = ''
    await loadDrafts()
  } catch (error) {
    message.value = error?.response?.data?.detail?.message || error?.message || '拒绝失败'
    messageKind.value = 'error'
  } finally {
    acting.value = false
  }
}

function formatDimensions(dim) {
  if (!dim || typeof dim !== 'object') return ''
  return Object.entries(dim)
    .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`)
    .join('  ·  ')
}

function statusBadgeClass(status) {
  return `badge-${status || 'draft'}`
}

onMounted(loadDrafts)
watch([courseId, statusFilter], loadDrafts)
</script>

<template>
  <section class="stage">
    <header class="stage-head">
      <div class="filters">
        <button
          v-for="opt in statusOptions"
          :key="opt.value"
          type="button"
          class="chip"
          :class="{ active: statusFilter === opt.value }"
          @click="statusFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
      <p v-if="message" :class="['msg', messageKind]">{{ message }}</p>
    </header>

    <div v-if="loading && !drafts.length" class="placeholder">
      <Loader2 :size="18" /> 加载中…
    </div>

    <div v-else-if="!drafts.length" class="placeholder">
      <ClipboardList :size="28" />
      <p>教育智能体尚未生成草稿</p>
      <small>学生在教学对话中提问后，智能体会依据知识点、六维认知与提问反推信号生成题目草稿，等待您在此审核。</small>
    </div>

    <div v-else class="review-grid">
      <ul class="draft-list">
        <li
          v-for="d in drafts"
          :key="d.draft_id"
          class="draft-item"
          :class="{ active: d.draft_id === selectedId }"
          @click="selectDraft(d.draft_id)"
        >
          <div class="item-head">
            <span :class="['badge', statusBadgeClass(d.status)]">{{ d.status }}</span>
            <span class="item-diff">{{ difficultyLabel[d.difficulty] || d.difficulty }}</span>
          </div>
          <p class="item-text">{{ d.question_text || '（无题目正文）' }}</p>
          <p class="item-meta">
            <span v-if="d.generation_purpose">{{ purposeLabel[d.generation_purpose] || d.generation_purpose }}</span>
            <span v-if="d.confidence != null">置信度 {{ Number(d.confidence).toFixed(2) }}</span>
            <span>{{ d.created_at?.slice(0, 16).replace('T', ' ') || '' }}</span>
          </p>
        </li>
      </ul>

      <article v-if="selected" class="detail">
        <h2 class="detail-title">题目预览</h2>
        <p class="question-text">{{ selected.question_text || '（无题目正文）' }}</p>

        <dl class="fields">
          <div><dt>题型</dt><dd>{{ selected.question_type || '—' }}</dd></div>
          <div><dt>难度</dt><dd>{{ difficultyLabel[selected.difficulty] || selected.difficulty || '—' }}</dd></div>
          <div><dt>分类</dt><dd>{{ selected.category || '—' }}</dd></div>
          <div><dt>生成目的</dt><dd>{{ purposeLabel[selected.generation_purpose] || selected.generation_purpose || '—' }}</dd></div>
          <div><dt>置信度</dt><dd>{{ selected.confidence != null ? Number(selected.confidence).toFixed(2) : '—' }}</dd></div>
          <div><dt>来源</dt><dd>{{ selected.generated_by || '—' }}</dd></div>
        </dl>

        <div v-if="selected.options && Object.keys(selected.options).length" class="block">
          <h3>选项</h3>
          <ul class="options">
            <li v-for="(val, key) in selected.options" :key="key"><strong>{{ key }}</strong> · {{ val }}</li>
          </ul>
        </div>

        <div class="block">
          <h3>参考答案</h3>
          <p class="answer">{{ selected.answer || '（无答案）' }}</p>
        </div>

        <div v-if="selected.reason_codes && selected.reason_codes.length" class="block">
          <h3>生成理由</h3>
          <ul class="codes"><li v-for="(r, i) in selected.reason_codes" :key="i">{{ r }}</li></ul>
        </div>

        <div v-if="selected.six_dimensions && Object.keys(selected.six_dimensions).length" class="block">
          <h3>六维诊断</h3>
          <p class="dims">{{ formatDimensions(selected.six_dimensions) }}</p>
        </div>

        <div v-if="selected.cognitive_snapshot && Object.keys(selected.cognitive_snapshot).length" class="block">
          <h3>认知快照</h3>
          <p class="dims">{{ formatDimensions(selected.cognitive_snapshot) }}</p>
        </div>

        <div v-if="selected.status === 'draft' || selected.status === 'stale'" class="actions-block">
          <h3>审核操作</h3>
          <div class="action-row">
            <label>审核备注（可选）</label>
            <textarea v-model="reviewComment" rows="2" maxlength="500" placeholder="给题目留下审核备注（可选）" />
            <SfxButton variant="primary" :disabled="acting" :loading="acting" @click="approve">
              <CheckCircle2 :size="16" /> 审核通过并发布
            </SfxButton>
          </div>
          <div class="action-row reject-row">
            <label>拒绝理由（必填）</label>
            <textarea v-model="rejectReason" rows="2" maxlength="500" placeholder="说明为什么拒绝这道题" />
            <SfxButton variant="danger" :disabled="acting" @click="reject">
              <XCircle :size="16" /> 拒绝草稿
            </SfxButton>
          </div>
        </div>

        <div v-else-if="selected.review_comment" class="block">
          <h3>审核备注</h3>
          <p class="answer">{{ selected.review_comment }}</p>
          <p class="item-meta">审核人 #{{ selected.reviewed_by || '—' }} · {{ selected.reviewed_at?.slice(0, 16).replace('T', ' ') || '' }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.stage{padding:0;height:100%;overflow-y:auto;display:flex;flex-direction:column;gap:var(--space-4)}
.stage-head{display:flex;flex-direction:column;gap:var(--space-2)}
.filters{display:flex;gap:var(--space-1);flex-wrap:wrap}
.chip{height:30px;padding:0 var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-full);background:var(--surface-panel);color:var(--text-secondary);font:inherit;font-size:var(--ui-sm-size);cursor:pointer;transition:all var(--duration-fast) var(--ease-out)}
.chip:hover{border-color:var(--border-strong);color:var(--text-primary)}
.chip.active{background:var(--ink-900);border-color:var(--ink-900);color:var(--surface-panel)}
.msg{margin:0;font-size:var(--ui-sm-size)}
.msg.success{color:var(--green-700)}
.msg.error{color:var(--red-700)}
.placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--space-2);padding:var(--space-8);color:var(--text-muted);text-align:center}
.placeholder small{max-width:420px;line-height:1.6}
.review-grid{flex:1;min-height:0;display:grid;grid-template-columns:minmax(280px,380px) 1fr;gap:var(--space-4);overflow:hidden}
.draft-list{list-style:none;margin:0;padding:0;overflow-y:auto;display:flex;flex-direction:column;gap:var(--space-2)}
.draft-item{padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-panel);cursor:pointer;transition:border-color var(--duration-fast) var(--ease-out)}
.draft-item:hover{border-color:var(--border-strong)}
.draft-item.active{border-color:var(--ink-700);box-shadow:inset 3px 0 0 var(--ink-700)}
.item-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-1)}
.badge{font-size:11px;font-weight:600;padding:2px var(--space-2);border-radius:var(--radius-full);text-transform:uppercase;letter-spacing:.04em}
.badge-draft{background:var(--amber-100);color:var(--amber-800)}
.badge-approved{background:var(--green-100);color:var(--green-800)}
.badge-rejected{background:var(--red-100);color:var(--red-700)}
.badge-stale{background:var(--ink-100);color:var(--text-muted)}
.item-diff{font-size:var(--caption-size);color:var(--text-muted)}
.item-text{margin:0 0 var(--space-1);font-size:var(--ui-sm-size);line-height:1.5;color:var(--text-primary);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.item-meta{margin:0;display:flex;gap:var(--space-3);flex-wrap:wrap;font-size:11px;color:var(--text-muted)}
.detail{overflow-y:auto;padding:var(--space-4);border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-panel);display:flex;flex-direction:column;gap:var(--space-3)}
.detail-title{margin:0;font-size:var(--ui-md-size);font-weight:650;color:var(--text-primary)}
.question-text{margin:0;padding:var(--space-3);background:var(--surface-soft);border-radius:var(--radius-sm);font-size:var(--ui-md-size);line-height:1.6;color:var(--text-primary);white-space:pre-wrap}
.fields{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:var(--space-2);margin:0}
.fields div{display:flex;flex-direction:column;gap:2px}
.fields dt{font-size:11px;color:var(--text-muted);font-weight:600}
.fields dd{margin:0;font-size:var(--ui-sm-size);color:var(--text-primary)}
.block{display:flex;flex-direction:column;gap:var(--space-1)}
.block h3{margin:0;font-size:var(--ui-sm-size);font-weight:650;color:var(--text-secondary)}
.options,.codes{margin:0;padding-left:var(--space-4);font-size:var(--ui-sm-size);line-height:1.6;color:var(--text-primary)}
.answer{margin:0;font-size:var(--ui-sm-size);line-height:1.6;color:var(--text-primary);white-space:pre-wrap}
.dims{margin:0;font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:var(--caption-size);color:var(--text-secondary);line-height:1.6}
.actions-block{margin-top:var(--space-2);padding-top:var(--space-3);border-top:1px solid var(--border-default);display:flex;flex-direction:column;gap:var(--space-3)}
.action-row{display:flex;flex-direction:column;gap:var(--space-2)}
.action-row label{font-size:var(--caption-size);font-weight:600;color:var(--text-secondary)}
.action-row textarea{box-sizing:border-box;width:100%;padding:var(--space-2);border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--surface-soft);font:inherit;font-size:var(--ui-sm-size);resize:vertical}
.reject-row{padding-top:var(--space-2);border-top:1px dashed var(--border-default)}
@media(max-width:900px){.review-grid{grid-template-columns:1fr;overflow:visible}.draft-list{max-height:300px}}
</style>
