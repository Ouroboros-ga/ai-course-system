<script setup>
import { computed, inject, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLearningWorkspace } from '@/features/student-learning/composables/useLearningWorkspace.js'
import { useMediaPlayback } from '@/features/student-learning/composables/useMediaPlayback.js'
import { useAvatarPlayback } from '@/features/student-learning/composables/useAvatarPlayback.js'
import {
  findPlaylistItemIndex,
  findPlaylistItemIndexById,
  resolvePlaylistPlaybackTarget,
  resolvePlaylistSelection,
  resolveTimelinePlaybackTarget,
  usePlaylistPlayback,
} from '@/features/student-learning/composables/usePlaylistPlayback.js'
import {
  createPlaybackCoordinate,
  resolveFrozenCoordinateGlobalSeconds,
} from '@/features/student-learning/adapters/learningAdjustmentCoordinate.js'
import {
  applyLearningAdjustment,
  createLearningAdjustmentIdempotencyKey,
  dismissLearningAdjustment,
  listRecentLearningAdjustments,
  returnFromLearningAdjustment,
} from '@/api/learning_adjustments.js'
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
import SfxButton from '@/app/ui/SfxButton.vue'
import { consumeRecommendation } from '@/api/cognitive.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()
const { detail, analyticsEligible, capabilities } = inject('courseContext')

const courseId = Number(route.params.courseId)
// Course Access is the source of truth: only an analytics-eligible learner
// may read or write their private learning/cognition state.  Staff and
// observers all use the content-only preview branch.
const previewMode = computed(() => !analyticsEligible.value)

let media = null
let playlistPlayback = null

function getQuestionObservation() {
  if (!media || !playlistPlayback) return null
  return createPlaybackCoordinate({
    courseReleaseId: ws.releaseId.value,
    mediaReleaseId: media.manifest.value.releaseId,
    item: playlistPlayback.activeItem.value,
    cue: media.resolvePptCue(ws.currentTime.value),
    globalTimeSeconds: ws.currentTime.value,
  })
}

// TeachingAgent 受控接入（P1）：将 courseContext 的 analyticsEligible/capabilities
// 与当前用户 ID 以 getter 形式注入 workspace。workspace 在 sendQuestion 时读取最新值，
// 仅当 cognitive_analysis 能力开关开启 + analyticsEligible（真实学生）+ studentId
// 三者齐备时尝试 TeachingAgent，否则直接走 V1 /chat/ask（AGENTS.md 硬约束）。
const ws = useLearningWorkspace(courseId, {
  previewMode: previewMode.value,
  getStudentId: () => counter.userData?.id ?? null,
  getAnalyticsEligible: () => analyticsEligible.value,
  getCapabilities: () => capabilities.value,
  getQuestionObservation: () => getQuestionObservation(),
})
media = useMediaPlayback(courseId)
const avatar = useAvatarPlayback()
playlistPlayback = usePlaylistPlayback(media.playlist)

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
  // 初始为 LEARN（听讲），不自动激活任何 dock 动作；提问模块需用户主动点击。
  initialState: LEARN_STATES.LEARN,
})
const learnState = ref(machine.state)
const branchContext = ref(null)
const dockRef = ref(null)
const pendingMediaSeek = ref(null)
const activeLearningAdjustment = ref(null)
const learningAdjustmentNotice = ref('')
const learningAdjustmentBusy = ref(false)
const LEARNING_ADJUSTMENT_STORAGE_KEY = `sfx:learning-adjustment:${courseId}:${counter.userData?.id ?? 'unknown'}`

function sameIdentifier(left, right) {
  return left != null && right != null && String(left) === String(right)
}

function coordinateForCurrentPlayback() {
  return getQuestionObservation()
}

function isStoredAdjustment(value) {
  const proposal = value?.proposal
  return Boolean(
    proposal?.adjustment_id
    && proposal?.status === 'applied'
    && proposal?.review_target?.media_release_item_id
    && proposal?.return_anchor?.media_release_item_id
  )
}

