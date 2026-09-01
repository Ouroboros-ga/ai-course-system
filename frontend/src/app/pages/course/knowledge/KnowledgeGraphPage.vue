<script setup>
/**
 * 知识空间 · 结构视图（批次3，page-design §15.2）。
 *
 * 整合三块学生侧能力，提供统一入口：
 * - StudentGraphPanel：已发布图谱快照 + 一跳先修/后继 + 跳转锚点；
 * - CognitiveDashboard：六维认知状态（保留 null 语义，不武断判弱）；
 * - RecommendationCard 列表：基于策略版本的推荐，支持消费/锁定状态。
 *
 * 路由：/app/course/:courseId/build/knowledge/graph/:nodeId?
 * - courseId 必填；
 * - nodeId 可选，存在时聚焦到该知识点并拉取相邻关系。
 *
 * 权限：依赖 CourseLayout 提供的 courseContext（allowed/capabilities/analyticsEligible）。
 * 角色分流（P1 修复）：
 * - 学生（analytics_eligible=true）：显示自己的认知仪表盘 + 推荐卡 + 采纳操作；
 * - 教师/助教/观察者（analytics_eligible=false）：仅查看已发布图谱快照，
 *   隐藏学生私有认知与「采纳推荐」操作（后端 owner analytics_excluded=True，
 *   查询非学生身份会 422）。如需查看某位学生的认知，应走专门的「学生认知查看」流程。
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Eye, Lightbulb, LoaderCircle, TriangleAlert, ShieldCheck } from 'lucide-vue-next'
import StudentGraphPanel from '@/features/student-graph/StudentGraphPanel.vue'
import CognitiveDashboard from '@/components/cognitive/CognitiveDashboard.vue'
import RecommendationCard from '@/features/student-learning/components/RecommendationCard.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxError from '@/app/ui/SfxError.vue'
import { useCounterStore } from '@/stores/counter.js'
import {
  consumeRecommendation,
  getRecommendations,
} from '@/api/cognitive.js'
import { getKnowledgeBundleStatus } from '@/api/graph.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()
const { courseId, courseRole, analyticsEligible } = inject('courseContext')

const nodeId = computed(() =>
  route.params.nodeId != null ? String(route.params.nodeId) : null,
)

// 角色分流：仅 analytics_eligible=true（学生且未 excluded）才加载学生私有认知/推荐。
// owner/teacher/teaching_assistant/observer 的 analytics_eligible 均为 false，
// 传自己的 user_id 给 /state?student_id= 会触发 422（course_access_service.py:192）。
const isPreview = computed(() => !analyticsEligible.value)

// 学生视角下才解析当前用户 ID 作为 studentId；预览视角下保持 null，避免误传。
const studentId = computed(() =>
  analyticsEligible.value ? (counter.userData?.id ?? null) : null,
)

// 预览视角的角色标签（用于占位提示文案）
const previewRoleLabel = computed(() => {
  switch (courseRole.value) {
    case 'owner': return '课程所有者'
    case 'teacher': return '教师'
    case 'teaching_assistant': return '助教'
    case 'observer': return '观察者'
    default: return '教师'
  }
})

// 学生视角下 studentId 缺失才算异常（未登录或身份解析失败）；预览视角不需要 studentId。
const missingStudentIdentity = computed(() => !isPreview.value && studentId.value == null)

// 推荐列表
const recommendations = ref([])
const recommendationsStatus = ref('idle') // idle | loading | ready | empty | error
const recommendationsError = ref('')
const consumingId = ref('')
const consumedIds = ref(new Set())

async function loadRecommendations() {
  // 预览视角（教师/助教/观察者）不加载学生私有推荐：后端 analytics_excluded
  // 会拒绝，且预览不应消费学生专属行动。
  if (isPreview.value || studentId.value == null) {
    recommendationsStatus.value = 'idle'
    recommendations.value = []
    return
  }
  recommendationsStatus.value = 'loading'
  recommendationsError.value = ''
  try {
    const res = await getRecommendations(courseId.value)
    const items = Array.isArray(res) ? res : (res?.items ?? [])
    recommendations.value = items
    recommendationsStatus.value = items.length ? 'ready' : 'empty'
  } catch (err) {
    recommendationsStatus.value = 'error'
    recommendationsError.value = err?.message || '推荐加载失败'
  }
}

async function handleConsume(recommendation) {
  if (!recommendation?.recommendation_id || consumingId.value) return
  consumingId.value = recommendation.recommendation_id
  try {
    await consumeRecommendation(recommendation.recommendation_id, {
      action: 'accepted',
    })
    consumedIds.value = new Set([
      ...consumedIds.value,
      recommendation.recommendation_id,
    ])
  } catch (err) {
    recommendationsError.value = err?.message || '推荐消费失败'
  } finally {
    consumingId.value = ''
  }
}

function handleJumpNode(node) {
  // 跳转到先修/后继节点：更新路由 nodeId，触发 StudentGraphPanel 重新加载相邻
  if (node?.id == null) return
  router.push(`/app/course/${courseId.value}/build/knowledge/graph/${node.id}`)
}

function handleReturnAnchor() {
  // 返回课程概览（无锚点时回退到概览）
  router.push(`/app/course/${courseId.value}/overview`)
}

// 教师预览模式：加载 refinement 质量报告（解决"refinement 质量报告尚未在教师页面完整展示"遗留）
const refinementStatus = ref('idle') // idle | loading | ready | error
const refinementReport = ref(null)
const refinementError = ref('')
const previewDrawerOpen = ref(false)
const refinementDrawerOpen = ref(false)

async function loadRefinementReport() {
  if (!isPreview.value) {
    refinementStatus.value = 'idle'
    refinementReport.value = null
    return
  }
  refinementStatus.value = 'loading'
  refinementError.value = ''
  try {
    const data = await getKnowledgeBundleStatus(courseId.value)
    refinementReport.value = data
    refinementStatus.value = 'ready'
  } catch (err) {
    refinementStatus.value = 'error'
    refinementError.value = err?.message || 'refinement 质量报告读取失败'
  }
}

// 从 refinement 报告中提取展示字段（兼容后端不同字段命名）
const refinementRows = computed(() => {
  const r = refinementReport.value
  if (!r || typeof r !== 'object') return []
  const rows = []
  const push = (label, value, hint = '') => {
    if (value == null || value === '') return
    rows.push({ label, value: String(value), hint })
  }
  push('Bundle 状态', r.status || r.bundle_status, r.phase ? `阶段：${r.phase}` : '')
  push('Bundle 版本', r.version || r.bundle_version)
  push('节点总数', r.node_count ?? r.total_nodes)
  push('关系总数', r.relation_count ?? r.total_relations)
  push('已确认节点', r.confirmed_nodes ?? r.confirmed_node_count)
  push('待评审节点', r.pending_nodes ?? r.pending_node_count)
  push('已发布快照', r.published_snapshot_id || r.active_snapshot_id || '—')
  push('生成时间', r.generated_at || r.created_at)
  push('最后评审', r.last_review_at || r.reviewed_at)
  if (r.quality_metrics && typeof r.quality_metrics === 'object') {
    for (const [key, val] of Object.entries(r.quality_metrics)) {
      push(`质量·${key}`, val)
    }
  }
  if (r.issues && Array.isArray(r.issues) && r.issues.length) {
    rows.push({ label: '待处理问题', value: r.issues.length, hint: r.issues.join('；') })
  }
  return rows
})

watch(
  () => [courseId.value, studentId.value],
  () => loadRecommendations(),
)
watch(courseId, () => loadRefinementReport())

onMounted(() => {
  loadRecommendations()
  loadRefinementReport()
})
</script>

<template>
  <div class="sfx-knowledge">
    <SfxError
      v-if="missingStudentIdentity"
      variant="error"
      title="无法加载知识空间"
      description="未识别到当前学生身份，请重新登录后再访问。"
      :retryable="false"
    />

    <div v-else class="sfx-knowledge__body" :class="{ 'is-preview': isPreview }">
      <section v-if="isPreview" class="sfx-knowledge__teacher-tools" aria-label="教师预览工具">
        <SfxButton variant="secondary" size="sm" @click="previewDrawerOpen = true">
          <template #icon><Eye :size="15" aria-hidden="true" /></template>
          {{ previewRoleLabel }}预览
        </SfxButton>
        <SfxButton variant="secondary" size="sm" @click="refinementDrawerOpen = true">
          <template #icon><ShieldCheck :size="15" aria-hidden="true" /></template>
          质量报告
          <span v-if="refinementRows.length" class="sfx-knowledge__mode-count">{{ refinementRows.length }}</span>
        </SfxButton>
      </section>

      <section class="sfx-knowledge__main">
        <StudentGraphPanel
          :course-id="courseId"
          :node-id="nodeId"
          @jump-node="handleJumpNode"
          @return-anchor="handleReturnAnchor"
        />
      </section>

      <aside v-if="!isPreview" class="sfx-knowledge__aside">
          <CognitiveDashboard
            :course-id="courseId"
            :student-id="studentId"
          />

          <section class="sfx-knowledge__recs" aria-label="学习推荐">
            <header class="sfx-knowledge__recs-head">
              <Lightbulb :size="16" aria-hidden="true" />
              <h2 class="sfx-knowledge__recs-title">学习推荐</h2>
            </header>

            <div
              v-if="recommendationsStatus === 'loading'"
              class="sfx-knowledge__recs-state"
              role="status"
            >
              <LoaderCircle :size="18" class="sfx-knowledge__spinner" />
              <p>正在加载推荐…</p>
            </div>

            <div
              v-else-if="recommendationsStatus === 'error'"
              class="sfx-knowledge__recs-state sfx-knowledge__recs-state--error"
              role="alert"
            >
              <TriangleAlert :size="18" />
              <p>{{ recommendationsError || '推荐暂时不可读' }}</p>
              <SfxButton variant="secondary" size="sm" @click="loadRecommendations">重试</SfxButton>
            </div>

            <div
              v-else-if="recommendationsStatus === 'empty'"
              class="sfx-knowledge__recs-state sfx-knowledge__recs-state--empty"
            >
              <Lightbulb :size="22" :stroke-width="1.6" />
              <strong>暂无学习推荐</strong>
              <p>完成更多练习后，系统会基于真实证据生成定向推荐。</p>
            </div>

            <ul v-else class="sfx-knowledge__recs-list">
              <li
                v-for="rec in recommendations"
                :key="rec.recommendation_id"
                class="sfx-knowledge__recs-item"
              >
                <RecommendationCard
                  :recommendation="rec"
                  :consuming="consumingId === rec.recommendation_id"
                  :consumed="consumedIds.has(rec.recommendation_id)"
                  @consume="handleConsume"
                />
              </li>
            </ul>
          </section>
      </aside>
    </div>

    <SfxDrawer
      :open="previewDrawerOpen"
      title="教师预览模式"
      :width="480"
      @close="previewDrawerOpen = false"
    >
      <section class="sfx-knowledge__preview-notice" role="note">
        <Eye :size="24" aria-hidden="true" />
        <p class="sfx-knowledge__preview-kicker">{{ previewRoleLabel }}视角</p>
        <p class="sfx-knowledge__preview-text">
          当前查看的是已发布的知识图谱。学生的个人学习数据不在教师预览中展示。
        </p>
        <p class="sfx-knowledge__preview-hint">
          如需查看某位学生的学习情况，请前往课程学习分析页面。
        </p>
      </section>
    </SfxDrawer>

    <SfxDrawer
      :open="refinementDrawerOpen"
      title="Refinement 质量报告"
      :width="480"
      @close="refinementDrawerOpen = false"
    >
      <header class="sfx-knowledge__refinement-head">
        <div>
          <p class="sfx-knowledge__preview-kicker">当前知识包</p>
          <p class="sfx-knowledge__refinement-copy">检查已发布图谱的版本、规模与发布前检查状态。</p>
        </div>
        <SfxButton variant="secondary" size="sm" :loading="refinementStatus === 'loading'" @click="loadRefinementReport">
          刷新
        </SfxButton>
      </header>

      <div v-if="refinementStatus === 'loading'" class="sfx-knowledge__refinement-state" role="status">
        <LoaderCircle :size="18" class="sfx-knowledge__spinner" />
        <p>正在读取质量报告…</p>
      </div>
      <div v-else-if="refinementStatus === 'error'" class="sfx-knowledge__refinement-state sfx-knowledge__refinement-state--error" role="alert">
        <TriangleAlert :size="18" />
        <p>{{ refinementError }}</p>
        <SfxButton variant="secondary" size="sm" @click="loadRefinementReport">重试</SfxButton>
      </div>
      <dl v-else-if="refinementStatus === 'ready' && refinementRows.length" class="sfx-knowledge__refinement-dl">
        <template v-for="row in refinementRows" :key="row.label">
          <dt :title="row.hint">{{ row.label }}</dt>
          <dd :title="row.hint">{{ row.value }}</dd>
        </template>
      </dl>
      <div v-else class="sfx-knowledge__refinement-state" role="status">
        <ShieldCheck :size="22" :stroke-width="1.6" />
        <strong>暂无可展示的质量报告</strong>
        <p>该课程尚未生成报告，或后端尚未返回可解析字段。</p>
      </div>
    </SfxDrawer>
  </div>
</template>

<style scoped>
/* design.md §5.1 三层滚动模型：页面根容器 flex+min-height:0；L2 由 .sfx-shell-main 滚动 */
.sfx-knowledge {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  padding: var(--space-4, 16px);
  min-height: 0;
  flex: 1;
}

