<script setup>
/**
 * VISUALIZE 舞台（批次4）：在学习页内嵌播放可视化计划。
 *
 * 与 CitationStage / PracticePanel 同级：
 * - 数据来自 /api/v1/visualization 真实端点；
 * - 仅展示 published 计划给学生（教师可看全部，但本面板默认学生视角）；
 * - 点击「播放」通过 getPlan(planId) 拉取 plan_data，嵌入 JSAVPlayer；
 * - 无 published 计划时显示「暂无可视化内容」；
 * - 提供「跳转到可视化页」入口（VisualizationView）与「返回课程」按钮。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  ExternalLink,
  LineChart,
  LoaderCircle,
  PlayCircle,
  TriangleAlert,
  X,
} from 'lucide-vue-next'
import { getPlan, listPlans } from '@/api/visualization.js'
import JSAVPlayer from '@/components/visualization/JSAVPlayer.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  /** 当前知识点 ID（用于按节点筛选计划） */
  nodeId: { type: [Number, String], default: null },
  /** 当前知识点标题（用于头部展示） */
  nodeTitle: { type: String, default: '' },
  /** Teacher preview may inspect validated/draft plans; students see published only. */
  preview: { type: Boolean, default: false },
})

const emit = defineEmits(['exit'])

const router = useRouter()

const status = ref('idle') // idle | loading | ready | empty | error
const errorMessage = ref('')
const plans = ref([])

const activePlan = ref(null)
const activePlanLoading = ref(false)
const activePlanError = ref('')

const visiblePlans = computed(() => props.preview ? plans.value : plans.value.filter(
  (p) => p.status === 'published' || p.is_published === true,
))
function mapError(err) {
  const msg = String(err?.message || '')
  if (/403|401|forbidden|权限|拒绝/.test(msg)) return 'forbidden'
  if (/503|unavailable|未配置|not configured/.test(msg)) return 'unavailable'
  return 'error'
}

async function loadPlans() {
  if (props.courseId == null || props.courseId === '') {
    status.value = 'empty'
    return
  }
  status.value = 'loading'
  errorMessage.value = ''
  try {
    const params = props.preview ? {} : { status: 'published' }
    if (props.nodeId != null) params.node_id = props.nodeId
    const res = await listPlans(props.courseId, params)
    const items = Array.isArray(res) ? res : (res?.items ?? res?.plans ?? [])
    plans.value = items
    status.value = items.length ? 'ready' : 'empty'
  } catch (err) {
    status.value = mapError(err)
    errorMessage.value = err?.message || '可视化计划加载失败'
  }
}

async function playPlan(plan) {
  if (!plan?.plan_id || activePlanLoading.value) return
  activePlanLoading.value = true
  activePlanError.value = ''
  activePlan.value = null
  try {
    const full = await getPlan(plan.plan_id)
    activePlan.value = full?.plan_data ? full : { ...full, plan_data: full }
  } catch (err) {
    activePlanError.value = err?.message || '计划详情加载失败'
  } finally {
    activePlanLoading.value = false
  }
}

function closePlayer() {
  activePlan.value = null
  activePlanError.value = ''
}

function jumpToVisualizationView() {
  const path =
    props.nodeId != null
      ? `/app/course/${props.courseId}/visualize/${props.nodeId}`
      : `/app/course/${props.courseId}/visualize`
  router.push(path)
}

function handleReturnAnchor() {
  // 播放器内「返回锚点」：关闭播放器，回到列表
  closePlayer()
}

watch(
  () => [props.courseId, props.nodeId],
  () => {
    closePlayer()
    loadPlans()
  },
)

onMounted(loadPlans)
</script>

