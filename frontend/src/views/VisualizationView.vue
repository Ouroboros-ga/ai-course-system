<script setup>
/**
 * 可视化视图（批次4）。
 *
 * 接收路由参数 courseId 与可选 nodeId：
 * - 调用 listPlans(courseId, { node_id, status }) 获取计划列表；
 * - 学生只看 published 计划；具备 course.mapping.edit 权限者可看全部并可 createPlan/publishPlan；
 * - 点击「播放」通过 getPlan(planId) 获取 plan_data 后嵌入 JSAVPlayer；
 * - 白名单算法来自 listAlgorithms()；
 * - 播放完成后通过「返回锚点」回到学习页（路由回退或显式跳转）。
 *
 * 权限（P1 修复）：从 CourseLayout 提供的 courseContext.allowed['course.mapping.edit']
 * 判断当前用户在本课程内的建设权限，不再用全局 User.role 近似（AGENTS.md Course Access v1）。
 * 数据契约：所有 API 失败均显示友好状态，不阻塞页面其他计划。
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  CheckCircle2,
  Code2,
  Eye,
  LineChart,
  LoaderCircle,
  PlayCircle,
  Plus,
  Send,
  TriangleAlert,
} from 'lucide-vue-next'
import {
  createPlan,
  getPlan,
  listAlgorithms,
  listPlans,
  publishPlan,
} from '@/api/visualization.js'
import JSAVPlayer from '@/components/visualization/JSAVPlayer.vue'

const route = useRoute()
const router = useRouter()
const { allowed } = inject('courseContext')

const courseId = computed(() => Number(route.params.courseId))
const nodeId = computed(() =>
  route.params.nodeId != null ? Number(route.params.nodeId) : null,
)

// 课程建设权限：course.mapping.edit 属于 course_building capability，
// 教师/owner 在 capability 开启时拥有；学生/观察者无此权限。
// 不再用全局 counter.userData.role 近似当前课程权限。
const canEditVisualisation = computed(
  () => Boolean(allowed.value?.['course.mapping.edit']),
)

// 计划列表
const plans = ref([])
const listStatus = ref('idle') // idle | loading | ready | empty | error
const listError = ref('')

// 算法白名单
const algorithms = ref([])
const algorithmsStatus = ref('idle')

// 当前播放
const activePlan = ref(null) // 完整 plan 对象（含 plan_data）
const activePlanLoading = ref(false)
const activePlanError = ref('')

// 教师创建计划
const showCreatePanel = ref(false)
const createForm = ref({
  algorithm_id: '',
  initial_params_json: '{"array": [5, 2, 8, 1, 9, 3]}',
  steps_json: '[]',
  highlights_json: '[]',
  playback_speed: 1.0,
  node_id: '',
})
const creating = ref(false)
const createError = ref('')

// 发布中
const publishingId = ref('')

const filteredPlans = computed(() => {
  if (canEditVisualisation.value) return plans.value
  // 学生只看 published
  return plans.value.filter(
    (p) => p.status === 'published' || p.is_published === true,
  )
})

function mapListError(err) {
  const msg = String(err?.message || '')
  if (/403|401|forbidden|权限|拒绝/.test(msg)) return 'forbidden'
  if (/503|unavailable|未配置|not configured/.test(msg)) return 'unavailable'
  return 'error'
}

async function loadPlans() {
  if (!courseId.value) {
    listStatus.value = 'empty'
    return
  }
  listStatus.value = 'loading'
  listError.value = ''
  try {
    const params = {}
    if (nodeId.value != null) params.node_id = nodeId.value
    // 学生视角强制只看 published
    if (!canEditVisualisation.value) params.status = 'published'
    const res = await listPlans(courseId.value, params)
    const items = Array.isArray(res)
      ? res
      : (res?.items ?? res?.plans ?? [])
    plans.value = items
    listStatus.value = items.length ? 'ready' : 'empty'
  } catch (err) {
    listStatus.value = mapListError(err)
    listError.value = err?.message || '可视化计划加载失败'
  }
}

async function loadAlgorithms() {
  algorithmsStatus.value = 'loading'
  try {
    const res = await listAlgorithms()
    algorithms.value = Array.isArray(res)
      ? res
      : (res?.algorithms ?? [])
    algorithmsStatus.value = 'ready'
  } catch {
    // 算法白名单加载失败不阻塞播放，仅影响教师创建
    algorithmsStatus.value = 'error'
  }
}

async function playPlan(plan) {
  if (!plan?.plan_id) return
  activePlanLoading.value = true
  activePlanError.value = ''
  activePlan.value = null
  try {
    const full = await getPlan(plan.plan_id)
    // 后端可能返回完整 plan 或仅 plan_data
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

async function publishOne(plan) {
  if (!plan?.plan_id || publishingId.value) return
  publishingId.value = plan.plan_id
  try {
    await publishPlan(courseId.value, plan.plan_id)
    // 本地标记为已发布，避免再次拉取
    plan.status = 'published'
    plan.is_published = true
  } catch (err) {
    listError.value = err?.message || '发布失败'
  } finally {
    publishingId.value = ''
  }
}

function openCreatePanel() {
  if (!algorithms.value.length && algorithmsStatus.value !== 'loading') {
    loadAlgorithms()
  }
  // 默认填入第一个算法与当前 nodeId
  if (!createForm.value.algorithm_id && algorithms.value.length) {
    createForm.value.algorithm_id = algorithms.value[0].algorithm_id
  }
  if (nodeId.value != null) {
    createForm.value.node_id = String(nodeId.value)
  }
  showCreatePanel.value = true
}

async function submitCreate() {
  if (!createForm.value.algorithm_id) {
    createError.value = '请先选择算法'
    return
  }
  let parsedParams
  let parsedSteps
  let parsedHighlights
  try {
    parsedParams = JSON.parse(createForm.value.initial_params_json || '{}')
  } catch {
    createError.value = 'initial_params 不是合法 JSON'
    return
  }
  try {
    parsedSteps = JSON.parse(createForm.value.steps_json || '[]')
  } catch {
    createError.value = 'steps 不是合法 JSON'
    return
  }
  try {
    parsedHighlights = JSON.parse(createForm.value.highlights_json || '[]')
  } catch {
    createError.value = 'highlights 不是合法 JSON'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const payload = {
      algorithm_id: createForm.value.algorithm_id,
      initial_params: parsedParams,
      steps: parsedSteps,
      highlights: parsedHighlights,
      playback_speed: Number(createForm.value.playback_speed) || 1.0,
    }
    if (createForm.value.node_id) {
      payload.node_id = Number(createForm.value.node_id)
    }
    const created = await createPlan(courseId.value, payload)
    if (created?.plan_id) {
      plans.value = [created, ...plans.value]
    }
    showCreatePanel.value = false
    listStatus.value = 'ready'
    // 重置表单
    createForm.value = {
      algorithm_id: algorithms.value[0]?.algorithm_id ?? '',
      initial_params_json: '{"array": [5, 2, 8, 1, 9, 3]}',
      steps_json: '[]',
      highlights_json: '[]',
      playback_speed: 1.0,
      node_id: nodeId.value != null ? String(nodeId.value) : '',
    }
  } catch (err) {
    createError.value = err?.message || '创建失败，请检查参数'
  } finally {
    creating.value = false
  }
}

function handleReturnAnchor() {
  // 返回学习页（与 LearnPage 的 visualize 入口对应）
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push(`/app/course/${courseId.value}/learn`)
}

function planStatusTone(plan) {
  if (plan.status === 'published' || plan.is_published) return 'published'
  if (plan.status === 'draft') return 'draft'
  return 'neutral'
}

function planStatusLabel(plan) {
  if (plan.status === 'published' || plan.is_published) return '已发布'
  if (plan.status === 'draft') return '草稿'
  return plan.status || '未知'
}

watch(
  () => [courseId.value, nodeId.value],
  () => loadPlans(),
)

onMounted(() => {
  loadPlans()
  if (canEditVisualisation.value) loadAlgorithms()
})
</script>

<template>
  <div class="sfx-vis">
    <header class="sfx-vis__bar">
      <button type="button" class="sfx-vis__back" @click="handleReturnAnchor">
        <ArrowLeft :size="16" /> 返回学习
      </button>
      <div class="sfx-vis__title-block">
        <h1 class="sfx-vis__title">
          <LineChart :size="18" />
          算法可视化
        </h1>
        <p class="sfx-vis__subtitle">
          课程 #{{ courseId }}
          <template v-if="nodeId != null"> · 知识点 #{{ nodeId }}</template>
        </p>
      </div>
      <div v-if="canEditVisualisation" class="sfx-vis__actions">
        <button
          type="button"
          class="sfx-vis__create-btn"
          @click="openCreatePanel"
        >
          <Plus :size="14" /> 新建计划
        </button>
      </div>
    </header>

    <!-- 播放器（覆盖在列表上方时仍保留列表） -->
    <section
      v-if="activePlan || activePlanLoading || activePlanError"
      class="sfx-vis__player-section"
      aria-label="可视化播放器"
    >
      <header class="sfx-vis__player-head">
        <span class="sfx-vis__player-title">
          <PlayCircle :size="16" /> 正在播放
        </span>
        <button type="button" class="sfx-vis__close-player" @click="closePlayer">
          关闭
        </button>
      </header>
      <div v-if="activePlanLoading" class="sfx-vis__player-state">
        <LoaderCircle :size="22" class="sfx-vis__spinner" />
        <p>加载计划详情…</p>
      </div>
      <div v-else-if="activePlanError" class="sfx-vis__player-state sfx-vis__player-state--error">
        <TriangleAlert :size="20" />
        <p>{{ activePlanError }}</p>
      </div>
      <JSAVPlayer
        v-else-if="activePlan"
        :plan-data="activePlan"
        @return-anchor="handleReturnAnchor"
      />
    </section>

    <!-- 教师创建计划 -->
    <section v-if="showCreatePanel" class="sfx-vis__create">
      <header class="sfx-vis__create-head">
        <h2 class="sfx-vis__create-title">
          <Code2 :size="16" /> 新建可视化计划
        </h2>
        <button type="button" class="sfx-vis__close-create" @click="showCreatePanel = false">
          取消
        </button>
      </header>

      <div v-if="algorithmsStatus === 'loading'" class="sfx-vis__create-state">
        正在加载算法白名单…
      </div>
      <div v-else-if="algorithmsStatus === 'error'" class="sfx-vis__create-state sfx-vis__create-state--error">
        算法白名单加载失败，无法创建计划
      </div>
      <template v-else>
        <div class="sfx-vis__field">
          <label class="sfx-vis__label">算法</label>
          <select v-model="createForm.algorithm_id" class="sfx-vis__select">
            <option value="" disabled>请选择算法</option>
            <option
              v-for="algo in algorithms"
              :key="algo.algorithm_id"
              :value="algo.algorithm_id"
            >
              {{ algo.name || algo.algorithm_id }}（{{ algo.category || '未分类' }}）
            </option>
          </select>
        </div>

        <div class="sfx-vis__field">
          <label class="sfx-vis__label">初始参数 (JSON)</label>
          <textarea v-model="createForm.initial_params_json" rows="3" class="sfx-vis__textarea" />
        </div>

        <div class="sfx-vis__field">
          <label class="sfx-vis__label">步骤列表 (JSON)</label>
          <textarea v-model="createForm.steps_json" rows="4" class="sfx-vis__textarea" />
        </div>

        <div class="sfx-vis__field">
          <label class="sfx-vis__label">高亮列表 (JSON, 可选)</label>
          <textarea v-model="createForm.highlights_json" rows="3" class="sfx-vis__textarea" />
        </div>

        <div class="sfx-vis__field-row">
          <div class="sfx-vis__field">
            <label class="sfx-vis__label">回放速度</label>
            <input
              v-model.number="createForm.playback_speed"
              type="number"
              step="0.1"
              min="0.5"
              max="3"
              class="sfx-vis__input"
            />
          </div>
          <div class="sfx-vis__field">
            <label class="sfx-vis__label">关联知识点 ID (可选)</label>
            <input v-model="createForm.node_id" type="number" class="sfx-vis__input" />
          </div>
        </div>

        <p v-if="createError" class="sfx-vis__create-error">{{ createError }}</p>

        <div class="sfx-vis__create-actions">
          <button
            type="button"
            class="sfx-vis__submit-btn"
            :disabled="creating"
            @click="submitCreate"
          >
            <Send :size="14" />
            {{ creating ? '提交中…' : '创建计划' }}
          </button>
        </div>
      </template>
    </section>

    <!-- 计划列表 -->
    <section class="sfx-vis__list-section" aria-label="可视化计划列表">
      <header class="sfx-vis__list-head">
        <h2 class="sfx-vis__list-title">
          <Eye :size="16" />
          可视化计划
          <span v-if="filteredPlans.length" class="sfx-vis__list-count">
            {{ filteredPlans.length }}
          </span>
        </h2>
        <button
          v-if="listStatus !== 'loading'"
          type="button"
          class="sfx-vis__refresh"
          @click="loadPlans"
        >
          刷新
        </button>
      </header>

      <div v-if="listStatus === 'loading'" class="sfx-vis__list-state" role="status">
        <LoaderCircle :size="20" class="sfx-vis__spinner" />
        <p>正在加载可视化计划…</p>
      </div>

      <div
        v-else-if="listStatus === 'error' || listStatus === 'forbidden' || listStatus === 'unavailable'"
        class="sfx-vis__list-state sfx-vis__list-state--error"
        role="alert"
      >
        <TriangleAlert :size="20" />
        <p>{{ listError || '可视化计划暂时不可读' }}</p>
        <button type="button" class="sfx-vis__retry" @click="loadPlans">重试</button>
      </div>

      <div v-else-if="listStatus === 'empty'" class="sfx-vis__list-state sfx-vis__list-state--empty">
        <LineChart :size="26" :stroke-width="1.6" />
        <strong>暂无可视化内容</strong>
        <p>
          当前知识点暂无已发布的可视化计划。
          <template v-if="canEditVisualisation">教师可在右上角「新建计划」创建。</template>
        </p>
      </div>

      <ul v-else class="sfx-vis__list">
        <li
          v-for="plan in filteredPlans"
          :key="plan.plan_id"
          class="sfx-vis__plan"
        >
          <div class="sfx-vis__plan-main">
            <header class="sfx-vis__plan-head">
              <span
                class="sfx-vis__plan-status"
                :class="`tone-${planStatusTone(plan)}`"
              >
                {{ planStatusLabel(plan) }}
              </span>
              <span v-if="plan.algorithm_id" class="sfx-vis__plan-algo">
                {{ plan.algorithm_name || plan.algorithm_id }}
              </span>
              <span v-if="plan.node_id" class="sfx-vis__plan-node">
                · 知识点 #{{ plan.node_id }}
              </span>
            </header>
            <h3 class="sfx-vis__plan-title">
              {{ plan.title || plan.name || `计划 ${plan.plan_id}` }}
            </h3>
            <p v-if="plan.description" class="sfx-vis__plan-desc">
              {{ plan.description }}
            </p>
            <p class="sfx-vis__plan-meta">
              <span v-if="plan.play_count != null">播放 {{ plan.play_count }} 次</span>
              <span v-if="plan.created_at"> · 创建于 {{ plan.created_at }}</span>
            </p>
          </div>
          <div class="sfx-vis__plan-actions">
            <button
              type="button"
              class="sfx-vis__play-btn"
              :disabled="activePlanLoading"
              @click="playPlan(plan)"
            >
              <PlayCircle :size="14" />
              播放
            </button>
            <button
              v-if="canEditVisualisation && planStatusTone(plan) !== 'published'"
              type="button"
              class="sfx-vis__publish-btn"
              :disabled="publishingId === plan.plan_id"
              @click="publishOne(plan)"
            >
              <CheckCircle2 :size="14" />
              {{ publishingId === plan.plan_id ? '发布中…' : '发布' }}
            </button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.sfx-vis {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  min-height: 100%;
  background: var(--surface-canvas, #fafbfc);
}

.sfx-vis__bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-default, #e5e7eb);
}

.sfx-vis__back {
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

.sfx-vis__back:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis__title-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sfx-vis__title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sfx-vis__subtitle {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis__actions {
  display: flex;
  gap: 8px;
}

.sfx-vis__create-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.85rem;
  cursor: pointer;
}

.sfx-vis__create-btn:hover {
  background: var(--accent-primary-hover, #3b7be0);
}

/* 播放器区 */
.sfx-vis__player-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 10px;
}

