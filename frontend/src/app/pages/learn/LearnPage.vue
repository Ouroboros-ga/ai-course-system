<script setup>
import { computed, inject, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useLearningWorkspace } from '@/features/student-learning/composables/useLearningWorkspace.js'
import { useMediaPlayback } from '@/features/student-learning/composables/useMediaPlayback.js'
import { useAvatarPlayback } from '@/features/student-learning/composables/useAvatarPlayback.js'
import { usePlaylistPlayback } from '@/features/student-learning/composables/usePlaylistPlayback.js'
import { createLearnMachine, LEARN_STATES, SLICE_ENABLED_STATES } from '@/app/lib/learnMachine.js'
import { useCounterStore } from '@/stores/counter.js'
import LearningTrack from '@/app/components/learn/LearningTrack.vue'
import LectureStage from '@/app/components/learn/LectureStage.vue'
import LearningActionDock from '@/app/components/learn/LearningActionDock.vue'
import CourseAgentPanel from '@/app/components/learn/CourseAgentPanel.vue'
import CitationStage from '@/app/components/learn/CitationStage.vue'
import PracticePanel from '@/app/components/learn/PracticePanel.vue'
import VisualizationStage from '@/app/components/learn/VisualizationStage.vue'
import NoteStage from '@/app/components/learn/NoteStage.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
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
const media = useMediaPlayback(courseId)
const avatar = useAvatarPlayback()
const playlistPlayback = usePlaylistPlayback(media.playlist)

const mediaTotalPages = computed(() => {
  const manifestPages = media.ppt.value?.decks?.flatMap(deck => deck.pages || []) || []
  return Math.max(
    0,
    media.ppt.value?.pages?.at(-1)?.page ?? 0,
    ...manifestPages.map(page => Number(page.page) || 0),
  )
})

// 批次1：启用 PRACTICE（试一试）切片；批次4：启用 VISUALIZE（看可视化）切片
const machine = createLearnMachine({
  enabledStates: [...SLICE_ENABLED_STATES, LEARN_STATES.PRACTICE, LEARN_STATES.VISUALIZE, LEARN_STATES.NOTE, LEARN_STATES.VERIFY],
  initialState: LEARN_STATES.UNDERSTAND,
})
const learnState = ref(machine.state)
const branchContext = ref(null)
const dockRef = ref(null)

// 学习轨道收起状态（与 BuildLayout 一致：用户手动选择后按设备记忆）
const TRACK_STORAGE_KEY = 'sfx:rail:learn'
const readStoredTrack = () => {
  try { return localStorage.getItem(TRACK_STORAGE_KEY) === '1' } catch { return null }
}
const trackManualOverride = ref(readStoredTrack())
const trackCollapsed = computed(() =>
  trackManualOverride.value ?? ![LEARN_STATES.LEARN, LEARN_STATES.UNDERSTAND].includes(learnState.value)
)
function handleTrackToggle() {
  const next = !trackCollapsed.value
  trackManualOverride.value = next
  try { localStorage.setItem(TRACK_STORAGE_KEY, next ? '1' : '0') } catch {
    // A blocked storage quota should not disable the learning rail.
  }
}

const evidenceDocumentId = computed(
  () => detail.value?.course?.document_id ?? detail.value?.document?.document_id ?? null
)

