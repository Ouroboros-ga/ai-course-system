<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { FlaskConical, Server } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import { listPublishedExperiments } from '@/api/experiments.js'
import { getActiveKnowledgeGraph } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import TeacherExperimentPanel from '@/app/components/course/TeacherExperimentPanel.vue'
import CodeWorkbench from '@/components/codebench/CodeWorkbench.vue'

const courseContext = inject('courseContext')
const isTeacher = computed(() => Boolean(courseContext.allowed.value['course.edit']))

// 沙箱状态
const sandboxAvailable = ref(false)
const sandboxLoading = ref(true)
const languages = ref([])

// 实验列表
const experiments = ref([])
const selectedExperiment = ref(null)
// F2 §16.1：状态筛选器（待完成｜进行中｜已完成）
const statusFilter = ref('todo')
const filterTabs = [
  { key: 'todo', label: '待完成' },
  { key: 'in_progress', label: '进行中' },
  { key: 'done', label: '已完成' },
]
// 关联知识点标题（与出题页同一知识图谱数据源；失败仅回退计数）
const knowledgeTitles = ref({})

// 加载沙箱
async function loadSandbox() {
  sandboxLoading.value = true
  try {
    const [health, supported] = await Promise.all([
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
    ])
    sandboxAvailable.value = health?.available === true
    languages.value = Array.isArray(supported?.languages) ? supported.languages : []
  } catch {
    sandboxAvailable.value = false
  } finally {
    sandboxLoading.value = false
  }
}

// 加载实验列表
async function loadExperiments() {
  if (isTeacher.value) return
  try {
    const result = await listPublishedExperiments(courseContext.courseId.value)
    experiments.value = result?.items ?? []
    if (!experiments.value.some((item) => item.experiment_id === selectedExperiment.value?.experiment_id)) {
      selectedExperiment.value = experiments.value[0] ?? null
    }
  } catch (error) {
    // 错误由空状态展示
  }
}

async function loadKnowledgeTitles() {
  try {
    const data = await getActiveKnowledgeGraph(courseContext.courseId.value)
    const raw = data?.nodes ?? data?.items ?? []
    const map = {}
    for (const node of (Array.isArray(raw) ? raw : [])) {
      const id = Number(node?.id ?? node?.node_id)
      const title = String(node?.title ?? node?.label ?? node?.node_key ?? '')
      if (Number.isInteger(id) && title) map[id] = title
    }
    knowledgeTitles.value = map
  } catch {
    knowledgeTitles.value = {}
  }
}

function summaryOf(item) {
  return item?.student_summary || null
}

function bucketOf(item) {
  return summaryOf(item)?.bucket || 'todo'
}

const statusCounts = computed(() => {
  const counts = { todo: 0, in_progress: 0, done: 0 }
  for (const item of experiments.value) {
    const bucket = bucketOf(item)
    if (counts[bucket] === undefined) counts.todo += 1
    else counts[bucket] += 1
  }
  return counts
})

const filteredExperiments = computed(() =>
  experiments.value.filter((item) => bucketOf(item) === statusFilter.value),
)

function knowledgeNames(item) {
  const ids = item?.knowledge_node_ids || []
  if (!ids.length) return '未关联知识点'
  const names = ids.map((id) => knowledgeTitles.value[id]).filter(Boolean)
  if (!names.length) return `已关联 ${ids.length} 个知识点`
  return names.join('、')
}

function attemptsText(item) {
  const used = summaryOf(item)?.attempts_used ?? 0
  return `已尝试 ${used}/${item?.max_attempts ?? '-'} 次`
}

const OUTCOME_TEXT = {
  accepted: '通过',
  wrong_answer: '未通过',
  compilation_error: '编译失败',
  runtime_error: '运行错误',
  time_limit_exceeded: '超时',
  memory_limit_exceeded: '内存超限',
  sandbox_unavailable: '沙箱不可用',
  pending: '运行中',
  processing: '运行中',
}

function latestOutcome(item) {
  return summaryOf(item)?.latest_outcome || ''
}

function outcomeText(item) {
  const outcome = latestOutcome(item)
  if (!outcome) return '未运行'
  const summary = summaryOf(item)
  const detail = summary?.latest_total_count
    ? ` ${summary.latest_passed_count ?? 0}/${summary.latest_total_count}`
    : ''
  return `${OUTCOME_TEXT[outcome] || outcome}${detail}`
}

function outcomeTone(item) {
  const outcome = latestOutcome(item)
  if (!outcome) return 'ink'
  if (outcome === 'accepted') return 'green'
  if (outcome === 'pending' || outcome === 'processing' || outcome === 'sandbox_unavailable') return 'amber'
  return 'red'
}

function hasStarted(item) {
  return (summaryOf(item)?.attempts_used ?? 0) > 0
}

// 切换实验
function selectExperiment(item) {
  selectedExperiment.value = item || null
}

// 提交完成后刷新聚合（尝试计数与最近结果会变）
async function handleSubmitComplete() {
  await loadExperiments()
}

const sandboxTooltip = computed(() => {
  if (sandboxLoading.value) return '沙箱状态检测中…'
  if (sandboxAvailable.value) return `沙箱可用 · 支持 ${languages.length} 种语言`
  return '沙箱暂不可用，提交评测可能失败'
})

onMounted(async () => {
  await loadSandbox()
  await loadExperiments()
  await loadKnowledgeTitles()
})

