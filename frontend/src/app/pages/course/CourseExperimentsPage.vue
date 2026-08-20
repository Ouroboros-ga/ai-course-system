<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { FlaskConical, Server } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import { listPublishedExperiments } from '@/api/experiments.js'
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
    selectedExperiment.value = experiments.value[0] ?? null
  } catch (error) {
    // 错误由空状态展示
  }
}

// 切换实验
function handleExperimentChange(e) {
  const expId = e.target.value
  selectedExperiment.value = experiments.value.find(exp => exp.experiment_id === expId) || null
}

const sandboxTooltip = computed(() => {
  if (sandboxLoading.value) return '沙箱状态检测中…'
  if (sandboxAvailable.value) return `沙箱可用 · 支持 ${languages.length} 种语言`
  return '沙箱暂不可用，提交评测可能失败'
})

onMounted(async () => {
  await loadSandbox()
  await loadExperiments()
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
      <!-- 实验选择器 -->
      <div class="experiment-selector">
        <label class="selector-label">
          <span class="selector-text">选择实验</span>
          <select
            :value="selectedExperiment?.experiment_id"
            class="selector-select"
            @change="handleExperimentChange"
          >
            <option
              v-for="item in experiments"
              :key="item.experiment_id"
              :value="item.experiment_id"
            >
              {{ item.title }}
            </option>
          </select>
        </label>
      </div>

      <!-- 代码工作台 -->
      <div class="workbench-container">
        <CodeWorkbench
          v-if="selectedExperiment"
          :experiment="selectedExperiment"
          :course-id="courseContext.courseId"
          :languages="languages"
          mode="both"
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

.experiment-selector {
  flex-shrink: 0;
}

.selector-label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.selector-text {
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  font-weight: 500;
}

.selector-select {
  width: 320px;
  padding: 8px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  color: var(--text-primary);
  font-size: var(--ui-md-size);
  cursor: pointer;
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.selector-select:focus {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 2px var(--ink-100);
}

.workbench-container {
  flex: 1;
  min-height: 0;
}

/* 移动端（design.md §12.5）：选择器满宽，页面留白收窄 */
@media (max-width: 760px) {
  .experiments-page {
    padding: var(--space-4) var(--space-3);
  }

  .selector-select {
    width: 100%;
    max-width: 320px;
  }
}
</style>
