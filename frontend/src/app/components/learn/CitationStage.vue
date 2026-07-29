<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ChevronDown, FileWarning, MessageSquareWarning } from 'lucide-vue-next'
import {
  fetchCitations,
  fetchCourseCitations,
  fetchCourseEvidenceSpans,
  fetchEvidenceSpans,
  fetchPageImage,
  fetchProtectedImageUrl,
  validateCitations,
} from '@/api/evidence.js'
import {
  indexSpansByEvidenceRef,
  mapCitationStatus,
} from '@/app/lib/citationStatus.js'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * CITATION 原文引用舞台（page-design §12.9 / §6.8）。
 * 数据全部来自真实 V2 Evidence 端点：
 *  - 学习页引用/证据来自课程级 graph/document-parse API；独立 Evidence Viewer
 *    仍可使用 evidence-v2 的文档级能力；
 *  - 引用状态由 mapCitationStatus 按后端真实信号（valid/stale/abstain）推导，
 *    不推测为通过（修正：旧版假设 {key,status} 字段，与后端 {evidence_ref,valid} 不符）；
 *  - documentId 缺失 / 403 / 503 → 显式状态，绝不伪造引用；
 *  - admin-only 的 evidence-v2 不作为学习页依赖，权限/空数据均显式呈现。
 */
const props = defineProps({
  courseId: { type: [String, Number], default: null },
  documentId: { type: [String, Number], default: null },
  preview: { type: Boolean, default: false },
})

const emit = defineEmits(['exit'])

const status = ref('loading')
const citations = ref([])
const spans = ref([])
const validateDetails = ref([])
const validateMeta = ref({ abstain: false, abstainReason: null })
const expandedKey = ref(null)
const pageImages = ref({})

const spansByRef = computed(() => indexSpansByEvidenceRef(spans.value))
const staleCount = computed(() => spans.value.filter((s) => s.status === 'stale').length)
const verifiedCount = computed(() =>
  citations.value.filter((c) => mapCitationStatus(c, validateDetails.value, spansByRef.value, validateMeta.value).tone === 'green').length
)

function statusFor(citation) {
  return mapCitationStatus(citation, validateDetails.value, spansByRef.value, validateMeta.value)
}

function mapError(e) {
  const msg = String(e?.message || '')
  if (/403|401|forbidden|权限|拒绝/.test(msg)) return 'forbidden'
  if (/503|unavailable|未配置|not configured/.test(msg)) return 'unavailable'
  return 'error'
}

async function load() {
  if ((props.courseId == null || props.courseId === '') && (props.documentId == null || props.documentId === '')) {
    status.value = 'no-document'
    return
  }
  status.value = 'loading'
  expandedKey.value = null
  pageImages.value = {}
  try {
    // The learning workspace is course-scoped.  The document-scoped
    // evidence-v2 routes are an admin-only shadow API and would return 401/403
    // for ordinary teachers/students.  Keep the old path only for the
    // standalone evidence viewer, which passes documentId without courseId.
    const citationList = props.courseId != null && props.courseId !== ''
      ? await fetchCourseCitations(props.courseId, props.preview ? { include_stale: true } : {})
      : await fetchCitations(props.documentId)
    let spanList = []
    if (props.courseId != null && props.courseId !== '' && props.preview) {
      try {
        spanList = await fetchCourseEvidenceSpans(props.courseId)
      } catch {
        // Teacher preview may still show formal citations when candidate-span
        // review is unavailable or has not been provisioned yet.
        spanList = []
      }
    } else if (props.courseId == null || props.courseId === '') {
      spanList = await fetchEvidenceSpans(props.documentId)
    }
    citations.value = citationList
    spans.value = spanList

    // 真实校验引用状态（后端返回 details:[{evidence_ref,valid}] + abstain）
    if (citationList.length && (props.courseId == null || props.courseId === '')) {
      try {
        const result = await validateCitations(props.documentId, citationList)
        validateDetails.value = Array.isArray(result?.details) ? result.details : []
        validateMeta.value = {
          abstain: Boolean(result?.abstain),
          abstainReason: result?.abstainReason ?? null,
        }
      } catch {
        // 校验失败：保留待校验，不推测为通过
        validateDetails.value = []
        validateMeta.value = { abstain: false, abstainReason: null }
      }
    } else {
      validateDetails.value = []
      validateMeta.value = { abstain: false, abstainReason: null }
    }

    status.value = citationList.length || spanList.length ? 'ready' : 'empty'
  } catch (e) {
    status.value = mapError(e)
  }
}

