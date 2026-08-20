<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  BookOpen, ChevronLeft, ClipboardCheck, ListChecks, MoreHorizontal,
  PanelLeftOpen, Play, Save, UploadCloud
} from 'lucide-vue-next'
import CoursePipelineNav from '../components/CoursePipelineNav.vue'
import PipelineWorkArea from '../components/PipelineWorkArea.vue'
import QualityGatePanel from '../components/QualityGatePanel.vue'
import { teacherCourseMock } from '../mock/frontendDesignMocks.js'
import '../styles/frontend-design.css'

const router = useRouter()
const course = ref(structuredClone(teacherCourseMock))
const activeKey = ref('script')
const activeBlockId = ref('script-2')
const inspectorTab = ref('quality')
const compactInitial = window.innerWidth < 1100
const pipelineOpen = ref(!compactInitial)
const inspectorOpen = ref(!compactInitial)
const toast = ref('')
let taskTimer
let toastTimer

const activeStep = computed(() => course.value.steps.find((step) => step.key === activeKey.value))
const publishBlocked = computed(() => {
  const hasBlockingCheck = course.value.checks.some((check) => check.severity === 'blocker' && !check.resolved)
  const requiredSteps = ['script', 'mapping', 'audio', 'avatar', 'preview']
  const hasIncompleteStep = course.value.steps.some((step) => requiredSteps.includes(step.key) && step.status !== 'confirmed')
  return hasBlockingCheck || hasIncompleteStep
})
const publishBlockReason = computed(() => publishBlocked.value ? '仍有待确认或未完成的生产步骤' : '发布当前课程版本')

const selectStep = (step) => {
  activeKey.value = step.key
  if (window.innerWidth < 1100) pipelineOpen.value = false
}

const openStep = (key) => {
  activeKey.value = key
  if (window.innerWidth < 1100) inspectorOpen.value = false
}

const updateBlock = ({ id, text }) => {
  const block = course.value.scriptBlocks.find((item) => item.id === id)
  if (!block) return
  block.text = text
  block.review = 'review_required'
  activeStep.value.status = 'review_required'
  activeStep.value.meta = '存在未确认修改'
}

const showToast = (message) => {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2200)
}

const regenerate = (id) => {
  const block = course.value.scriptBlocks.find((item) => item.id === id)
  if (!block) return
  block.review = 'review_required'
  activeBlockId.value = id
  showToast('已模拟局部重新生成；下游映射与音频需重新检查')
}

const confirmStep = () => {
  activeStep.value.status = 'confirmed'
  activeStep.value.meta = '教师刚刚确认'
  course.value.scriptBlocks.forEach((block) => { block.review = 'confirmed' })
  course.value.checks
    .filter((check) => check.step === activeKey.value)
    .forEach((check) => { check.resolved = true })
  showToast('当前版本已标记为教师确认')
}

const retryTask = (taskId = 'task-audio-1') => {
  const task = course.value.tasks.find((item) => item.id === taskId)
  if (!task || task.status === 'running') return
  task.status = 'running'
  task.progress = 12
  task.error = ''
  task.retryable = false
  const step = course.value.steps.find((item) => item.key === 'audio')
  step.status = 'processing'
  step.meta = '生成中 12%'
  inspectorTab.value = 'log'
  inspectorOpen.value = true
  clearInterval(taskTimer)
  taskTimer = window.setInterval(() => {
    task.progress = Math.min(100, task.progress + 22)
    step.meta = '生成中 ' + task.progress + '%'
    if (task.progress >= 100) {
      clearInterval(taskTimer)
      task.status = 'review_required'
      step.status = 'review_required'
      step.meta = '待确认 1'
      showToast('音频生成完成，仍需教师试听确认')
    }
  }, 450)
}

onBeforeUnmount(() => {
  clearInterval(taskTimer)
  clearTimeout(toastTimer)
})
</script>

<template>
  <div class="fd-workspace fd-teacher-workspace">
    <header class="fd-workspace-topbar">
      <div class="fd-topbar__context">
        <button class="fd-icon-button" type="button" aria-label="返回课程列表" @click="router.push('/app/courses/building')"><ChevronLeft :size="19" /></button>
        <span class="fd-course-icon"><BookOpen :size="18" /></span>
        <div>
          <strong>{{ course.name }}</strong>
          <span>{{ course.version }}</span>
        </div>
        <span class="fd-prototype-mark">设计原型 · Mock 数据</span>
      </div>
      <div class="fd-topbar__actions">
        <span class="fd-saved-state"><Save :size="14" />{{ course.savedAt }}</span>
        <button class="fd-topbar-button" type="button" :aria-expanded="pipelineOpen" @click="pipelineOpen = !pipelineOpen"><ListChecks :size="17" /><span>流程</span></button>
        <button class="fd-topbar-button" type="button" :aria-expanded="inspectorOpen" @click="inspectorOpen = !inspectorOpen"><ClipboardCheck :size="17" /><span>检查</span></button>
        <button class="fd-secondary-button" type="button" @click="showToast('已打开学生视角预览（Mock）')"><Play :size="16" />预览课程</button>
        <button class="fd-primary-button" type="button" :disabled="publishBlocked" :title="publishBlockReason">发布</button>
        <button class="fd-icon-button" type="button" aria-label="更多课程操作"><MoreHorizontal :size="19" /></button>
      </div>
    </header>

    <div class="fd-workspace-body" :class="{ 'is-left-collapsed': !pipelineOpen, 'is-right-collapsed': !inspectorOpen }">
      <div v-if="pipelineOpen || inspectorOpen" class="fd-drawer-mask" @click="pipelineOpen = false; inspectorOpen = false"></div>

      <CoursePipelineNav
        v-if="pipelineOpen"
        :steps="course.steps"
        :active-key="activeKey"
        :mobile="true"
        @select="selectStep"
        @close="pipelineOpen = false"
      />
      <div v-else class="fd-collapsed-rail fd-collapsed-rail--left">
        <button type="button" aria-label="展开制作流程" @click="pipelineOpen = true"><PanelLeftOpen :size="18" /></button>
      </div>

      <PipelineWorkArea
        :step="activeStep"
        :chapters="course.chapters"
        :script-blocks="course.scriptBlocks"
        :active-block-id="activeBlockId"
        @select-block="activeBlockId = $event"
        @update-block="updateBlock"
        @regenerate="regenerate"
        @retry-task="retryTask"
        @confirm-step="confirmStep"
      />

      <QualityGatePanel
        v-if="inspectorOpen"
        v-model:active-tab="inspectorTab"
        :checks="course.checks"
        :tasks="course.tasks"
        :active-step="activeStep"
        :mobile="true"
        @retry-task="retryTask"
        @open-step="openStep"
        @close="inspectorOpen = false"
      />
      <div v-else class="fd-collapsed-rail fd-collapsed-rail--right">
        <button type="button" aria-label="展开质量检查" @click="inspectorOpen = true"><ClipboardCheck :size="18" /></button>
      </div>
    </div>

    <footer class="fd-task-dock">
      <div>
        <UploadCloud :size="17" />
        <span>长任务</span>
        <strong>文档解析 · 算法设计与分析.pdf</strong>
      </div>
      <div class="fd-task-dock__progress">
        <div class="fd-progress-line"><i style="width: 65%"></i></div>
        <span>65% · 预计剩余 8 分钟</span>
      </div>
      <button class="fd-text-button" type="button" @click="inspectorTab = 'log'; inspectorOpen = true">查看任务日志</button>
    </footer>

    <p v-if="toast" class="fd-toast" role="status">{{ toast }}</p>
  </div>
</template>
