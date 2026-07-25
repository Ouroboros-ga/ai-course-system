<script setup>
/**
 * 课程知识空间页（批次3，page-design §15）。
 *
 * 整合三块学生侧能力，提供统一入口：
 * - StudentGraphPanel：已发布图谱快照 + 一跳先修/后继 + 跳转锚点；
 * - CognitiveDashboard：六维认知状态（保留 null 语义，不武断判弱）；
 * - RecommendationCard 列表：基于策略版本的推荐，支持消费/锁定状态。
 *
 * 路由：/app/course/:courseId/knowledge/:nodeId?
 * - courseId 必填；
 * - nodeId 可选，存在时聚焦到该知识点并拉取相邻关系。
 *
 * 权限：依赖 CourseLayout 提供的 courseContext（allowed/capabilities）。
 * 学生查看自己；教师/助教预览时不强制写入学习证据。
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Lightbulb, LoaderCircle, TriangleAlert } from 'lucide-vue-next'
import StudentGraphPanel from '@/features/student-graph/StudentGraphPanel.vue'
import CognitiveDashboard from '@/components/cognitive/CognitiveDashboard.vue'
import RecommendationCard from '@/features/student-learning/components/RecommendationCard.vue'
import SfxError from '@/app/ui/SfxError.vue'
import { useCounterStore } from '@/stores/counter.js'
import {
  consumeRecommendation,
  getRecommendations,
} from '@/api/cognitive.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()
const { courseId, courseRole } = inject('courseContext')

const nodeId = computed(() =>
  route.params.nodeId != null ? Number(route.params.nodeId) : null,
)

// 学生 ID：学生视角下使用当前用户 ID；教师预览时仍使用当前用户 ID
// （后端会基于 JWT 解析学生身份，教师预览仅查看图谱与推荐，不写入证据）。
const studentId = computed(() => counter.userData?.id ?? null)

const isPreview = computed(() =>
  ['owner', 'teacher', 'teaching_assistant'].includes(courseRole.value),
)

// 推荐列表
const recommendations = ref([])
const recommendationsStatus = ref('idle') // idle | loading | ready | empty | error
const recommendationsError = ref('')
const consumingId = ref('')
const consumedIds = ref(new Set())

async function loadRecommendations() {
  if (studentId.value == null) {
    recommendationsStatus.value = 'empty'
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
  router.push(`/app/course/${courseId.value}/knowledge/${node.id}`)
}

function handleReturnAnchor() {
  // 返回课程概览（无锚点时回退到概览）
  router.push(`/app/course/${courseId.value}/overview`)
}

function backToOverview() {
  router.push(`/app/course/${courseId.value}/overview`)
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
    <header class="sfx-knowledge__bar">
      <button type="button" class="sfx-knowledge__back" @click="backToOverview">
        <ArrowLeft :size="16" /> 返回概览
      </button>
      <div class="sfx-knowledge__title-block">
        <h1 class="sfx-knowledge__title">课程知识空间</h1>
        <p class="sfx-knowledge__subtitle">
          <span v-if="isPreview">教师预览视角（不写入学习证据）</span>
          <span v-else>基于已发布图谱快照与六维认知状态</span>
        </p>
      </div>
    </header>

    <SfxError
      v-if="studentId == null"
      variant="error"
      title="无法加载知识空间"
      description="未识别到当前学生身份，请重新登录后再访问。"
      :retryable="false"
    />

    <div v-else class="sfx-knowledge__body">
      <!-- 主区：知识图谱 -->
      <section class="sfx-knowledge__main">
        <StudentGraphPanel
          :course-id="courseId"
          :node-id="nodeId"
          @jump-node="handleJumpNode"
          @return-anchor="handleReturnAnchor"
        />
      </section>

      <!-- 侧栏：认知仪表盘 + 推荐卡 -->
      <aside class="sfx-knowledge__aside">
        <CognitiveDashboard
          :course-id="courseId"
          :student-id="studentId"
        />

        <section class="sfx-knowledge__recs" aria-label="学习推荐">
          <header class="sfx-knowledge__recs-head">
            <Lightbulb :size="16" />
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
            <button
              type="button"
              class="sfx-knowledge__retry"
              @click="loadRecommendations"
            >
              重试
            </button>
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
.sfx-knowledge {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  min-height: 0;
  flex: 1;
}

.sfx-knowledge__bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-default, #e5e7eb);
}

.sfx-knowledge__back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-panel, #fff);
  color: var(--text-secondary, #374151);
  font-size: 0.85rem;
  cursor: pointer;
}

.sfx-knowledge__back:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-knowledge__title-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-knowledge__title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-knowledge__subtitle {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-knowledge__body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 1100px) {
  .sfx-knowledge__body {
    grid-template-columns: 1fr;
  }
}

.sfx-knowledge__main {
  min-width: 0;
}

.sfx-knowledge__aside {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

/* 推荐卡区 */
.sfx-knowledge__recs {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: var(--surface-canvas, #fafbfc);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 10px;
}

.sfx-knowledge__recs-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sfx-knowledge__recs-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-knowledge__recs-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px 12px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-knowledge__recs-state--error {
  color: var(--red-700, #c62828);
}

.sfx-knowledge__recs-state--empty {
  color: var(--text-muted, #9ca3af);
}

.sfx-knowledge__spinner {
  color: var(--accent-primary, #4f8cf7);
  animation: sfx-knowledge-spin 0.8s linear infinite;
}

@keyframes sfx-knowledge-spin {
  to { transform: rotate(360deg); }
}

.sfx-knowledge__retry {
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--ink-700, #1f2937);
}

.sfx-knowledge__retry:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-knowledge__recs-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sfx-knowledge__recs-item {
  min-width: 0;
}
</style>