function buildBranchContext(triggerAction) {
  const anchor = ws.captureReturnAnchor(triggerAction)
  // The workspace may expose playback time as either a ref or a scalar.
  const currentPlaybackTime = Number(ws.currentTime?.value ?? ws.currentTime ?? 0)
  return {
    sourceCourseId: courseId,
    sourceNodeId: ws.currentNodeId.value,
    sourceNodeIndex: anchor?.nodeIndex ?? ws.currentNodeIndex.value,
    sourceNodeTitle: ws.currentNode.value?.title ?? '',
    sourceSectionId: ws.currentNode.value?.section_id ?? null,
    learningGoal: ws.currentNode.value?.learning_goal ?? '',
    completionCondition: '完成当前教学行动后返回原学习位置',
    sourcePage: anchor?.currentPage ?? ws.currentPage.value,
    sourceTime: anchor?.currentTime ?? currentPlaybackTime,
    triggerAction,
    returnTarget: {
      nodeIndex: anchor?.nodeIndex ?? ws.currentNodeIndex.value,
      page: anchor?.currentPage ?? ws.currentPage.value,
      time: anchor?.currentTime ?? currentPlaybackTime,
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
function handleNodeChange(direction) {
  ws.selectNode(ws.currentNodeIndex.value + Number(direction), { play: ws.isPlaying.value })
}
function handlePlaylistNext() {
  if (!playlistPlayback.next()) return
  const item = playlistPlayback.activeItem.value
  if (item?.nodeId != null) {
    const index = ws.nodes.value.findIndex(node => String(node.id) === String(item.nodeId))
    if (index >= 0) ws.selectNode(index, { play: true })
  }
}
function handlePlaylistPrevious() {
  if (!playlistPlayback.previous()) return
  const item = playlistPlayback.activeItem.value
  if (item?.nodeId != null) {
    const index = ws.nodes.value.findIndex(node => String(node.id) === String(item.nodeId))
    if (index >= 0) ws.selectNode(index, { play: true })
  }
}
function handleAgentAction(action) { handleDockAction({ id: action, target: action === 'visualize' ? LEARN_STATES.VISUALIZE : LEARN_STATES.PRACTICE }) }

onMounted(async () => {
  await Promise.all([ws.load(), media.load()])
})

watch(
  [() => media.avatarCues.value, () => media.digitalHumanManifest.value, () => playlistPlayback.activeItem.value?.avatarCues],
  ([avatarCues, digitalHumanManifest, playlistAvatarCues]) => {
    avatar.load({ avatarCues: playlistAvatarCues || avatarCues, digitalHumanManifest })
  },
  { immediate: true },
)
</script>

<template>
  <div class="sfx-learn">
    <SfxSkeleton v-if="ws.status.value === 'loading'" :lines="4" block />

    <SfxError
      v-else-if="ws.status.value === 'error'"
      :description="ws.error.value || '课程内容加载失败，请稍后重试。'"
      @retry="ws.load"
    />

    <SfxError
      v-else-if="ws.status.value === 'empty'"
      variant="unavailable"
      title="课程学习内容尚未就绪"
      :description="ws.error.value || '该课程当前没有可学习的讲解节点。'"
      :retryable="false"
    />

    <template v-else>
      <div class="sfx-learn-body">
        <LearningTrack
          :nodes="ws.nodes.value"
          :current-index="ws.currentNodeIndex.value"
          :completed-ids="ws.completedNodes.value"
          :collapsed="trackCollapsed"
          @select="(i) => ws.selectNode(i, { play: false })"
          @toggle="handleTrackToggle"
        />

        <main class="sfx-learn-stage">
          <LectureStage
            v-if="![LEARN_STATES.CITATION, LEARN_STATES.VISUALIZE, LEARN_STATES.NOTE].includes(learnState)"
            :current-node="ws.currentNode.value"
            :current-time="ws.currentTime.value"
            :current-slide="ws.currentSlide.value"
            :current-ppt-page="ws.currentPptPage.value"
            :current-page="ws.currentPage.value"
            :total-pages="Math.max(ws.totalPages.value, mediaTotalPages)"
            :is-playing="ws.isPlaying.value"
            :playback-rate="ws.playbackRate.value"
            :volume="ws.volume.value"
            :is-muted="ws.isMuted.value"
            :captions-enabled="ws.captionsEnabled.value"
            :audio-url="media.audioUrl.value"
            :playlist="media.playlist.value"
            :playlist-index="playlistPlayback.activeIndex.value"
            :duration="media.manifest.value.durationMs / 1000"
            :subtitle-segments="media.subtitleSegments.value"
            :ppt-timeline="media.pptTimeline.value"
            :ppt-manifest="media.ppt.value"
            :avatar-cues="avatar.cues.value"
            :avatar-sprite-manifest="avatar.spriteManifest.value"
            :avatar-asset-source="avatar.assetSource.value"
            :default-playback-mode="media.manifest.value.defaultPlaybackMode"
            :media-status="media.status.value"
            :media-message="media.manifest.value.message || media.error.value"
            :legacy-video-url="ws.currentVideoUrl.value"
            @playback="handlePlayback"
            @page-change="ws.setPage"
            @node-change="handleNodeChange"
            @playlist-next="handlePlaylistNext"
            @playlist-previous="handlePlaylistPrevious"
            @rate-change="ws.playbackRate.value = $event"
            @volume-change="ws.volume.value = $event"
            @mute-change="ws.isMuted.value = $event"
            @captions-change="ws.captionsEnabled.value = $event"
          >
            <template v-if="learnState === LEARN_STATES.UNDERSTAND" #secondary>
              <CourseAgentPanel
                :ws="ws"
                :anchor="branchContext"
                @exit="exitBranch"
                @action="handleAgentAction"
              />
            </template>
          </LectureStage>

          <CitationStage
            v-else-if="learnState === LEARN_STATES.CITATION"
            :course-id="courseId"
            :document-id="evidenceDocumentId"
            :preview="previewMode"
            @exit="exitBranch"
          />

          <VisualizationStage
            v-else-if="learnState === LEARN_STATES.VISUALIZE"
            :course-id="courseId"
            :node-id="ws.currentNodeId.value"
            :node-title="ws.currentNode.value?.title || ''"
            :preview="previewMode"
            @exit="exitBranch"
          />
          <NoteStage v-else-if="learnState === LEARN_STATES.NOTE" :ws="ws" :anchor="branchContext" @exit="exitBranch" />
        </main>

        <PracticePanel
          v-if="learnState === LEARN_STATES.PRACTICE"
          :course-id="courseId"
          :node-index="ws.currentNodeIndex.value"
          @exit="exitBranch"
        />
      </div>

      <LearningActionDock
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