async function toggleCitation(citation) {
  const key = citation.key ?? `no-evidence-${citation.statement.slice(0, 12)}`
  expandedKey.value = expandedKey.value === key ? null : key

  const page = citation.pageOrSlide
  if (expandedKey.value && page != null && !pageImages.value[page]) {
    pageImages.value = { ...pageImages.value, [page]: { status: 'loading', url: '' } }
    try {
      const renderUrl = citation.metadata?.renderUrl
      const imageUrl = renderUrl
        ? await fetchProtectedImageUrl(renderUrl)
        : (await fetchPageImage(props.documentId, page))?.imageUrl
      if (!imageUrl) throw new Error('empty image url')
      pageImages.value = { ...pageImages.value, [page]: { status: 'ready', url: imageUrl } }
    } catch {
      pageImages.value = { ...pageImages.value, [page]: { status: 'error', url: '' } }
    }
  }
}

// A7 修复：documentId 变化时重新加载（切换课程场景）
watch(() => [props.courseId, props.documentId, props.preview], () => load())

onMounted(load)
</script>

<template>
  <div class="sfx-citation">
    <header class="sfx-citation-header">
      <button type="button" class="sfx-citation-back" @click="emit('exit')">
        <ArrowLeft :size="16" /> 返回课程
      </button>
      <div class="sfx-citation-headtext">
        <h2 class="sfx-t-title3">
          原文引用
          <SfxCapabilityTag level="experimental" />
        </h2>
        <span v-if="status === 'ready'" class="sfx-t-caption">
          {{ citations.length }} 条引用 · {{ spans.length }} 条证据锚点<template v-if="staleCount"> · {{ staleCount }} 条来源已更新</template><template v-if="verifiedCount"> · {{ verifiedCount }} 条已校验</template><span v-if="validateMeta.abstain" class="sfx-citation-abstain"> · 校验受限：{{ validateMeta.abstainReason || '后端无法校验' }}</span>
        </span>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" />

    <SfxEmpty
      v-else-if="status === 'no-document'"
      title="本课程暂未关联原文引用数据"
      description="课程详情没有返回可核查的证据文档，因此这里不展示任何引用。系统不会用推测内容填充原文引用。"
    >
      <template #icon><FileWarning :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <SfxError
      v-else-if="status === 'forbidden'"
      variant="forbidden"
      description="原文引用数据当前仅对有权限的账号开放。你可以继续正常学习，或联系教师/管理员确认访问权限。"
      @retry="load"
    />

    <SfxError
      v-else-if="status === 'unavailable'"
      variant="unavailable"
      @retry="load"
    />

    <SfxError v-else-if="status === 'error'" @retry="load" />

    <SfxEmpty
      v-else-if="status === 'empty'"
      title="当前课程还没有可用的原文引用"
      description="引用数据可能尚未建设完成。可以向教师反馈缺失引用，我们会保留这条真实状态而不是伪造来源。"
    >
      <template #icon><MessageSquareWarning :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <ul v-else class="sfx-citation-list">
      <li v-for="(citation, index) in citations" :key="citation.key ?? index" class="sfx-citation-item">
        <button type="button" class="sfx-citation-row"
                :aria-expanded="expandedKey === (citation.key ?? `no-evidence-${citation.statement.slice(0, 12)}`)"
                @click="toggleCitation(citation)">
          <span class="sfx-citation-statement sfx-t-ui">{{ citation.statement }}</span>
          <span class="sfx-citation-row-meta">
            <span class="sfx-cap-inline" :class="`tone-${statusFor(citation).tone}`">
              {{ statusFor(citation).label }}
            </span>
            <span v-if="citation.pageOrSlide != null" class="sfx-t-caption">p.{{ citation.pageOrSlide }}</span>
            <span v-if="citation.confidence != null" class="sfx-t-caption">{{ Math.round(citation.confidence * 100) }}%</span>
            <ChevronDown :size="15" class="sfx-citation-chevron"
                         :class="{ 'is-open': expandedKey === (citation.key ?? `no-evidence-${citation.statement.slice(0, 12)}`) }" />
          </span>
        </button>

        <div v-if="expandedKey === (citation.key ?? `no-evidence-${citation.statement.slice(0, 12)}`)"
             class="sfx-citation-detail">
          <!-- §6.8 CitationBlock：来源类型 / 文件名 / 页码 / 引用片段 / 关联说明 / 查看原文 -->
          <div class="sfx-citation-quote">
            <dl class="sfx-citation-facts">
              <div class="sfx-citation-fact">
                <dt class="sfx-t-caption">来源</dt>
                <dd class="sfx-t-sm">课程资料</dd>
              </div>
              <div class="sfx-citation-fact" v-if="citation.key">
                <dt class="sfx-t-caption">引用编号</dt>
                <dd class="sfx-t-sm sfx-mono">{{ citation.key }}</dd>
              </div>
              <div class="sfx-citation-fact" v-if="citation.pageOrSlide != null">
                <dt class="sfx-t-caption">位置</dt>
                <dd class="sfx-t-sm">第 {{ citation.pageOrSlide }} 页</dd>
              </div>
              <div class="sfx-citation-fact">
                <dt class="sfx-t-caption">关联</dt>
                <dd class="sfx-t-sm">关联当前课程回答</dd>
              </div>
            </dl>
            <p v-if="statusFor(citation).reason" class="sfx-citation-reason sfx-t-caption">
              校验说明：{{ statusFor(citation).reason }}
            </p>
          </div>

          <template v-if="citation.pageOrSlide != null">
            <div v-if="pageImages[citation.pageOrSlide]?.status === 'loading'" class="sfx-citation-pageimg">
              <SfxSkeleton :lines="2" block />
            </div>
            <div v-else-if="pageImages[citation.pageOrSlide]?.status === 'ready'" class="sfx-citation-pageimg">
              <img :src="pageImages[citation.pageOrSlide].url"
                   :alt="`原文第 ${citation.pageOrSlide} 页`"
                   class="sfx-citation-pageimg-img" />
              <span class="sfx-t-caption">原文第 {{ citation.pageOrSlide }} 页</span>
            </div>
            <p v-else-if="pageImages[citation.pageOrSlide]?.status === 'error'" class="sfx-t-caption sfx-citation-imgerr">
              原文页图暂时无法加载，引用文本仍可核查。
            </p>
          </template>
        </div>
      </li>
    </ul>

    <!-- §12.9 无原文时提供「向教师反馈缺失引用」入口（诚实：反馈端点未建，仅说明） -->
    <footer v-if="status === 'empty' || status === 'no-document'" class="sfx-citation-feedback">
      <p class="sfx-t-caption">向教师反馈缺失引用（反馈通道建设中，暂记录本地）</p>
    </footer>
  </div>
