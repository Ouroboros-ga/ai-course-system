import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { askQuestion } from '@/api/chat.js'
import { respondTeachingAgent, getConversationHistory } from '@/api/teaching_agent.js'
import { getPlayerInitData, savePlayerProgress } from '@/api/player.js'
import { getLearningContext, recordLearningEvent, completeLearningAction } from '@/api/facade.js'
import { getCognitiveState } from '@/api/cognitive.js'
import { getNodeDisplayState as resolveNodeDisplayState } from '@/features/student-learning/learningStatus.js'
import { listNotes, createNote, updateNote, deleteNote } from '@/api/note.js'
import {
  buildProgressPayload,
  clamp,
  findNodeIndexAtTime,
  normalizePlayerData,
  resolvePageAtTime,
  withAccessToken,
} from '../adapters/playerWorkspaceAdapter.js'

export const LEARNING_MODES = Object.freeze({
  GUIDED: 'guided',
  STUDY: 'study',
})

const readJson = (key, fallback) => {
  try {
    const value = window.localStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch {
    return fallback
  }
}

const writeJson = (key, value) => {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Local persistence is a convenience. A blocked storage quota must not stop learning.
  }
}

export function useLearningWorkspace(courseId, options = {}) {
  // page-design §1.4：教师「学生视角预览」不写入正式学习进度。
  // previewMode 下所有进度持久化调用直接短路（读取照常）。
  const previewMode = options?.previewMode === true
  // TeachingAgent 受控接入（P1）：getStudentId/getAnalyticsEligible/getCapabilities
  // 由 LearnPage 从 courseContext 注入（ref/getter）。仅在 cognitive_analysis 能力
  // 开关开启、且当前用户为 analytics_eligible（真实学生）时尝试 TeachingAgent；
  // 503/失败时静默回退 V1 /chat/ask，不影响正常 Q&A（AGENTS.md 硬约束）。
  const getStudentId = options?.getStudentId ?? (() => null)
  const getAnalyticsEligible = options?.getAnalyticsEligible ?? (() => false)
  const getCapabilities = options?.getCapabilities ?? (() => ({}))
  // CodingEduAgent receives only a server-issued ExperimentRun id. The
  // coding runner can update this value after a verified submission; no
  // source code or Judge0 token is ever placed in the TeachingAgent payload.
  const codeRunStorageKey = `teaching-agent-code-run:${courseId}:${getStudentId() ?? 'anonymous'}`
  const codeSubmissionId = ref(
    options?.codeSubmissionId ?? window.localStorage.getItem(codeRunStorageKey) ?? null,
  )
  const getCodeSubmissionId = options?.getCodeSubmissionId ?? (() => codeSubmissionId.value)
  // 学习会话 ID：贯穿一次学习会话，TeachingAgent 用作 session_id 关联事件与 trace。
  // Reuse a per-learner/course ID. The Audit-domain session context is still
  // bounded and expires after 30 minutes; full chat messages are now persisted
  // in the separate Conversation Domain and resumed via loadConversationHistory().
  const teachingSessionStorageKey = `teaching-agent-session:${courseId}:${getStudentId() ?? 'anonymous'}`
  let teachingSessionId = window.localStorage.getItem(teachingSessionStorageKey)
  if (!teachingSessionId) {
    teachingSessionId = (typeof crypto !== 'undefined' && crypto?.randomUUID?.()) ||
      'sess-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)
    window.localStorage.setItem(teachingSessionStorageKey, teachingSessionId)
  }
  const status = ref('loading')
  const error = ref('')
  const course = ref(null)
  const mode = ref(LEARNING_MODES.GUIDED)
  const currentNodeIndex = ref(0)
  const currentTime = ref(0)
  const currentPage = ref(1)
  const completedNodes = ref([])
  const releaseId = ref(null)
  const learningContext = ref(null)
  const expandedNodeId = ref(null)
  const cognitiveDetails = ref({})
  const cognitiveLoading = ref({})
  const cognitiveCache = new Map()
  const pendingLearningEvents = ref([])
  const openedNodeKeys = ref(new Set())
  const isPlaying = ref(false)
  const playbackRate = ref(1)
  const volume = ref(0.85)
  const isMuted = ref(false)
  const captionsEnabled = ref(true)
  const outlineOpen = ref(true)
  const assistantOpen = ref(true)
  const notesOpen = ref(false)
  const mobilePanel = ref(null)
  const questionDraft = ref('')
  const messages = ref([])
  const isAsking = ref(false)
  const notes = ref({})
  // 批次1：笔记持久化--映射 anchorKey -> 后端 noteId，用于更新而非重复创建
  const noteIdMap = ref({})
  let noteSyncTimer = null
  const saveState = ref('saved')
  const mediaError = ref('')
  const returnAnchor = ref(null)
  // P2 §三.2：笔记同步错误消息（保存失败时提示用户，不再静默吞错）
  const noteSyncError = ref('')
  // P2 §三.2：「完成笔记」成功标记，前端可据此显示笔记入口（不弹庆祝页）
  const lastFinishedNoteAnchor = ref('')

  const storagePrefix = 'student-learning-workspace:' + courseId
  const viewStorageKey = storagePrefix + ':view'
  const notesStorageKey = storagePrefix + ':notes'
  const learningQueueStorageKey = storagePrefix + ':learning-events'
  let viewPersistTimer = null
  let progressTimer = null
  // 听课时长埋点：记录上次进度保存时间戳，用于计算本次保存周期内的听课秒数。
  // 仅在 isPlaying 时累计 delta，后端累加到 NodeProgress.time_spent。
  let lastProgressSaveAt = 0
  let flushingLearningEvents = false

  const nodes = computed(() => course.value?.nodes ?? [])
  const slides = computed(() => course.value?.slides ?? [])
  const pptPages = computed(() => course.value?.pptPages ?? [])
  const currentNode = computed(() => nodes.value[currentNodeIndex.value] ?? null)
  const currentNodeId = computed(() => currentNode.value?.id ?? null)
  const learningItems = computed(() => learningContext.value?.items ?? [])
  const learningItemsByNodeId = computed(() => {
    const map = new Map()
    for (const item of learningItems.value) map.set(String(item.outline_node_id), item)
    return map
  })

  function buildPreviewLearningContext(normalized) {
    const previewItems = (normalized?.nodes || [])
      .filter(node => node?.outlineNodeId)
      .map(node => ({
        outline_node_id: String(node.outlineNodeId),
        title: node.title,
        node_type: node.type || 'knowledge_point',
        knowledge_node_key: null,
        learning: {
          status: 'not_available',
          completion_ratio: 0,
          exposure_seconds: 0,
          current_timestamp: 0,
          current_page: node.pageStart || 1,
          completion_reason: null,
        },
        cognition: {
          status: 'not_available',
          reason_codes: ['teacher_preview_no_student_state'],
        },
        recommendation: {
          status: 'not_available',
          reason_codes: ['teacher_preview_no_student_state'],
        },
      }))
    return {
      course_id: normalized?.courseId ?? courseId,
      release_id: normalized?.releaseId ?? null,
      items: previewItems,
      total: previewItems.length,
      completed: 0,
      completion_rate: 0,
      recent_anchor: null,
      preview: true,
    }
  }
  const currentSlide = computed(() => {
    const slide = slides.value.find(item => item.page === currentPage.value)
    if (!slide) return null
    return {
      ...slide,
      url: withAccessToken(slide.url, window.localStorage.getItem('token')),
    }
  })
  const currentPptPage = computed(() => {
    return pptPages.value.find(item => item.page === currentPage.value) ?? null
  })
  const totalPages = computed(() => {
    const slideMax = slides.value.at(-1)?.page ?? 0
    const textMax = pptPages.value.at(-1)?.page ?? 0
    const nodeMax = nodes.value.reduce((max, node) => Math.max(max, node.pageEnd), 0)
    return Math.max(1, slideMax, textMax, nodeMax)
  })
  const currentVideoUrl = computed(() => {
    return withAccessToken(
      currentNode.value?.videoUrl ?? '',
      window.localStorage.getItem('token')
    )
  })
  const progressPercent = computed(() => {
    if (!course.value) return 0
    const restored = course.value.savedProgress.completionRate
    const timeProgress = course.value.totalDuration > 0
      ? (currentTime.value / course.value.totalDuration) * 100
      : 0
    return clamp(Math.max(restored, timeProgress), 0, 100)
  })
  const noteAnchorKey = computed(() => {
    return String(currentNodeId.value ?? 'course') + ':page-' + currentPage.value
  })
  const currentNote = computed({
    get: () => notes.value[noteAnchorKey.value] ?? '',
    set: value => {
      notes.value = {
        ...notes.value,
        [noteAnchorKey.value]: String(value),
      }
      // 离线草稿：立即写 localStorage（不阻塞输入）
      writeJson(notesStorageKey, notes.value)
      // 批次1：防抖同步到后端
      scheduleNoteSync(noteAnchorKey.value)
    },
  })

  // 批次1：将本地笔记同步到后端 API
  function scheduleNoteSync(anchorKey) {
    window.clearTimeout(noteSyncTimer)
    noteSyncTimer = window.setTimeout(() => syncNoteToBackend(anchorKey), 800)
  }

  async function syncNoteToBackend(anchorKey) {
    if (previewMode) return
    const content = notes.value[anchorKey]
    if (content === undefined) return
    // 解析 anchorKey 提取 node_id 和 page
    const match = anchorKey.match(/^(.+):page-(\d+)$/)
    const nodeId = match && match[1] !== 'course' ? Number(match[1]) : null
    const page = match ? Number(match[2]) : null
    const existingId = noteIdMap.value[anchorKey]
    // 数据卫生：清空内容时不落库；已有笔记则删除，避免资源库「课程笔记」出现空条目
    if (!String(content).trim()) {
      if (existingId) {
        try {
          await deleteNote(existingId)
          noteIdMap.value = { ...noteIdMap.value, [anchorKey]: undefined }
        } catch (e) {
          noteSyncError.value = '笔记删除失败：' + (e?.message || '网络或服务异常')
          return
        }
      }
      noteSyncError.value = ''
      return
    }

    try {
      if (existingId) {
        await updateNote(existingId, {
          content: String(content),
          is_draft: false,
        })
      } else {
        const res = await createNote({
          course_id: courseId,
          node_id: nodeId,
          page: page,
          timestamp: currentTime.value || null,
          title: currentNode.value?.title || '',
          content: String(content),
          trigger_source: 'learn',
          is_draft: false,
        })
        if (res?.id) {
          noteIdMap.value = { ...noteIdMap.value, [anchorKey]: res.id }
        }
      }
      // P2 §三.2：保存成功清空错误，并允许 finishNote 复用此状态
      noteSyncError.value = ''
    } catch (e) {
      // P2 §三.2：保存失败必须提示（page-design §12.8），不再静默吞错
      // 同时保留 localStorage 草稿，下次加载时重试
      noteSyncError.value = '笔记保存失败：' + (e?.message || '网络或服务异常，已暂存到本地草稿')
    }
  }

  // P2 §三.2：「完成笔记」动作（page-design §12.8）
  // 取消待同步定时器，立即同步当前 anchorKey，成功后标记可返回课程；失败时阻止返回并提示。
  // 返回 { ok, error } 供调用方决定是否返回课程。
  async function finishNote() {
    window.clearTimeout(noteSyncTimer)
    const anchorKey = noteAnchorKey.value
    if (!notes.value[anchorKey]) {
      // 空笔记直接视为完成（无需持久化）
      lastFinishedNoteAnchor.value = anchorKey
      return { ok: true, error: '' }
    }
    await syncNoteToBackend(anchorKey)
    if (noteSyncError.value) {
      return { ok: false, error: noteSyncError.value }
    }
    lastFinishedNoteAnchor.value = anchorKey
    return { ok: true, error: '' }
  }

  // P2 §三.2：清空笔记同步错误提示（用户确认后调用）
  function clearNoteSyncError() {
    noteSyncError.value = ''
  }

  // 批次1：从后端加载笔记
  async function loadNotesFromBackend() {
    if (previewMode) return
    try {
      const res = await listNotes(courseId)
      const items = res?.items ?? []
      const noteMap = {}
      const idMap = {}
      for (const item of items) {
        const anchor = `${item.node_id ?? 'course'}:page-${item.page ?? 1}`
        noteMap[anchor] = item.content || ''
        idMap[anchor] = item.id
      }
      // 合并：后端笔记优先，localStorage 草稿补充未同步的
      const localDrafts = readJson(notesStorageKey, {})
      for (const [key, val] of Object.entries(localDrafts)) {
        if (!(key in noteMap) && val) {
          noteMap[key] = val
        }
      }
      notes.value = noteMap
      noteIdMap.value = idMap
    } catch {
      // 后端不可用时回退到 localStorage
      notes.value = readJson(notesStorageKey, {})
    }
  }

  // Conversation Domain：恢复学生教学智能体对话历史。
  // 仅在 TeachingAgent 受控条件齐备（cognitive_analysis + analytics_eligible +
  // studentId）时拉取；失败静默（skipErrorToast），不影响学习页面就绪态。
  // 刷新 / 重新进入课程后，历史消息重建到 messages，学生可继续上下文对话。
  async function loadConversationHistory() {
    if (previewMode) return
    const studentId = getStudentId()
    const analyticsEligible = getAnalyticsEligible()
    const capabilities = getCapabilities()
    if (!capabilities?.cognitive_analysis || !analyticsEligible || studentId == null) return
    try {
      const data = await getConversationHistory(courseId, { limit: 200 })
      const items = Array.isArray(data?.messages) ? data.messages : []
      if (!items.length) return
      messages.value = items.map(msg => ({
        id: 'restored-' + msg.id,
        role: msg.role === 'assistant' ? 'assistant' : 'user',
        content: String(msg.content || ''),
        citations: Array.isArray(msg.citations) ? msg.citations : [],
        conceptId: msg.concept_id ?? null,
        restored: true,
      }))
    } catch {
      // 历史拉取失败不阻断学习；学生仍可发起新提问。
    }
  }

  function refreshLearningContext() {
    return getLearningContext(courseId).then(response => {
      const context = response?.data ?? response
      const nextReleaseId = context?.release_id || releaseId.value
      if (nextReleaseId !== releaseId.value) {
        cognitiveCache.clear()
        cognitiveDetails.value = {}
        cognitiveLoading.value = {}
      }
      learningContext.value = context
      releaseId.value = nextReleaseId
      completedNodes.value = learningItems.value
        .filter(item => item?.learning?.status === 'completed')
        .map(item => {
          const node = nodes.value.find(candidate => String(candidate.outlineNodeId) === String(item.outline_node_id))
          return node?.id
        })
        .filter(id => id != null)
      return context
    })
  }

  function getNodeDisplayState(item) {
    return resolveNodeDisplayState(item)
  }

  async function loadNodeCognition(outlineNodeId) {
    const item = learningItemsByNodeId.value.get(String(outlineNodeId))
    const nodeId = item?.cognition?.node_id
    expandedNodeId.value = String(outlineNodeId)
    if (nodeId == null || previewMode) return null
    const cacheKey = `${releaseId.value || 'unknown'}:${String(outlineNodeId)}`
    if (cognitiveCache.has(cacheKey)) return cognitiveCache.get(cacheKey)
    cognitiveLoading.value = { ...cognitiveLoading.value, [outlineNodeId]: true }
    try {
      const response = await getCognitiveState(courseId, null, nodeId)
      const detail = response?.data ?? response
      cognitiveCache.set(cacheKey, detail)
      cognitiveDetails.value = { ...cognitiveDetails.value, [outlineNodeId]: detail }
      return detail
    } catch (err) {
      cognitiveDetails.value = {
        ...cognitiveDetails.value,
        [outlineNodeId]: { status: 'degraded', message: err?.message || '认知详情暂时不可用' },
      }
      return null
    } finally {
      cognitiveLoading.value = { ...cognitiveLoading.value, [outlineNodeId]: false }
    }
  }

  function toggleNodeCognition(outlineNodeId) {
    const key = String(outlineNodeId)
    if (expandedNodeId.value === key) {
      expandedNodeId.value = null
      return
    }
    loadNodeCognition(key)
  }

  function restoreViewState() {
    const saved = readJson(viewStorageKey, {})
    mode.value = Object.values(LEARNING_MODES).includes(saved.mode)
      ? saved.mode
      : LEARNING_MODES.GUIDED
    playbackRate.value = clamp(Number(saved.playbackRate) || 1, 0.5, 2)
    volume.value = clamp(Number(saved.volume) || 0.85, 0, 1)
    isMuted.value = Boolean(saved.isMuted)
    captionsEnabled.value = saved.captionsEnabled !== false
    outlineOpen.value = saved.outlineOpen !== false
    assistantOpen.value = saved.assistantOpen !== false
    notesOpen.value = Boolean(saved.notesOpen)
    questionDraft.value = String(saved.questionDraft || '')
    notes.value = readJson(notesStorageKey, {})
  }

  function persistViewState() {
    window.clearTimeout(viewPersistTimer)
    viewPersistTimer = window.setTimeout(() => {
      writeJson(viewStorageKey, {
        mode: mode.value,
        playbackRate: playbackRate.value,
        volume: volume.value,
        isMuted: isMuted.value,
        captionsEnabled: captionsEnabled.value,
        outlineOpen: outlineOpen.value,
        assistantOpen: assistantOpen.value,
        notesOpen: notesOpen.value,
        questionDraft: questionDraft.value,
      })
    }, 120)
  }

  async function load() {
    status.value = 'loading'
    error.value = ''
    mediaError.value = ''

    try {
      pendingLearningEvents.value = readJson(learningQueueStorageKey, [])
      const response = await getPlayerInitData(courseId)
      const normalized = normalizePlayerData(response)
      releaseId.value = normalized.releaseId
      course.value = normalized
      if (previewMode) {
        // Teacher/staff preview is a content inspection context. It must not
        // read or merge a student's release-scoped projection into draft nodes.
        learningContext.value = buildPreviewLearningContext(normalized)
        completedNodes.value = []
      } else {
        try {
          await refreshLearningContext()
        } catch {
          completedNodes.value = normalized.savedProgress.completedNodeIds || []
        }
      }
      if (!normalized.nodes.length) {
        error.value = normalized.contentMessage || '课程学习内容尚未就绪，请稍后再试。'
        status.value = 'empty'
        return
      }

      currentNodeIndex.value = normalized.savedProgress.currentNodeIndex
      currentTime.value = normalized.savedProgress.currentTime
      currentPage.value = normalized.savedProgress.currentPage
      restoreViewState()
      status.value = 'ready'
      if (!previewMode && releaseId.value && currentNode.value?.outlineNodeId) {
        const key = `${releaseId.value}:${currentNode.value.outlineNodeId}`
        if (!openedNodeKeys.value.has(key)) {
          openedNodeKeys.value.add(key)
          queueLearningEvent(currentNode.value.outlineNodeId, 'node_opened', {
            current_timestamp: currentTime.value,
            current_page: currentPage.value,
          })
        }
      }
      startProgressTimer()
      // 批次1：笔记持久化--从后端加载笔记（失败时回退 localStorage）
      loadNotesFromBackend()
      // Conversation Domain：恢复教学智能体对话历史（刷新 / 重进课程后重建聊天面板）
      loadConversationHistory()
    } catch (loadError) {
      error.value = loadError?.message || '课程内容加载失败，请稍后重试'
      status.value = 'error'
    }
  }

  function switchMode(nextMode) {
    if (!Object.values(LEARNING_MODES).includes(nextMode)) return
    mode.value = nextMode
  }

  function selectNode(index, options = {}) {
    if (!nodes.value.length) return
    const nextIndex = clamp(Number(index) || 0, 0, nodes.value.length - 1)
    currentNodeIndex.value = nextIndex
    const node = nodes.value[nextIndex]
    if (!options.preserveTime) {
      currentTime.value = node.timestampStart
    }
    currentPage.value = options.page ?? resolvePageAtTime(node, currentTime.value)
    mediaError.value = ''
    if (options.play === true) isPlaying.value = true
    if (releaseId.value && node?.outlineNodeId && !openedNodeKeys.value.has(`${releaseId.value}:${node.outlineNodeId}`)) {
      openedNodeKeys.value.add(`${releaseId.value}:${node.outlineNodeId}`)
      queueLearningEvent(node.outlineNodeId, 'node_opened', {
        current_timestamp: currentTime.value,
        current_page: currentPage.value,
      })
    }
  }

  function seekTo(globalTime, options = {}) {
    if (!course.value) return
    const nextTime = clamp(
      Number(globalTime) || 0,
      0,
      course.value.totalDuration || Number.MAX_SAFE_INTEGER
    )
    const requestedIndex = Number(options.nodeIndex)
    const nextIndex = Number.isInteger(requestedIndex)
      && requestedIndex >= 0
      && requestedIndex < nodes.value.length
      ? requestedIndex
      : findNodeIndexAtTime(nodes.value, nextTime)
    if (nextIndex !== currentNodeIndex.value) {
      currentNodeIndex.value = nextIndex
    }
    currentTime.value = nextTime
    currentPage.value = resolvePageAtTime(nodes.value[nextIndex], nextTime)
    mediaError.value = ''
  }

  function updatePlayback(payload) {
    const globalTime = Number(payload?.globalTime)
    if (Number.isFinite(globalTime)) {
      const previousIndex = currentNodeIndex.value
      const playlistNodeIndex = Number(payload?.playlistNodeIndex)
      const hasPlaylistNodeIndex = Number.isInteger(playlistNodeIndex)
        && playlistNodeIndex >= 0
        && playlistNodeIndex < nodes.value.length
      seekTo(globalTime, hasPlaylistNodeIndex ? { nodeIndex: playlistNodeIndex } : {})
      // A frozen media release owns its cue-to-node/page mapping.  The legacy
      // script timing remains a fallback while P0 still borrows its PPT assets.
      const cueNodeIndex = nodes.value.findIndex(node => {
        const nodeIdMatches = payload?.nodeId != null && String(node.id) === String(payload.nodeId)
        const outlineNodeIdMatches = payload?.outlineNodeId != null
          && String(node.outlineNodeId) === String(payload.outlineNodeId)
        return nodeIdMatches || outlineNodeIdMatches
      })
      if (!hasPlaylistNodeIndex && cueNodeIndex >= 0) {
        currentNodeIndex.value = cueNodeIndex
      }
      const cuePage = Number(payload?.page)
      if (Number.isFinite(cuePage) && cuePage >= 1) {
        currentPage.value = clamp(cuePage, 1, totalPages.value)
      }
      if (currentNodeIndex.value > previousIndex) {
        const completedId = nodes.value[previousIndex]?.id
        if (completedId && !completedNodes.value.includes(completedId)) {
          completedNodes.value = [...completedNodes.value, completedId]
        }
      }
      const node = currentNode.value
      if (node?.outlineNodeId && releaseId.value) {
        queueLearningEvent(node.outlineNodeId, 'media_progress', {
          progress_ratio: node.timestampEnd > node.timestampStart
            ? clamp((currentTime.value - node.timestampStart) / (node.timestampEnd - node.timestampStart), 0, 1)
            : 0,
          current_timestamp: currentTime.value,
          current_page: currentPage.value,
        })
      }
    }
    if (typeof payload?.isPlaying === 'boolean') {
      isPlaying.value = payload.isPlaying
      if (!payload.isPlaying) saveProgress()
    }
  }

  function setPage(page) {
    currentPage.value = clamp(Number(page) || 1, 1, totalPages.value)
  }

  function setPanel(panel, open) {
    const value = Boolean(open)
    if (panel === 'outline') outlineOpen.value = value
    if (panel === 'assistant') assistantOpen.value = value
    if (panel === 'notes') notesOpen.value = value
  }

  function openMobilePanel(panel) {
    mobilePanel.value = panel
  }

  function closeMobilePanel() {
    mobilePanel.value = null
  }

  function captureReturnAnchor(reason = 'prerequisite') {
    returnAnchor.value = {
      reason,
      nodeIndex: currentNodeIndex.value,
      currentTime: currentTime.value,
      currentPage: currentPage.value,
      mode: mode.value,
      questionDraft: questionDraft.value,
    }
    return returnAnchor.value
  }

  function restoreReturnAnchor() {
    if (!returnAnchor.value) return false
    const anchor = returnAnchor.value
    currentNodeIndex.value = anchor.nodeIndex
    currentTime.value = anchor.currentTime
    currentPage.value = anchor.currentPage
    mode.value = anchor.mode
    questionDraft.value = anchor.questionDraft
    returnAnchor.value = null
    return true
  }

  // TeachingAgent warning code → 可读文案映射（变更 3）。
  // 让"web 研究待教师确认""工具被教师关闭"等受控代理行为对学生可见，
  // 避免学生误以为回答缺失。COURSE_KNOWLEDGE_GRAPH_PENDING 由 fallback_reason 触发，
  // 其余 warning 由 result.warnings 数组携带。
  const TEACHING_AGENT_WARNING_NOTICES = {
    COURSE_KNOWLEDGE_GRAPH_PENDING: '课程知识图谱正在解析或暂不可用，本次已使用普通课程问答。',
    WEB_RESEARCH_PENDING_TEACHER_CONFIRMATION: '联网资料检索需教师确认，本次已跳过该环节。',
    TOOL_LOCKED_BY_TEACHER: '该能力已被教师关闭。',
  }

  // TeachingAgent 受控接入（P1）：调用 /teaching-agent/respond 并归一化响应。
  // 仅在 sendQuestion 中被调用，且仅当 cognitive_analysis 能力开关开启 +
  // analyticsEligible + studentId 三者齐备时触发。失败由调用方回退 V1。
  async function askTeachingAgent(question) {
    const verifiedRunId = getCodeSubmissionId()
    const result = await respondTeachingAgent({
      course_id: String(course.value.courseId),
      session_id: teachingSessionId,
      message: question,
      resource_id: currentNodeId.value != null ? String(currentNodeId.value) : null,
      code_submission_id: verifiedRunId ? String(verifiedRunId) : null,
    })
    const warnings = Array.isArray(result?.warnings) ? result.warnings : []
    // 合并 fallback_reason 与 warnings 去重后的可读文案
    const noticeCodes = []
    if (result?.fallback_reason) noticeCodes.push(result.fallback_reason)
    for (const code of warnings) {
      if (!noticeCodes.includes(code)) noticeCodes.push(code)
    }
    const fallbackNotice = noticeCodes
      .map(code => TEACHING_AGENT_WARNING_NOTICES[code])
      .filter(Boolean)
      .join(' ')
    return {
      answer: String(result?.answer || '暂时没有可用回答。'),
      citations: Array.isArray(result?.citations) ? result.citations : [],
      fallbackRequired: result?.status === 'fallback_required',
      fallbackNotice,
      // 透传 warnings 数组，供未来面板展示（本次面板已有 fallbackNotice 展示位）。
      warnings,
      // TeachingAgent 不返回 confidence 数值；有 warnings/degraded_services 时标低置信。
      lowConfidence:
        Boolean(warnings.length) || Boolean(result?.degraded_services?.length),
    }
  }

  // V1 问答（/chat/ask）：始终可用的回退路径，不受 Agent 能力开关影响。
  function setCodeSubmissionId(runId) {
    codeSubmissionId.value = runId == null || runId === '' ? null : String(runId)
    if (codeSubmissionId.value) {
      window.localStorage.setItem(codeRunStorageKey, codeSubmissionId.value)
    } else {
      window.localStorage.removeItem(codeRunStorageKey)
    }
  }

  async function askV1(question) {
    const result = await askQuestion({
      question,
      courseId: course.value.courseId,
      currentNodeId: currentNodeId.value,
    })
    return {
      answer: String(result?.answer || '暂时没有可用回答。'),
      citations: Array.isArray(result?.citations) ? result.citations : [],
      lowConfidence: result?.confidence !== undefined && Number(result.confidence) < 0.5,
    }
  }

  async function sendQuestion(explicitQuestion) {
    const question = String(explicitQuestion ?? questionDraft.value).trim()
    if (!question || isAsking.value || !currentNode.value) return

    const userMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      content: question,
      nodeId: currentNodeId.value,
      page: currentPage.value,
      time: currentTime.value,
    }
    messages.value = [...messages.value, userMessage]
    questionDraft.value = ''
    isAsking.value = true

    // TeachingAgent 受控接入：能力开关（cognitive_analysis）+ analytics_eligible
    // （真实学生）+ studentId 三重校验。任一不满足则直接走 V1，不尝试 Agent。
    const studentId = getStudentId()
    const analyticsEligible = getAnalyticsEligible()
    const capabilities = getCapabilities()
    const canUseTeachingAgent = Boolean(
      capabilities?.cognitive_analysis && analyticsEligible && studentId != null,
    )

    try {
      let result
      if (canUseTeachingAgent) {
        // Agent 503/失败属预期降级场景（skipErrorToast 已静默），回退 V1 不影响 Q&A。
        try {
          result = await askTeachingAgent(question)
          if (result.fallbackRequired) {
            const fallback = await askV1(question)
            result = {
              ...fallback,
              fallbackNotice: result.fallbackNotice,
              warnings: result.warnings,
            }
          }
        } catch {
          result = await askV1(question)
        }
      } else {
        result = await askV1(question)
      }
      messages.value = [
        ...messages.value,
        {
          id: 'assistant-' + Date.now(),
          role: 'assistant',
          content: result.answer,
          citations: result.citations,
          lowConfidence: result.lowConfidence,
          fallbackNotice: result.fallbackNotice || '',
          nodeId: currentNodeId.value,
          page: currentPage.value,
        },
      ]
    } catch {
      messages.value = [
        ...messages.value,
        {
          id: 'assistant-error-' + Date.now(),
          role: 'assistant',
          content: '回答请求失败，请检查网络后重试。',
          error: true,
          retryQuestion: question,
        },
      ]
    } finally {
      isAsking.value = false
    }
  }

  async function saveProgress(options = {}) {
    if (previewMode) return
    if (!course.value || status.value !== 'ready') return
    if (!options.silent) saveState.value = 'saving'

    // 听课时长埋点：计算自上次保存以来的听课秒数（仅 playing 时累计）。
    // 后端把 delta 累加到当前节点的 NodeProgress.time_spent。
    const now = Date.now()
    let timeSpentDelta = 0
    if (isPlaying.value && lastProgressSaveAt > 0) {
      timeSpentDelta = Math.min(60, Math.max(0, (now - lastProgressSaveAt) / 1000))
    }
    lastProgressSaveAt = now

    try {
      if (releaseId.value) {
        const node = currentNode.value
        if (node?.outlineNodeId) {
          queueLearningEvent(node.outlineNodeId, 'media_progress', {
            progress_ratio: node.timestampEnd > node.timestampStart
              ? clamp((currentTime.value - node.timestampStart) / (node.timestampEnd - node.timestampStart), 0, 1)
              : 0,
            current_timestamp: currentTime.value,
            current_page: currentPage.value,
            time_spent_delta: timeSpentDelta,
          })
        }
        await flushLearningEvents()
        saveState.value = 'saved'
        return
      }
      await savePlayerProgress(
        buildProgressPayload({
          courseId: course.value.courseId,
          currentNodeId: currentNodeId.value,
          currentTime: currentTime.value,
          currentPage: currentPage.value,
          completedNodes: completedNodes.value,
          timeSpentDelta,
        })
      )
      saveState.value = 'saved'
    } catch {
      saveState.value = 'error'
    }
  }

  function queueLearningEvent(outlineNodeId, eventType, payload = {}) {
    if (previewMode || !releaseId.value || !outlineNodeId) return
    const nonce = (typeof crypto !== 'undefined' && crypto?.randomUUID?.()) || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const idempotencyKey = `learn:${courseId}:${releaseId.value}:${outlineNodeId}:${eventType}:${nonce}`
    const event = { release_id: releaseId.value, outline_node_id: outlineNodeId, event_type: eventType, idempotency_key: idempotencyKey, payload }
    pendingLearningEvents.value = [...pendingLearningEvents.value, event].slice(-20)
    writeJson(learningQueueStorageKey, pendingLearningEvents.value)
    flushLearningEvents()
  }

  async function completeCurrentNode() {
    const node = currentNode.value
    if (previewMode || !node?.outlineNodeId || !releaseId.value) return false
    const idempotencyKey = `complete:${courseId}:${releaseId.value}:${node.outlineNodeId}`
    try {
      await completeLearningAction(courseId, {
        release_id: releaseId.value,
        outline_node_id: node.outlineNodeId,
        idempotency_key: idempotencyKey,
      })
      if (!completedNodes.value.includes(node.id)) {
        completedNodes.value = [...completedNodes.value, node.id]
      }
      await refreshLearningContext().catch(() => {})
      return true
    } catch {
      saveState.value = 'error'
      return false
    }
  }

  async function flushLearningEvents() {
    if (previewMode || flushingLearningEvents || !pendingLearningEvents.value.length) return
    flushingLearningEvents = true
    try {
      const queue = [...pendingLearningEvents.value]
      for (const event of queue) {
        try {
          await recordLearningEvent(courseId, event)
          pendingLearningEvents.value = pendingLearningEvents.value.filter(item => item.idempotency_key !== event.idempotency_key)
          writeJson(learningQueueStorageKey, pendingLearningEvents.value)
        } catch {
          break
        }
      }
    } finally {
      flushingLearningEvents = false
    }
  }

  function startProgressTimer() {
    window.clearInterval(progressTimer)
    // 进入就绪态后初始化时间戳，避免首次保存计入加载耗时。
    lastProgressSaveAt = Date.now()
    progressTimer = window.setInterval(() => {
      if (isPlaying.value) saveProgress({ silent: true })
    }, 10000)
  }

  watch(
    [
      mode,
      playbackRate,
      volume,
      isMuted,
      captionsEnabled,
      outlineOpen,
      assistantOpen,
      notesOpen,
      questionDraft,
    ],
    persistViewState
  )

  onBeforeUnmount(() => {
    window.clearTimeout(viewPersistTimer)
    window.clearInterval(progressTimer)
    persistViewState()
    saveProgress({ silent: true })
  })

  return {
    status,
    error,
    course,
    mode,
    nodes,
    slides,
    pptPages,
    currentNode,
    currentNodeIndex,
    currentTime,
    currentPage,
    currentSlide,
    currentPptPage,
    currentNodeId,
    totalPages,
    currentVideoUrl,
    completedNodes,
    releaseId,
    learningContext,
    learningItems,
    learningItemsByNodeId,
    expandedNodeId,
    cognitiveDetails,
    cognitiveLoading,
    getNodeDisplayState,
    loadNodeCognition,
    toggleNodeCognition,
    refreshLearningContext,
    pendingLearningEvents,
    queueLearningEvent,
    flushLearningEvents,
    completeCurrentNode,
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
    returnAnchor,
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
    captureReturnAnchor,
    restoreReturnAnchor,
    sendQuestion,
    setCodeSubmissionId,
    saveProgress,
  }
}