onBeforeUnmount(() => {
  // 清理
})
</script>

<template>
  <div class="sfx-page experiments-page">
    <!-- 页面头部 -->
    <header class="sfx-page-header">
      <div class="header-left">
        <h1 class="sfx-t-title1">课程实验</h1>
        <!-- 沙箱状态小标识 -->
        <div
          class="sandbox-indicator"
          :class="{
            'is-available': sandboxAvailable && !sandboxLoading,
            'is-unavailable': !sandboxAvailable && !sandboxLoading,
            'is-loading': sandboxLoading,
          }"
          :title="sandboxTooltip"
        >
          <Server :size="13" :stroke-width="1.8" />
        </div>
      </div>
      <SfxCapabilityTag level="experimental" />
    </header>

    <!-- 教师端 -->
    <TeacherExperimentPanel v-if="isTeacher" />

    <!-- 学生端 - 实验工作台（占满剩余高度） -->
    <div v-else-if="experiments.length" class="experiment-workbench-area">
      <!-- 状态筛选器（page-design §16.1：待完成｜进行中｜已完成） -->
      <div class="experiment-filter" role="tablist" aria-label="按状态筛选实验">
        <SfxButton
          v-for="tab in filterTabs"
          :key="tab.key"
          role="tab"
          :aria-selected="statusFilter === tab.key"
          :variant="statusFilter === tab.key ? 'secondary' : 'tertiary'"
          size="sm"
          @click="statusFilter = tab.key"
        >
          {{ tab.label }}（{{ statusCounts[tab.key] }}）
        </SfxButton>
      </div>

      <!-- 实验条目 -->
      <div v-if="filteredExperiments.length" class="experiment-entries">
        <article
          v-for="item in filteredExperiments"
          :key="item.experiment_id"
          class="experiment-entry"
          :class="{ 'is-selected': selectedExperiment?.experiment_id === item.experiment_id }"
        >
          <div class="entry-main">
            <div class="entry-title">{{ item.title }}</div>
            <div class="entry-meta">
              {{ knowledgeNames(item) }} · {{ (item.language_whitelist || []).join('、') || '—' }}
            </div>
            <div class="entry-status">
              <span class="entry-progress">{{ attemptsText(item) }}</span>
              <SfxBadge :tone="outcomeTone(item)">{{ outcomeText(item) }}</SfxBadge>
            </div>
          </div>
          <SfxButton
            size="sm"
            :variant="selectedExperiment?.experiment_id === item.experiment_id ? 'primary' : 'secondary'"
            @click="selectExperiment(item)"
          >
            {{ hasStarted(item) ? '继续' : '开始' }}
          </SfxButton>
        </article>
      </div>
      <SfxEmpty
        v-else
        title="该状态下暂无实验"
        description="切换其他状态筛选查看，或等待教师发布新的实验。"
      >
        <template #icon><FlaskConical :size="20" :stroke-width="1.9" /></template>
      </SfxEmpty>

      <!-- 代码工作台 -->
      <div class="workbench-container">
        <CodeWorkbench
          v-if="selectedExperiment"
          :experiment="selectedExperiment"
          :course-id="courseContext.courseId"
          :languages="languages"
          mode="both"
          @submit-complete="handleSubmitComplete"
        />
      </div>
    </div>

    <!-- 空状态 -->
    <SfxEmpty
      v-else-if="!isTeacher"
      title="暂无已发布实验"
      description="教师完成版本、测试、参考解预览和锁定后，实验会显示在这里。"
    >
      <template #icon><FlaskConical :size="20" :stroke-width="1.9" /></template>
    </SfxEmpty>
  </div>
</template>

<style scoped>
.experiments-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: var(--space-6) var(--space-8);
  gap: var(--space-4);
  /* 页面整体不滚动，内部工作台独立滚动（design.md §5 三层滚动模型） */
  overflow: hidden;
}

/* 页面头部 */
.sfx-page-header {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.header-left h1 {
  margin: 0;
}

/* 沙箱状态小标识 */
.sandbox-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--surface-soft);
  border: 1px solid var(--border-default);
  cursor: help;
  transition: all var(--duration-fast) var(--ease-out);
}

.sandbox-indicator.is-loading {
  color: var(--text-muted);
}

.sandbox-indicator.is-available {
  color: var(--green-500);
  border-color: rgba(94, 140, 97, 0.4);
  background: rgba(94, 140, 97, 0.08);
}

.sandbox-indicator.is-unavailable {
  color: var(--amber-500);
  border-color: rgba(198, 139, 44, 0.4);
  background: rgba(198, 139, 44, 0.08);
}

/* 工作台区域 */
.experiment-workbench-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.experiment-filter {
  flex-shrink: 0;
  display: flex;
  gap: var(--space-2);
}

.experiment-entries {
  flex-shrink: 0;
  display: grid;
  gap: var(--space-2);
  max-height: 220px;
  overflow-y: auto;
}

.experiment-entry {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
}

.experiment-entry.is-selected {
  border-color: var(--color-brand);
  background: var(--color-brand-soft);
}

.entry-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.entry-title {
  font-weight: 600;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-meta {
  font-size: var(--caption-size);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.entry-progress {
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.workbench-container {
  flex: 1;
  min-height: 0;
}

/* 移动端（design.md §12.5）：页面留白收窄，条目纵排 */
@media (max-width: 760px) {
  .experiments-page {
    padding: var(--space-4) var(--space-3);
  }

  .experiment-entry {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
