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
import { Lightbulb, LoaderCircle, TriangleAlert } from 'lucide-vue-next'
import StudentGraphPanel from '@/features/student-graph/StudentGraphPanel.vue'
import CognitiveDashboard from '@/components/cognitive/CognitiveDashboard.vue'
import RecommendationCard from '@/features/student-learning/components/RecommendationCard.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import { useCounterStore } from '@/stores/counter.js'
import {
  consumeRecommendation,
  getRecommendations,
} from '@/api/cognitive.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()
const { courseId, analyticsEligible } = inject('courseContext')

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

function handleOpenLearnNode(node) {
  // 原文引用页映射到的学习页节点：带锚点进入学习页并定位到该节点
  if (!node) return
  const query = {}
  if (node.outlineNodeId != null) query.node = String(node.outlineNodeId)
  if (Number.isInteger(node.index)) query.nodeIndex = String(node.index)
  if (!Object.keys(query).length) return
  router.push({ path: `/app/course/${courseId.value}/learn`, query })
}

watch(
  () => [courseId.value, studentId.value],
  () => loadRecommendations(),
)

onMounted(() => {
  loadRecommendations()
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
      <section class="sfx-knowledge__main">
        <StudentGraphPanel
          :course-id="courseId"
          :node-id="nodeId"
          @jump-node="handleJumpNode"
          @open-learn-node="handleOpenLearnNode"
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

  </div>
</template>

<style scoped>
/* design.md §5.1 三层滚动模型：页面根容器 flex+min-height:0；
   知识工作区并入建设布局后（.stage-body 为 overflow:hidden 的块容器），
   根容器需要明确 height:100% 让内部 grid/fr 与 aside 滚动正常工作 */
.sfx-knowledge {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  padding: var(--space-4, 16px);
  min-height: 0;
  flex: 1;
  height: 100%;
  overflow-y: auto;
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
}
</style>