/* design.md §5.2：grid 行高用 minmax(0,1fr) 限制，避免内容撑爆 */
.sfx-knowledge__body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: var(--space-4, 16px);
  flex: 1;
  min-height: 0;
}

.sfx-knowledge__body.is-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}

.sfx-knowledge__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.sfx-knowledge__aside {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}

.sfx-knowledge__teacher-tools {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2, 8px);
  flex-shrink: 0;
}

.sfx-knowledge__mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  border: 1px solid var(--border-default, #DDE2E8);
  border-radius: 999px;
  padding: 0 12px;
  background: rgba(255, 255, 255, .94);
  color: var(--ink-700, #203A5F);
  font-size: var(--ui-sm-size, 13px);
  font-weight: 560;
  cursor: pointer;
}
.sfx-knowledge__mode-chip:hover { background: var(--ink-100, #E8EEF4); }
.sfx-knowledge__mode-count {
  min-width: 20px;
  border-radius: 999px;
  padding: 1px 6px;
  background: var(--ink-700, #203A5F);
  color: white;
  font-size: var(--caption-size);
  text-align: center;
}

/* 教师预览占位提示 — design.md §1.3 surface-cool + §1.5 border-default */
.sfx-knowledge__preview-notice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2, 8px);
  padding: var(--space-5, 20px) var(--space-4, 16px);
  background: var(--surface-cool, #F7F8FA);
  border-left: 3px solid var(--ink-500, #355C7D);
  border-radius: 0 var(--radius-md, 10px) var(--radius-md, 10px) 0;
  color: var(--text-secondary, #4E5969);
}

.sfx-knowledge__preview-kicker {
  margin: 0;
  color: var(--ink-700, #203A5F);
  font-size: var(--caption-size, 12px);
  font-weight: 650;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.sfx-knowledge__preview-text {
  margin: 0;
  font-size: var(--ui-sm-size, 13px);
  line-height: 1.5;
}

.sfx-knowledge__preview-hint {
  margin: 0;
  font-size: var(--caption-size, 12px);
  color: var(--text-muted, #7B8494);
}

/* Refinement 质量报告区 — design.md §4.5 主工作面板 */
.sfx-knowledge__refinement-head {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle, #EDF0F3);
  padding-bottom: var(--space-4, 16px);
}
.sfx-knowledge__refinement-copy { margin: 5px 0 0; color: var(--text-secondary, #4E5969); }

.sfx-knowledge__refinement-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-6, 24px) var(--space-3, 12px);
  text-align: center;
  color: var(--text-muted, #7B8494);
}
.sfx-knowledge__refinement-state--error { color: var(--red-700, #8B3A3A); }

/* design.md §4.8 描述列表：140px / 1fr 两列 */
.sfx-knowledge__refinement-dl {
  display: grid;
  grid-template-columns: 130px 1fr;
  row-gap: 0;
  column-gap: var(--space-3, 12px);
  margin: 0;
  font-size: var(--ui-sm-size, 13px);
}
.sfx-knowledge__refinement-dl dt {
  padding: 11px 0;
  border-bottom: 1px solid var(--border-subtle, #EDF0F3);
  color: var(--text-muted, #7B8494);
  font-weight: 450;
}
.sfx-knowledge__refinement-dl dd {
  padding: 11px 0;
  border-bottom: 1px solid var(--border-subtle, #EDF0F3);
  margin: 0;
  color: var(--text-primary, #172033);
  font-weight: 500;
  word-break: break-all;
}

/* 推荐卡区 */
.sfx-knowledge__recs {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  background: var(--surface-canvas, #FBFAF7);
  border: 1px solid var(--border-default, #DDE2E8);
  border-radius: var(--radius-md, 10px);
}

.sfx-knowledge__recs-head {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  color: var(--ink-700, #203A5F);
}

.sfx-knowledge__recs-title {
  margin: 0;
  font-size: var(--ui-md-size, 14px);
  font-weight: 600;
  color: var(--text-primary, #172033);
}

.sfx-knowledge__recs-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-6, 24px) var(--space-3, 12px);
  text-align: center;
  color: var(--text-muted, #7B8494);
}
.sfx-knowledge__recs-state--error { color: var(--red-700, #8B3A3A); }
.sfx-knowledge__recs-state--empty { color: var(--text-muted, #7B8494); }

/* design.md §1.1 ink-500 替换原 accent-primary #4f8cf7 */
.sfx-knowledge__spinner {
  color: var(--ink-500, #355C7D);
  animation: sfx-knowledge-spin 0.9s linear infinite;
}
@keyframes sfx-knowledge-spin { to { transform: rotate(360deg); } }

.sfx-knowledge__recs-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}
.sfx-knowledge__recs-item { min-width: 0; }

@media (max-width: 760px) {
  .sfx-knowledge__body { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .sfx-knowledge__teacher-tools { justify-content: flex-start; flex-wrap: wrap; }
}
</style>