function persistActiveLearningAdjustment() {
  const active = activeLearningAdjustment.value
  try {
    if (!active?.proposal?.adjustment_id) {
      sessionStorage.removeItem(LEARNING_ADJUSTMENT_STORAGE_KEY)
      return
    }
    sessionStorage.setItem(LEARNING_ADJUSTMENT_STORAGE_KEY, JSON.stringify({
      proposal: active.proposal,
      previousRate: active.previousRate,
      wasPlaying: active.wasPlaying,
      navigationStatus: active.navigationStatus,
    }))
  } catch {
    // Browser storage is only a recovery aid; it cannot block learning.
  }
}

function setActiveLearningAdjustment(active) {
  activeLearningAdjustment.value = active
  persistActiveLearningAdjustment()
}

function clearActiveLearningAdjustment() {
  activeLearningAdjustment.value = null
  persistActiveLearningAdjustment()
}

function restoreActiveLearningAdjustment() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(LEARNING_ADJUSTMENT_STORAGE_KEY) || 'null')
    if (!isStoredAdjustment(stored)) return
    // Reloading the page cannot prove the media element remains at its old
    // target. Require a fresh browser-confirmed seek before showing review.
    activeLearningAdjustment.value = {
      proposal: stored.proposal,
      previousRate: Number(stored.previousRate) || 1,
      wasPlaying: Boolean(stored.wasPlaying),
      navigationStatus: 'accepted',
    }
  } catch {
    // Corrupt or unavailable session storage must not affect the player.
  }
}

function updateMessageLearningAdjustment(proposal) {
  if (!proposal?.adjustment_id) return
  ws.messages.value = ws.messages.value.map(message => (
    String(message.learningAdjustment?.adjustment_id || '') === String(proposal.adjustment_id)
      ? { ...message, learningAdjustment: proposal }
      : message
  ))
}

async function recoverAcceptedLearningAdjustment(adjustmentId, previousRate, wasPlaying) {
  try {
    const response = await listRecentLearningAdjustments(courseId, { limit: 20 })
    const payload = response?.data ?? response
    const proposal = (payload?.items || []).find(item => (
      String(item?.adjustment_id || '') === String(adjustmentId)
      && item?.status === 'applied'
      && item?.return_anchor
    ))
    if (!proposal) return null
    updateMessageLearningAdjustment(proposal)
    const active = { proposal, previousRate, wasPlaying, navigationStatus: 'accepted' }
    setActiveLearningAdjustment(active)
    return active
  } catch {
    return null
  }
}

function waitForMediaSeek(target) {
  return new Promise((resolve, reject) => {
    pendingMediaSeek.value?.fail(new Error('MEDIA_SEEK_SUPERSEDED'))
    let timeoutId = null
    const complete = () => {
      if (pendingMediaSeek.value?.complete === complete) pendingMediaSeek.value = null
      window.clearTimeout(timeoutId)
      resolve()
    }
    const fail = error => {
      if (pendingMediaSeek.value?.fail === fail) pendingMediaSeek.value = null
      window.clearTimeout(timeoutId)
      reject(error)
    }
    timeoutId = window.setTimeout(() => {
      if (pendingMediaSeek.value?.complete === complete) pendingMediaSeek.value = null
      reject(new Error('MEDIA_SEEK_TIMEOUT'))
    }, 12_000)
    pendingMediaSeek.value = {
      target,
      complete,
      fail,
    }
  })
}

function handleMediaSeeked(payload) {
  const pending = pendingMediaSeek.value
  if (!pending) return
  const target = pending.target
  if (!sameIdentifier(payload?.mediaReleaseItemId, target?.media_release_item_id)) return
  if (Math.abs(Number(payload?.localTimeMs) - Number(target?.local_time_ms)) > 1_250) return
  pending.complete()
}

function handleMediaError(payload) {
  const pending = pendingMediaSeek.value
  if (!pending) return
  if (!sameIdentifier(payload?.mediaReleaseItemId, pending.target?.media_release_item_id)) return
  pending.fail(new Error('MEDIA_SOURCE_UNAVAILABLE'))
}