<template>
  <div class="sfx-vis-stage">
    <header class="sfx-vis-stage-header">
      <button type="button" class="sfx-vis-stage-back" @click="emit('exit')">
        <ArrowLeft :size="16" /> 返回课程
      </button>
      <div class="sfx-vis-stage-headtext">
        <h2 class="sfx-vis-stage-title">
          <LineChart :size="18" />
          看可视化
          <span v-if="nodeTitle" class="sfx-vis-stage-node">· {{ nodeTitle }}</span>
        </h2>
        <span v-if="status === 'ready'" class="sfx-vis-stage-meta">
          {{ visiblePlans.length }} {{ props.preview ? '个可预览' : '个已发布' }}计划
        </span>
      </div>
      <button
        type="button"
        class="sfx-vis-stage-jump"
        @click="jumpToVisualizationView"
      >
        <ExternalLink :size="14" /> 完整可视化页
      </button>
    </header>

    <!-- 播放器（嵌入在舞台内） -->
    <section
      v-if="activePlan || activePlanLoading || activePlanError"
      class="sfx-vis-stage-player"
      aria-label="可视化播放器"
    >
      <header class="sfx-vis-stage-player-head">
        <span class="sfx-vis-stage-player-title">
          <PlayCircle :size="15" /> 正在播放
        </span>
        <button
          type="button"
          class="sfx-vis-stage-close"
          @click="closePlayer"
          aria-label="关闭播放器"
        >
          <X :size="14" />
        </button>
      </header>
      <div v-if="activePlanLoading" class="sfx-vis-stage-state">
        <LoaderCircle :size="22" class="sfx-vis-stage-spinner" />
        <p>加载计划详情…</p>
      </div>
      <div
        v-else-if="activePlanError"
        class="sfx-vis-stage-state sfx-vis-stage-state--error"
      >
        <TriangleAlert :size="20" />
        <p>{{ activePlanError }}</p>
      </div>
      <JSAVPlayer
        v-else-if="activePlan"
        :plan-data="activePlan"
        @return-anchor="handleReturnAnchor"
      />
    </section>

    <!-- 计划列表 -->
    <div v-if="status === 'loading'" class="sfx-vis-stage-state" role="status">
      <LoaderCircle :size="22" class="sfx-vis-stage-spinner" />
      <p>正在加载已发布可视化计划…</p>
    </div>

    <div
      v-else-if="status === 'error' || status === 'forbidden' || status === 'unavailable'"
      class="sfx-vis-stage-state sfx-vis-stage-state--error"
      role="alert"
    >
      <TriangleAlert :size="22" />
      <p>{{ errorMessage || '可视化计划暂时不可读' }}</p>
      <SfxButton variant="secondary" @click="loadPlans">
        重试
      </SfxButton>
    </div>

    <div v-else-if="status === 'empty'" class="sfx-vis-stage-state sfx-vis-stage-state--empty">
      <LineChart :size="28" :stroke-width="1.6" />
      <strong>暂无可视化内容</strong>
      <p>
        当前知识点暂无已发布的可视化计划。完成学习后可由教师创建并发布。
      </p>
    </div>

    <ul v-else class="sfx-vis-stage-list">
      <li
        v-for="plan in visiblePlans"
        :key="plan.plan_id"
        class="sfx-vis-stage-item"
      >
        <div class="sfx-vis-stage-item-main">
          <header class="sfx-vis-stage-item-head">
            <span class="sfx-vis-stage-item-algo">
              {{ plan.algorithm_name || plan.algorithm_id || '未指定算法' }}
            </span>
            <span v-if="plan.algorithm_category" class="sfx-vis-stage-item-cat">
              {{ plan.algorithm_category }}
            </span>
          </header>
          <h3 class="sfx-vis-stage-item-title">
            {{ plan.title || plan.name || `计划 ${plan.plan_id}` }}
          </h3>
          <p v-if="plan.description" class="sfx-vis-stage-item-desc">
            {{ plan.description }}
          </p>
        </div>
        <button
          type="button"
          class="sfx-vis-stage-play-btn"
          :disabled="activePlanLoading"
          @click="playPlan(plan)"
        >
          <PlayCircle :size="14" />
          播放
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sfx-vis-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-canvas, #fafbfc);
  overflow-y: auto;
  padding: 16px 24px 40px;
  animation: sfx-vis-stage-in var(--duration-normal, 0.2s) var(--ease-out, ease-out);
}

@keyframes sfx-vis-stage-in {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.sfx-vis-stage-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.sfx-vis-stage-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  color: var(--text-secondary, #6b7280);
  font-size: 0.85rem;
  font-weight: 500;
  background: none;
  border: 1px solid transparent;
  cursor: pointer;
}

.sfx-vis-stage-back:hover {
  background: var(--surface-cool, #f5f5f5);
  color: var(--ink-700, #1f2937);
}

.sfx-vis-stage-headtext {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-vis-stage-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sfx-vis-stage-node {
  color: var(--text-secondary, #6b7280);
  font-weight: 500;
}

.sfx-vis-stage-meta {
  font-size: 0.78rem;
  color: var(--text-muted, #9ca3af);
}

.sfx-vis-stage-jump {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-panel, #fff);
  color: var(--accent-primary, #4f8cf7);
  font-size: 0.82rem;
  cursor: pointer;
  flex-shrink: 0;
}

.sfx-vis-stage-jump:hover {
  background: var(--surface-cool, #f5f5f5);
  border-color: var(--accent-primary, #4f8cf7);
}

/* 播放器 */
.sfx-vis-stage-player {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 10px;
  margin-bottom: 16px;
}

.sfx-vis-stage-player-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sfx-vis-stage-player-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-vis-stage-close {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis-stage-close:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis-stage-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 32px 16px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-vis-stage-state--error {
  color: var(--red-700, #c62828);
}

.sfx-vis-stage-state--empty {
  color: var(--text-muted, #9ca3af);
}

.sfx-vis-stage-spinner {
  color: var(--accent-primary, #4f8cf7);
  animation: sfx-vis-stage-spin 0.8s linear infinite;
}

@keyframes sfx-vis-stage-spin {
  to { transform: rotate(360deg); }
}

.sfx-vis-stage-retry {
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--ink-700, #1f2937);
}

.sfx-vis-stage-retry:hover {
  background: var(--surface-cool, #f5f5f5);
}

/* 计划列表 */
.sfx-vis-stage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 860px;
}

.sfx-vis-stage-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 8px;
}

.sfx-vis-stage-item-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sfx-vis-stage-item-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.sfx-vis-stage-item-algo {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--accent-primary, #4f8cf7);
}

.sfx-vis-stage-item-cat {
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface-cool, #f0f0f0);
  color: var(--text-muted, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sfx-vis-stage-item-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-vis-stage-item-desc {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-secondary, #6b7280);
  line-height: 1.4;
}

.sfx-vis-stage-play-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  flex-shrink: 0;
}

.sfx-vis-stage-play-btn:hover:not(:disabled) {
  background: var(--accent-primary-hover, #3b7be0);
}

.sfx-vis-stage-play-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