.sfx-vis__player-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sfx-vis__player-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-vis__close-player {
  padding: 4px 10px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: none;
  font-size: 0.8rem;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis__close-player:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis__player-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-vis__player-state--error {
  color: var(--red-700, #c62828);
}

.sfx-vis__spinner {
  color: var(--accent-primary, #4f8cf7);
  animation: sfx-vis-spin 0.8s linear infinite;
}

@keyframes sfx-vis-spin {
  to { transform: rotate(360deg); }
}

/* 创建计划 */
.sfx-vis__create {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 10px;
}

.sfx-vis__create-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sfx-vis__create-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sfx-vis__close-create {
  padding: 4px 10px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: none;
  font-size: 0.8rem;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis__close-create:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis__create-state {
  padding: 12px;
  font-size: 0.85rem;
  color: var(--text-muted, #6b7280);
}

.sfx-vis__create-state--error {
  color: var(--red-700, #c62828);
}

.sfx-vis__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.sfx-vis__field-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.sfx-vis__label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis__select,
.sfx-vis__input,
.sfx-vis__textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: var(--surface-canvas, #fff);
  font-size: 0.85rem;
  font-family: inherit;
  color: var(--text-primary, #1f2937);
}

.sfx-vis__textarea {
  font-family: var(--font-mono, monospace);
  resize: vertical;
}

.sfx-vis__select:focus,
.sfx-vis__input:focus,
.sfx-vis__textarea:focus {
  outline: 2px solid var(--accent-primary, #4f8cf7);
  outline-offset: 1px;
}

.sfx-vis__create-error {
  margin: 0;
  padding: 6px 10px;
  font-size: 0.8rem;
  color: var(--red-700, #c62828);
  background: #fee2e2;
  border-radius: 6px;
}

.sfx-vis__create-actions {
  display: flex;
  justify-content: flex-end;
}

.sfx-vis__submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.85rem;
  cursor: pointer;
}

.sfx-vis__submit-btn:hover:not(:disabled) {
  background: var(--accent-primary-hover, #3b7be0);
}

.sfx-vis__submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 列表 */
.sfx-vis__list-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sfx-vis__list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sfx-vis__list-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sfx-vis__list-count {
  padding: 0 8px;
  border-radius: 999px;
  background: var(--surface-cool, #f0f0f0);
  color: var(--text-secondary, #6b7280);
  font-size: 0.75rem;
  font-weight: 500;
}

.sfx-vis__refresh {
  padding: 4px 12px;
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 6px;
  background: none;
  font-size: 0.8rem;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
}

.sfx-vis__refresh:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis__list-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 32px 16px;
  text-align: center;
  color: var(--text-muted, #6b7280);
}

.sfx-vis__list-state--error {
  color: var(--red-700, #c62828);
}

.sfx-vis__list-state--empty {
  color: var(--text-muted, #9ca3af);
}

.sfx-vis__retry {
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--ink-700, #1f2937);
}

.sfx-vis__retry:hover {
  background: var(--surface-cool, #f5f5f5);
}

.sfx-vis__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sfx-vis__plan {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  background: var(--surface-panel, #fff);
  border: 1px solid var(--border-default, #e5e7eb);
  border-radius: 8px;
}

.sfx-vis__plan-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sfx-vis__plan-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.sfx-vis__plan-status {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.sfx-vis__plan-status.tone-published {
  background: #d1fae5;
  color: #047857;
}

.sfx-vis__plan-status.tone-draft {
  background: #fef3c7;
  color: #b45309;
}

.sfx-vis__plan-status.tone-neutral {
  background: var(--surface-cool, #f0f0f0);
  color: var(--text-muted, #6b7280);
}

.sfx-vis__plan-algo {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--accent-primary, #4f8cf7);
}

.sfx-vis__plan-node {
  font-size: 0.75rem;
  color: var(--text-muted, #9ca3af);
}

.sfx-vis__plan-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.sfx-vis__plan-desc {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-secondary, #6b7280);
  line-height: 1.4;
}

.sfx-vis__plan-meta {
  margin: 0;
  font-size: 0.72rem;
  color: var(--text-muted, #9ca3af);
}

.sfx-vis__plan-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.sfx-vis__play-btn,
.sfx-vis__publish-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
}

.sfx-vis__play-btn {
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  border: none;
}

.sfx-vis__play-btn:hover:not(:disabled) {
  background: var(--accent-primary-hover, #3b7be0);
}

.sfx-vis__play-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sfx-vis__publish-btn {
  background: #fff;
  border-color: #a5d6a7;
  color: #2e7d32;
}

.sfx-vis__publish-btn:hover:not(:disabled) {
  background: #e8f5e9;
}

.sfx-vis__publish-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