function selectFrozenCoordinate(coordinate) {
  const items = media.playlist.value?.items || []
  const playlistIndex = findPlaylistItemIndexById(items, coordinate.media_release_item_id)
  if (playlistIndex < 0) throw new Error('MEDIA_ITEM_UNAVAILABLE')
  const item = items[playlistIndex]
  const nodeIndex = ws.nodes.value.findIndex(node => (
    sameIdentifier(node.id, item.nodeId)
    || sameIdentifier(node.outlineNodeId, item.outlineNodeId)
  ))
  if (nodeIndex < 0) throw new Error('COURSE_NODE_UNAVAILABLE')
  const targetGlobalSeconds = resolveFrozenCoordinateGlobalSeconds(coordinate, item)
  if (targetGlobalSeconds == null) throw new Error('MEDIA_COORDINATE_UNAVAILABLE')
  playlistPlayback.activeIndex.value = playlistIndex
  ws.selectNode(nodeIndex, { play: false, preserveTime: true, page: coordinate.page })
  // Keep the legacy learner rail synchronized when a frozen coordinate crosses
  // from one released media item to another.
  ws.seekTo(targetGlobalSeconds, { nodeIndex })
  ws.isPlaying.value = false
}

async function restoreLocalAnchor(anchor, previousRate, wasPlaying) {
  if (!anchor) return
  const seeked = waitForMediaSeek(anchor)
  selectFrozenCoordinate(anchor)
  await seeked
  ws.playbackRate.value = previousRate
  ws.isPlaying.value = wasPlaying
}

async function openAcceptedLearningAdjustment(active) {
  const target = active?.proposal?.review_target
  if (!target) throw new Error('ADJUSTMENT_TARGET_UNAVAILABLE')
  const seeked = waitForMediaSeek(target)
  selectFrozenCoordinate(target)
  await seeked
  ws.playbackRate.value = active.proposal.recommended_playback_rate
  setActiveLearningAdjustment({ ...active, navigationStatus: 'reviewing' })
}

async function restoreAfterFailedReviewOpen(active) {
  try {
    await restoreLocalAnchor(active.proposal.return_anchor, active.previousRate, active.wasPlaying)
    return true
  } catch {
    ws.playbackRate.value = active.previousRate
    ws.isPlaying.value = false
    return false
  }
}

async function acceptLearningAdjustment(initialProposal) {
  if (!initialProposal?.adjustment_id || learningAdjustmentBusy.value || activeLearningAdjustment.value) return
  const returnAnchor = coordinateForCurrentPlayback()
  if (!returnAnchor) {
    learningAdjustmentNotice.value = '当前播放位置未能对应到已发布媒体，无法安全开始回顾。'
    return
  }
  const previousRate = ws.playbackRate.value
  const wasPlaying = ws.isPlaying.value
  learningAdjustmentBusy.value = true
  learningAdjustmentNotice.value = ''
  ws.isPlaying.value = false
  try {
    const accepted = await applyLearningAdjustment(
      initialProposal.adjustment_id,
      returnAnchor,
      createLearningAdjustmentIdempotencyKey('apply', initialProposal.adjustment_id),
    )
    const proposal = accepted?.data ?? accepted
    if (proposal?.status !== 'applied' || !proposal?.review_target || !proposal?.return_anchor) {
      throw new Error('ADJUSTMENT_ACCEPTANCE_UNAVAILABLE')
    }
    updateMessageLearningAdjustment(proposal)
    const active = { proposal, previousRate, wasPlaying, navigationStatus: 'accepted' }
    setActiveLearningAdjustment(active)
    await openAcceptedLearningAdjustment(active)
  } catch {
    const active = activeLearningAdjustment.value
      || await recoverAcceptedLearningAdjustment(initialProposal.adjustment_id, previousRate, wasPlaying)
    if (!active) {
      learningAdjustmentNotice.value = '未能确认回顾请求；当前学习位置没有改变。'
      ws.playbackRate.value = previousRate
      ws.isPlaying.value = wasPlaying
      return
    }
    const restored = await restoreAfterFailedReviewOpen(active)
    learningAdjustmentNotice.value = restored
      ? '已确认回顾，但未能打开内容；已返回原学习位置，可重试。'
      : '已确认回顾，但未能打开内容，也未能自动恢复原位置；请手动恢复后重试。'
  } finally {
    learningAdjustmentBusy.value = false
  }
}

