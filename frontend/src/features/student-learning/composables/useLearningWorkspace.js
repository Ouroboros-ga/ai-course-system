import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { askQuestion } from '@/api/chat.js'
import { respondTeachingAgent } from '@/api/teaching_agent.js'
import { getPlayerInitData, savePlayerProgress } from '@/api/player.js'
import { listNotes, createNote, updateNote } from '@/api/note.js'
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
  const codeSubmissionId = ref(options?.codeSubmissionId ?? null)
  const getCodeSubmissionId = options?.getCodeSubmissionId ?? (() => codeSubmissionId.value)
  // 学习会话 ID：贯穿一次学习会话，TeachingAgent 用作 session_id 关联事件与 trace。
  // Reuse a per-learner/course ID. The server keeps only a bounded structured
  // summary and expires it after 30 minutes; no transcript is persisted.
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
  let viewPersistTimer = null
  let progressTimer = null

  const nodes = computed(() => course.value?.nodes ?? [])
  const slides = computed(() => course.value?.slides ?? [])
  const pptPages = computed(() => course.value?.pptPages ?? [])
  const currentNode = computed(() => nodes.value[currentNodeIndex.value] ?? null)
  const currentNodeId = computed(() => currentNode.value?.id ?? null)
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
      const response = await getPlayerInitData(courseId)
      const normalized = normalizePlayerData(response)
      if (!normalized.nodes.length) {
        throw new Error('课程暂无可学习的讲解节点')
      }

      course.value = normalized
      currentNodeIndex.value = normalized.savedProgress.currentNodeIndex
      currentTime.value = normalized.savedProgress.currentTime
      currentPage.value = normalized.savedProgress.currentPage
      restoreViewState()
      status.value = 'ready'
      startProgressTimer()
      // 批次1：笔记持久化--从后端加载笔记（失败时回退 localStorage）
      loadNotesFromBackend()
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
  }

  function seekTo(globalTime) {
    if (!course.value) return
    const nextTime = clamp(
      Number(globalTime) || 0,
      0,
      course.value.totalDuration || Number.MAX_SAFE_INTEGER
    )
    const nextIndex = findNodeIndexAtTime(nodes.value, nextTime)
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
      seekTo(globalTime)
      if (currentNodeIndex.value > previousIndex) {
        const completedId = nodes.value[previousIndex]?.id
        if (completedId && !completedNodes.value.includes(completedId)) {
          completedNodes.value = [...completedNodes.value, completedId]
        }
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

  // TeachingAgent 受控接入（P1）：调用 /teaching-agent/respond 并归一化响应。
  // 仅在 sendQuestion 中被调用，且仅当 cognitive_analysis 能力开关开启 +
  // analyticsEligible + studentId 三者齐备时触发。失败由调用方回退 V1。
  async function askTeachingAgent(question, studentId) {
    const verifiedRunId = getCodeSubmissionId()
    const result = await respondTeachingAgent({
      student_id: String(studentId),
      course_id: String(course.value.courseId),
      session_id: teachingSessionId,
      message: question,
      resource_id: currentNodeId.value != null ? String(currentNodeId.value) : null,
      code_submission_id: verifiedRunId ? String(verifiedRunId) : null,
    })
    return {
      answer: String(result?.answer || '暂时没有可用回答。'),
      citations: Array.isArray(result?.citations) ? result.citations : [],
      fallbackRequired: result?.status === 'fallback_required',
      fallbackNotice: result?.fallback_reason === 'COURSE_KNOWLEDGE_GRAPH_PENDING'
        ? '课程知识图谱正在解析或暂不可用，本次已使用普通课程问答。'
        : '',
      // TeachingAgent 不返回 confidence 数值；有 warnings/degraded_services 时标低置信。
      lowConfidence:
        Boolean(result?.warnings?.length) || Boolean(result?.degraded_services?.length),
    }
  }

  // V1 问答（/chat/ask）：始终可用的回退路径，不受 Agent 能力开关影响。
  function setCodeSubmissionId(runId) {
    codeSubmissionId.value = runId == null || runId === '' ? null : String(runId)
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
          result = await askTeachingAgent(question, studentId)
          if (result.fallbackRequired) {
            const fallback = await askV1(question)
            result = { ...fallback, fallbackNotice: result.fallbackNotice }
          }
        } catch (agentError) {
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

    try {
      await savePlayerProgress(
        buildProgressPayload({
          courseId: course.value.courseId,
          currentNodeId: currentNodeId.value,
          currentTime: currentTime.value,
          currentPage: currentPage.value,
          completedNodes: completedNodes.value,
        })
      )
      saveState.value = 'saved'
    } catch {
      saveState.value = 'error'
    }
  }

  function startProgressTimer() {
    window.clearInterval(progressTimer)
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