</template>

<style scoped>
.sfx-citation {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-canvas);
  overflow-y: auto;
  padding: var(--space-4) var(--space-6) var(--space-10);
  animation: sfx-citation-in var(--duration-normal) var(--ease-out);
}

@keyframes sfx-citation-in {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.sfx-citation-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.sfx-citation-back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: 500;
}
.sfx-citation-back:hover { background: var(--surface-cool); color: var(--ink-700); }

.sfx-citation-headtext {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sfx-citation-headtext h2 {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-citation-abstain { color: var(--amber-700); }

.sfx-citation-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 860px;
}

.sfx-citation-item {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.sfx-citation-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  text-align: left;
}

.sfx-citation-row:hover { background: var(--surface-cool); }

.sfx-citation-statement { color: var(--text-primary); }

.sfx-citation-row-meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}

/* 内联状态标签（图标+文字+颜色三重编码，§4.7） */
.sfx-cap-inline {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  font-weight: 500;
  white-space: nowrap;
}
.sfx-cap-inline::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
}
.sfx-cap-inline.tone-green { background: var(--green-100); color: var(--green-700); }
.sfx-cap-inline.tone-amber { background: var(--amber-100); color: var(--amber-700); }
.sfx-cap-inline.tone-red { background: var(--red-100); color: var(--red-700); }
.sfx-cap-inline.tone-neutral { background: var(--surface-cool); color: var(--text-secondary); }

.sfx-citation-chevron { color: var(--text-muted); transition: transform var(--duration-fast) var(--ease-out); }
.sfx-citation-chevron.is-open { transform: rotate(180deg); }

.sfx-citation-detail {
  border-top: 1px solid var(--border-subtle);
  padding: var(--space-4) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 原文引用块（design.md 4.5）：左 3px 墨蓝边，仅右侧圆角 */
.sfx-citation-quote {
  background: var(--surface-cool);
  border-left: 3px solid var(--ink-500);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-citation-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.sfx-citation-fact dt { margin-bottom: 2px; }
.sfx-citation-fact dd { margin: 0; color: var(--text-primary); }

.sfx-citation-reason { color: var(--amber-700); }

.sfx-citation-pageimg {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-citation-pageimg-img {
  max-width: 100%;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.sfx-citation-imgerr { color: var(--amber-700); }

.sfx-citation-feedback {
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  text-align: center;
}
</style>