async function retryOpeningLearningAdjustment() {
  const active = activeLearningAdjustment.value
  if (!active?.proposal?.adjustment_id || learningAdjustmentBusy.value) return
  learningAdjustmentBusy.value = true
  learningAdjustmentNotice.value = ''
  ws.isPlaying.value = false
  try {
    await openAcceptedLearningAdjustment(active)
  } catch {
    const restored = await restoreAfterFailedReviewOpen(active)
    learningAdjustmentNotice.value = restored
      ? '仍未能打开回顾内容；已返回原学习位置，可稍后重试。'
      : '仍未能打开回顾内容；请手动恢复学习位置后再试。'
  } finally {
    learningAdjustmentBusy.value = false
  }
}

async function returnToLearningAnchor() {
  const active = activeLearningAdjustment.value
  const anchor = active?.proposal?.return_anchor
  if (
    !active?.proposal?.adjustment_id
    || !anchor
    || active.navigationStatus !== 'reviewing'
    || learningAdjustmentBusy.value
  ) return
  learningAdjustmentBusy.value = true
  learningAdjustmentNotice.value = ''
  ws.isPlaying.value = false
  try {
    await restoreLocalAnchor(anchor, active.previousRate, active.wasPlaying)
    await returnFromLearningAdjustment(
      active.proposal.adjustment_id,
      createLearningAdjustmentIdempotencyKey('return', active.proposal.adjustment_id),
    )
    clearActiveLearningAdjustment()
  } catch {
    learningAdjustmentNotice.value = '未能回到原学习位置；可以再次尝试返回。'
    ws.isPlaying.value = false
  } finally {
    learningAdjustmentBusy.value = false
  }
}

async function dismissLearningAdjustmentProposal(proposal) {
  if (!proposal?.adjustment_id || learningAdjustmentBusy.value) return
  learningAdjustmentBusy.value = true
  try {
    const dismissed = await dismissLearningAdjustment(
      proposal.adjustment_id,
      createLearningAdjustmentIdempotencyKey('dismiss', proposal.adjustment_id),
    )
    updateMessageLearningAdjustment(dismissed?.data ?? dismissed)
  } catch {
    learningAdjustmentNotice.value = '未能保存“继续当前位置”的选择，请稍后重试。'
  } finally {
    learningAdjustmentBusy.value = false
  }
}

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
  const items = media.playlist.value?.items
  const globalTime = Number(payload?.globalTime)
  if (Array.isArray(items) && items.length && Number.isFinite(globalTime)) {
    const target = resolvePlaylistPlaybackTarget(
      items,
      ws.nodes.value,
      globalTime,
      playlistPlayback.activeIndex.value,
    )
    if (target.playlistIndex >= 0) {
      playlistPlayback.activeIndex.value = target.playlistIndex
      const item = items[target.playlistIndex]
      // The playlist is authoritative for release playback. Supplying its
      // node id keeps the legacy workspace index in sync for the rail.
      payload = {
        ...payload,
        nodeId: item.nodeId,
        outlineNodeId: item.outlineNodeId,
        nodeIndex: target.nodeIndex,
      }
    }
  } else if (Number.isFinite(globalTime)) {
    const target = resolveTimelinePlaybackTarget(
      media.pptTimeline.value,
      ws.nodes.value,
      globalTime,
      ws.currentNodeIndex.value,
    )
    payload = {
      ...payload,
      nodeId: target.nodeId ?? payload?.nodeId,
      outlineNodeId: target.outlineNodeId ?? payload?.outlineNodeId,
      nodeIndex: target.nodeIndex,
    }
  }
  ws.updatePlayback(payload)
}
function handleNodeChange(direction) {
  handleTrackSelect(ws.currentNodeIndex.value + Number(direction))
}
function handleTrackSelect(index, options = {}) {
  const parsedIndex = Number(index)
  if (!Number.isInteger(parsedIndex) || parsedIndex < 0 || parsedIndex >= ws.nodes.value.length) return
  const nextIndex = parsedIndex
  const node = ws.nodes.value[nextIndex]
  if (!node) return
  const wasPlaying = options.play ?? ws.isPlaying.value
  const items = media.playlist.value?.items || []
  const { playlistIndex, targetTime } = resolvePlaylistSelection(items, node, media.pptTimeline.value)

  if (playlistIndex >= 0) playlistPlayback.activeIndex.value = playlistIndex
  ws.selectNode(nextIndex, { play: wasPlaying, preserveTime: true })
  ws.seekTo(targetTime, { nodeIndex: nextIndex })
}

