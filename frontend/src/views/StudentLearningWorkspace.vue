<template>
  <div class="student-learning-workspace">
    <a class="sl-skip-link" href="#learning-stage">跳到学习内容</a>

    <div v-if="status === 'loading'" class="sl-page-state" role="status">
      <LoaderCircle :size="30" class="sl-spin" />
      <strong>正在恢复课程与学习进度</strong>
      <p>加载课件、讲解节点和上次学习位置…</p>
    </div>

    <div v-else-if="status === 'error'" class="sl-page-state sl-page-state--error">
      <TriangleAlert :size="34" />
      <strong>课程学习空间暂时无法打开</strong>
      <p>{{ error }}</p>
      <div>
        <button type="button" @click="load">重新加载</button>
        <button type="button" class="secondary" @click="goBack">返回课程</button>
      </div>
    </div>

    <template v-else-if="course">
      <LearningWorkspaceHeader
        :course-title="course.courseTitle"
        :node-title="currentNode?.title"
        :mode="mode"
        :progress="progressPercent"
        :save-state="saveState"
        :outline-open="outlineOpen"
        :assistant-open="assistantOpen"
        :notes-open="notesOpen"
        @back="goBack"
        @mode-change="switchMode"
        @toggle-panel="handlePanelToggle"
      />

      <div
        class="sl-workspace-layout"
        :class="{
          'has-outline': outlineOpen && !isCompact,
          'has-assistant': assistantOpen && !isCompact,
          'has-notes': notesOpen && !isCompact,
        }"
      >
        <CourseOutlineRail
          v-if="outlineOpen && !isCompact"
          :nodes="nodes"
          :current-node-index="currentNodeIndex"
          :completed-nodes="completedNodes"
          @select="selectNode"
          @close="setPanel('outline', false)"
        />

        <section id="learning-stage" class="sl-stage-column" aria-label="主要学习区域">
          <LearningMediaStage
            :mode="mode"
            :current-node="currentNode"
            :current-time="currentTime"
            :current-page="currentPage"
            :current-slide="currentSlide"
            :current-ppt-page="currentPptPage"
            :current-video-url="currentVideoUrl"
            :total-pages="totalPages"
            :total-duration="course.totalDuration"
            :is-playing="isPlaying"
            :playback-rate="playbackRate"
            :volume="volume"
            :is-muted="isMuted"
            :captions-enabled="captionsEnabled"
            @update-playback="updatePlayback"
            @seek="seekTo"
            @page-change="setPage"
            @rate-change="playbackRate = $event"
            @volume-change="volume = $event"
            @mute-change="isMuted = $event"
            @captions-change="captionsEnabled = $event"
            @media-error="mediaError = $event"
          />

          <LearningNotesPanel
            v-if="notesOpen && !isCompact"
            v-model="currentNote"
            :node-title="currentNode?.title"
            :page="currentPage"
            :time="currentTime"
            :sync-error="noteSyncError"
            :finishing="noteFinishing"
            :finished-anchor="lastFinishedNoteAnchor"
            :current-anchor="noteAnchorKey"
            @finish="handleFinishNote"
            @dismiss-error="clearNoteSyncError"
          />
        </section>

        <LearningAssistantPanel
          v-if="assistantOpen && !isCompact"
          :messages="messages"
          :draft="questionDraft"
          :is-asking="isAsking"
          @update:draft="questionDraft = $event"
          @ask="sendQuestion"
          @close="setPanel('assistant', false)"
        />
      </div>

      <nav v-if="isCompact" class="sl-mobile-dock" aria-label="学习工具">
        <button type="button" @click="openMobilePanel('outline')">
          <ListTree :size="19" /> 目录
        </button>
        <button type="button" @click="openMobilePanel('notes')">
          <NotebookPen :size="19" /> 笔记
        </button>
        <button type="button" @click="openMobilePanel('assistant')">
          <MessageSquareText :size="19" /> 智能体
          <i v-if="messages.length" aria-label="有对话记录"></i>
        </button>
      </nav>

      <WorkspaceDrawer
        v-if="isCompact"
        :open="Boolean(mobilePanel)"
        :title="drawerTitle"
        @close="closeMobilePanel"
      >
        <CourseOutlineRail
          v-if="mobilePanel === 'outline'"
          :nodes="nodes"
          :current-node-index="currentNodeIndex"
          :completed-nodes="completedNodes"
          :closable="false"
          @select="handleMobileNodeSelect"
        />
        <LearningNotesPanel
          v-else-if="mobilePanel === 'notes'"
          v-model="currentNote"
          :node-title="currentNode?.title"
          :page="currentPage"
          :time="currentTime"
          :sync-error="noteSyncError"
          :finishing="noteFinishing"
          :finished-anchor="lastFinishedNoteAnchor"
          :current-anchor="noteAnchorKey"
          @finish="handleFinishNote"
          @dismiss-error="clearNoteSyncError"
        />
        <LearningAssistantPanel
          v-else-if="mobilePanel === 'assistant'"
          :messages="messages"
          :draft="questionDraft"
          :is-asking="isAsking"
          :closable="false"
          @update:draft="questionDraft = $event"
          @ask="sendQuestion"
        />
      </WorkspaceDrawer>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import {
  ListTree,
  LoaderCircle,
  MessageSquareText,
  NotebookPen,
  TriangleAlert,
} from 'lucide-vue-next'

