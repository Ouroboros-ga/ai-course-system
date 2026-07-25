<script setup>
import { computed, inject, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLearningWorkspace } from '@/features/student-learning/composables/useLearningWorkspace.js'
import { createLearnMachine, LEARN_STATES, SLICE_ENABLED_STATES } from '@/app/lib/learnMachine.js'
import { useCounterStore } from '@/stores/counter.js'
import LearnContextBar from '@/app/components/learn/LearnContextBar.vue'
import LearningTrack from '@/app/components/learn/LearningTrack.vue'
import LectureStage from '@/app/components/learn/LectureStage.vue'
import LearningActionDock from '@/app/components/learn/LearningActionDock.vue'
import CourseAgentPanel from '@/app/components/learn/CourseAgentPanel.vue'
import CitationStage from '@/app/components/learn/CitationStage.vue'
import PracticePanel from '@/app/components/learn/PracticePanel.vue'
import VisualizationStage from '@/app/components/learn/VisualizationStage.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()
const { courseRole, detail, analyticsEligible, capabilities } = inject('courseContext')

const courseId = Number(route.params.courseId)
const previewMode = computed(() => ['owner', 'teacher', 'teaching_assistant'].includes(courseRole.value))

// TeachingAgent 受控接入（P1）：将 courseContext 的 analyticsEligible/capabilities
// 与当前用户 ID 以 getter 形式注入 workspace。workspace 在 sendQuestion 时读取最新值，
// 仅当 cognitive_analysis 能力开关开启 + analyticsEligible（真实学生）+ studentId
// 三者齐备时尝试 TeachingAgent，否则直接走 V1 /chat/ask（AGENTS.md 硬约束）。
const ws = useLearningWorkspace(courseId, {
  previewMode: previewMode.value,
  getStudentId: () => counter.userData?.id ?? null,
  getAnalyticsEligible: () => analyticsEligible.value,
  getCapabilities: () => capabilities.value,
})

// 批次1：启用 PRACTICE（试一试）切片；批次4：启用 VISUALIZE（看可视化）切片
const machine = createLearnMachine({
  enabledStates: [...SLICE_ENABLED_STATES, LEARN_STATES.PRACTICE, LEARN_STATES.VISUALIZE],
})
const learnState = ref(machine.state)
const branchContext = ref(null)
const dockRef = ref(null)

const isFullscreen = ref(false)
function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

const trackManualOverride = ref(null)
const trackCollapsed = computed(() =>
  trackManualOverride.value ?? (learnState.value !== LEARN_STATES.LEARN)
)

const evidenceDocumentId = computed(
  () => detail.value?.course?.document_id ?? detail.value?.document?.document_id ?? null
)

function buildBranchContext(triggerAction) {
  const anchor = ws.captureReturnAnchor(triggerAction)
  return {
    sourceCourseId: courseId,
    sourceNodeId: ws.currentNodeId.value,
    sourceNodeIndex: anchor?.nodeIndex ?? ws.currentNodeIndex.value,
    sourceNodeTitle: ws.currentNode.value?.title ?? '',
    sourcePage: anchor?.currentPage ?? ws.currentPage.value,
    sourceTime: anchor?.currentTime ?? ws.currentTime.value,
    triggerAction,
    returnTarget: {
      nodeIndex: anchor?.nodeIndex ?? ws.currentNodeIndex.value,
      page: anchor?.currentPage ?? ws.currentPage.value,
      time: anchor?.currentTime ?? ws.currentTime.value,
    },
  }
}

function handleDockAction(action) {
  if (learnState.value === action.target) {
    exitBranch()
    return
  }
  if (learnState.value === LEARN_STATES.LEARN) {
    // 进入分支：先锚定当前课程位置（§12.11），再迁移状态
    const result = machine.enter(action.target, buildBranchContext(action.id))
    if (!result.ok) return
    learnState.value = result.state
    branchContext.value = result.branchContext
    return
  }
  // 分支 → 分支：保留最初返回点
  const result = machine.enter(action.target)
  if (result.ok) {
    learnState.value = result.state
    branchContext.value = result.branchContext
  }
}