function handleOpenKnowledge(nodeId) {
  if (nodeId == null || nodeId === '') return
  router.push(`/app/course/${courseId}/knowledge/graph/${encodeURIComponent(nodeId)}`)
}
function handlePlaylistNext() {
  const nextIndex = playlistPlayback.activeIndex.value + 1
  const items = media.playlist.value?.items || []
  const item = items[nextIndex]
  if (!item) return
  const index = ws.nodes.value.findIndex(node => (
    (item.nodeId != null && String(node.id) === String(item.nodeId))
    || (item.outlineNodeId && String(node.outlineNodeId) === String(item.outlineNodeId))
  ))
  if (index >= 0) handleTrackSelect(index, { play: true })
  else playlistPlayback.next()
}
function handlePlaylistPrevious() {
  const previousIndex = playlistPlayback.activeIndex.value - 1
  const items = media.playlist.value?.items || []
  const item = items[previousIndex]
  if (!item) return
  const index = ws.nodes.value.findIndex(node => (
    (item.nodeId != null && String(node.id) === String(item.nodeId))
    || (item.outlineNodeId && String(node.outlineNodeId) === String(item.outlineNodeId))
  ))
  if (index >= 0) handleTrackSelect(index, { play: true })
  else playlistPlayback.previous()
}

watch(
  [() => ws.currentNode.value?.id, () => ws.currentNode.value?.outlineNodeId, () => media.playlist.value],
  () => {
    const node = ws.currentNode.value
    if (!node || !media.playlist.value?.items?.length) return
    const matched = media.playlist.value.items.find(item => (
      String(item.nodeId) === String(node.id)
      || (node.outlineNodeId && String(item.outlineNodeId) === String(node.outlineNodeId))
    ))
    if (matched) playlistPlayback.selectByNode(matched.outlineNodeId || matched.nodeId)
  },
  { immediate: true },
)
function handleAgentAction(action) { handleDockAction({ id: action, target: action === 'visualize' ? LEARN_STATES.VISUALIZE : LEARN_STATES.PRACTICE }) }

async function handleRecommendationAction({ node, recommendation, action }) {
  const nodeIndex = ws.nodes.value.findIndex(item => String(item.outlineNodeId) === String(node?.outlineNodeId))
  if (nodeIndex >= 0) handleTrackSelect(nodeIndex, { play: action === 'continue' })

  if (action === 'practice') {
    handleDockAction({ id: 'practice', target: LEARN_STATES.PRACTICE })
  }

  // 推荐消费是可追溯的学习动作；消费失败不阻断学生进入练习或继续学习。
  if (recommendation?.recommendation_id) {
    const consumed = await consumeRecommendation(recommendation.recommendation_id, { action: 'accepted' })
      .then(() => true)
      .catch(() => false)
    // 后端消费接口会在可映射时写入统一 LearningEvent；只有接口失败时
    // 才进入离线队列，避免产生两条 recommendation_consumed 事实。
    if (!consumed && node?.outlineNodeId) {
      ws.queueLearningEvent(node.outlineNodeId, 'recommendation_consumed', {
        recommendation_id: recommendation.recommendation_id,
        recommendation_type: recommendation.type || recommendation.recommendation_type || null,
        action,
      })
    }
  }
}