import CourseOutlineRail from '@/features/student-learning/components/CourseOutlineRail.vue'
import LearningAssistantPanel from '@/features/student-learning/components/LearningAssistantPanel.vue'
import LearningMediaStage from '@/features/student-learning/components/LearningMediaStage.vue'
import LearningNotesPanel from '@/features/student-learning/components/LearningNotesPanel.vue'
import LearningWorkspaceHeader from '@/features/student-learning/components/LearningWorkspaceHeader.vue'
import WorkspaceDrawer from '@/features/student-learning/components/WorkspaceDrawer.vue'
import { useLearningWorkspace } from '@/features/student-learning/composables/useLearningWorkspace.js'
import '@/features/student-learning/styles/learning-workspace.css'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)
const isCompact = useMediaQuery('(max-width: 1024px)')

const {
  status,
  error,
  course,
  mode,
  nodes,
  currentNode,
  currentNodeIndex,
  currentTime,
  currentPage,
  currentSlide,
  currentPptPage,
  totalPages,
  currentVideoUrl,
  completedNodes,
  progressPercent,
  isPlaying,
  playbackRate,
  volume,
  isMuted,
  captionsEnabled,
  outlineOpen,
  assistantOpen,
  notesOpen,
  mobilePanel,
  questionDraft,
  messages,
  isAsking,
  currentNote,
  noteAnchorKey,
  saveState,
  mediaError,
  // P2 §三.2：笔记保存失败提示与「完成笔记」动作
  noteSyncError,
  lastFinishedNoteAnchor,
  finishNote,
  clearNoteSyncError,
  load,
  switchMode,
  selectNode,
  seekTo,
  updatePlayback,
  setPage,
  setPanel,
  openMobilePanel,
  closeMobilePanel,
  sendQuestion,
} = useLearningWorkspace(courseId)

const drawerTitle = computed(() => {
  if (mobilePanel.value === 'outline') return '课程目录'
  if (mobilePanel.value === 'notes') return '学习笔记'
  return '课程智能体'
})

function goBack() {
  router.push('/student')
}

// P2 §三.2：「完成笔记」处理器——成功后返回课程主视图（关闭笔记面板）
const noteFinishing = ref(false)
async function handleFinishNote() {
  noteFinishing.value = true
  const result = await finishNote()
  noteFinishing.value = false
  if (result.ok) {
    // 保存成功后返回课程（page-design §12.8：手动「完成笔记」后返回课程）
    setPanel('notes', false)
  }
  // 失败时不关闭面板，由 syncError 提示用户重试
}

function handlePanelToggle(panel) {
  if (isCompact.value) {
    openMobilePanel(panel)
    return
  }
  if (panel === 'outline') setPanel(panel, !outlineOpen.value)
  if (panel === 'assistant') setPanel(panel, !assistantOpen.value)
  if (panel === 'notes') setPanel(panel, !notesOpen.value)
}

function handleMobileNodeSelect(index) {
  selectNode(index)
  closeMobilePanel()
}

onMounted(load)
</script>