// 返回课程：恢复到进入分支前的知识点 / 页码 / 播放位置（§4.6/§12.11）
// C1 修复：退出分支后焦点回到工具坞触发区
async function exitBranch() {
  const wasUnderstand = learnState.value === LEARN_STATES.UNDERSTAND
  const result = machine.exit()
  learnState.value = result.state
  branchContext.value = null
  ws.restoreReturnAnchor()
  if (wasUnderstand) {
    await nextTick()
    dockRef.value?.focus()
  }
}

function handlePlayback(payload) {
  ws.updatePlayback(payload)
}

onMounted(() => {
  ws.load()
})
</script>

<template>
  <div class="sfx-learn" :class="{ 'is-fullscreen': isFullscreen }">
    <LearnContextBar
      :course-title="ws.course.value?.courseTitle || ''"
      :node-title="ws.currentNode.value?.title || ''"
      :current-page="ws.currentPage.value"
      :total-pages="ws.totalPages.value"
      :save-state="ws.saveState.value"
      :preview="previewMode"
      @back="router.push(`/app/course/${courseId}/overview`)"
      @fullscreen="toggleFullscreen"
    />

    <SfxSkeleton v-if="ws.status.value === 'loading'" :lines="4" block />

    <SfxError
      v-else-if="ws.status.value === 'error'"
      :description="ws.error.value || '课程内容加载失败，请稍后重试。'"
      @retry="ws.load"
    />

    <template v-else>
      <div class="sfx-learn-body">
        <LearningTrack
          v-if="!isFullscreen"
          :nodes="ws.nodes.value"
          :current-index="ws.currentNodeIndex.value"
          :completed-ids="ws.completedNodes.value"
          :collapsed="trackCollapsed"
          @select="(i) => ws.selectNode(i, { play: false })"
          @toggle="trackManualOverride = !trackCollapsed"
        />

        <main class="sfx-learn-stage">
          <LectureStage
            v-if="learnState !== LEARN_STATES.CITATION && learnState !== LEARN_STATES.VISUALIZE"
            :current-node="ws.currentNode.value"
            :current-video-url="ws.currentVideoUrl.value"
            :current-slide="ws.currentSlide.value"
            :current-ppt-page="ws.currentPptPage.value"
            :current-page="ws.currentPage.value"
            :total-pages="ws.totalPages.value"
            :is-playing="ws.isPlaying.value"
            @playback="handlePlayback"
            @page-change="ws.setPage"
          />

          <CitationStage
            v-else-if="learnState === LEARN_STATES.CITATION"
            :document-id="evidenceDocumentId"
            @exit="exitBranch"
          />

          <VisualizationStage
            v-else-if="learnState === LEARN_STATES.VISUALIZE"
            :course-id="courseId"
            :node-id="ws.currentNodeId.value"
            :node-title="ws.currentNode.value?.title || ''"
            @exit="exitBranch"
          />
        </main>

        <CourseAgentPanel
          v-if="learnState === LEARN_STATES.UNDERSTAND"
          :ws="ws"
          :anchor="branchContext"
          @exit="exitBranch"
        />

        <PracticePanel
          v-if="learnState === LEARN_STATES.PRACTICE"
          :course-id="courseId"
          :node-index="ws.currentNodeIndex.value"
          @exit="exitBranch"
        />
      </div>

      <LearningActionDock
        v-if="!isFullscreen"
        ref="dockRef"
        :current-state="learnState"
        :enabled-states="machine.isEnabled"
        @action="handleDockAction"
      />
    </template>
  </div>
</template>

<style scoped>
.sfx-learn {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* §12.12 全屏讲解：覆盖整个视口，隐藏 L1/L2/工具坞（由 v-if 控制），
   舞台独占，保留极简退出（ContextBar 的全屏按钮） */
.sfx-learn.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: var(--surface-canvas);
}

.sfx-learn-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.sfx-learn-stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  transition: margin var(--duration-normal) var(--ease-out);
}
</style>