async function handlePracticeExit() {
  await exitBranch()
  await ws.refreshLearningContext().catch(() => {})
}

async function completeNode() {
  await ws.completeCurrentNode()
}

onMounted(async () => {
  await Promise.all([ws.load(), media.load()])
  restoreActiveLearningAdjustment()
})

watch(
  [() => media.avatarCues.value, () => media.digitalHumanManifest.value, () => media.avatarManifestUrl.value, () => media.avatarAssetUrls.value, () => playlistPlayback.activeItem.value?.avatarCues, () => playlistPlayback.activeItem.value?.avatarManifestUrl, () => playlistPlayback.activeItem.value?.avatarAssetUrls],
  ([avatarCues, digitalHumanManifest, avatarManifestUrl, avatarAssetUrls, playlistAvatarCues, playlistAvatarManifestUrl, playlistAvatarAssetUrls]) => {
    avatar.load({
      avatarCues: playlistAvatarCues || avatarCues,
      digitalHumanManifest,
      avatarManifestUrl: playlistAvatarManifestUrl || avatarManifestUrl,
      avatarAssetUrls: Object.keys(playlistAvatarAssetUrls || {}).length ? playlistAvatarAssetUrls : avatarAssetUrls,
    })
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
      <div v-if="previewMode" class="sfx-preview-notice" role="status">
        教师预览模式：这里展示课程草稿内容，不读取或写入任何学生学习进度、认知或推荐状态。
      </div>
      <div class="sfx-learn-body">
        <LearningTrack
          :nodes="ws.nodes.value"
          :current-index="ws.currentNodeIndex.value"
          :completed-ids="ws.completedNodes.value"
          :learning-items="ws.learningItems.value"
          :expanded-node-id="ws.expandedNodeId.value"
          :cognitive-details="ws.cognitiveDetails.value"
          :cognitive-loading="ws.cognitiveLoading.value"
          :collapsed="trackCollapsed"
          @select="handleTrackSelect"
          @inspect="ws.toggleNodeCognition"
          @open-knowledge="handleOpenKnowledge"
          @recommendation-action="handleRecommendationAction"
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
            @media-seeked="handleMediaSeeked"
            @media-error="handleMediaError"
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
                :active-adjustment="activeLearningAdjustment"
                :adjustment-busy="learningAdjustmentBusy"
                :adjustment-notice="learningAdjustmentNotice"
                @exit="exitBranch"
                @action="handleAgentAction"
                @accept-adjustment="acceptLearningAdjustment"
                @dismiss-adjustment="dismissLearningAdjustmentProposal"
                @retry-opening-review="retryOpeningLearningAdjustment"
                @return-adjustment="returnToLearningAnchor"
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
          @exit="handlePracticeExit"
        />
      </div>

      <LearningActionDock
        ref="dockRef"
        :current-state="learnState"
        :enabled-states="machine.isEnabled"
        @action="handleDockAction"
      />
      <SfxButton
        v-if="!previewMode && ws.currentNode.value?.outlineNodeId && !ws.completedNodes.value.includes(ws.currentNode.value.id)"
        variant="primary"
        size="sm"
        class="sfx-learn-complete"
        @click="completeNode"
      >完成本知识点</SfxButton>
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
.sfx-learn-complete { align-self: center; margin: 0 0 16px; padding: 8px 14px; border: var(--border-default); border-radius: 8px; background: var(--color-brand); color: var(--text-inverse); }
.sfx-preview-notice { flex: 0 0 auto; margin: 12px 16px 0; padding: 10px 12px; border: 1px solid var(--amber-300); border-radius: var(--radius-sm); background: var(--amber-100); color: var(--amber-700); font-size: var(--ui-sm-size); }

.sfx-learn-stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  transition: margin var(--duration-normal) var(--ease-out);
}
</style>
