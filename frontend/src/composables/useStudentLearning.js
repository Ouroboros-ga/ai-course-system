import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from '@/utils/toast'
import { useCounterStore } from '@/stores/counter.js'
import request from '@/utils/request.js'
import { renderContent } from '@/utils/markdownRenderer.js'

export const STUDENT_LEARNING_KEY = Symbol('studentLearning')

export function useStudentLearning() {
  const router = useRouter()
  const counter = useCounterStore()

  const selectedCourse = ref(null)
  const availableCourses = ref([])
  const isLoadingCourses = ref(true)
  const scriptNodes = ref([])
  const currentNodeIndex = ref(0)
  const chatMessages = ref([])
  const userInput = ref('')
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const canInput = ref(false)
  const isComponentMounted = ref(true)
  const nodeProgressMap = ref({})
  const nodeChatHistory = ref({})
  const requestNodeIndex = ref(-1)
  const courseSlides = ref([])
  const courseSlidesTotal = ref(0)
  const currentSlidePage = ref(1)
  const currentNodeAudioUrl = ref('')
  const currentNodeAudioDuration = ref(0)
  const scrollTrigger = ref(0)
  const pendingAutoPlay = ref(false)
  const agentLabel = ref('智能体')

  const overallProgress = computed(() => {
    if (scriptNodes.value.length === 0) return 0
    const completed = scriptNodes.value.filter((_, i) => isNodeCompleted(i)).length
    return (completed / scriptNodes.value.length) * 100
  })

  function getStatusLabel(status) {
    const map = { published: '已发布', draft: '草稿', archived: '已归档' }
    return map[status] || status
  }

  function formatDuration(seconds) {
    if (!seconds) return '0分钟'
    const mins = Math.floor(seconds / 60)
    return `${mins}分钟`
  }

  function getNodeTypeIcon(type) {
    const icons = {
      lecture: '📖',
      question: '❓',
      breakpoint: '🔖',
      summary: '📋',
      video: '🎬',
      interactive: '💬',
    }
    return icons[type] || '📄'
  }

  function isNodeCompleted(index) {
    const progress = nodeProgressMap.value[index]
    return progress?.completed || false
  }

  function getNodeProgress(index) {
    return nodeProgressMap.value[index] || null
  }

  function getUnderstandingClass(level) {
    const map = {
      excellent: 'level-excellent',
      high: 'level-high',
      medium: 'level-medium',
      low: 'level-low',
    }
    return map[level] || 'level-medium'
  }

  function getLevelLabel(level) {
    const labels = {
      excellent: '优秀',
      high: '良好',
      medium: '一般',
      low: '需加强',
    }
    return labels[level] || level
  }

  function triggerScroll() {
    scrollTrigger.value++
  }

  async function loadAvailableCourses() {
    isLoadingCourses.value = true
    try {
      const data = await request({ url: '/document/courses', method: 'get' })
      availableCourses.value = data.courses || []
    } catch (error) {
      showToast('加载课程失败', 'error')
    } finally {
      isLoadingCourses.value = false
    }
  }

  function selectCourse(course) {
    selectedCourse.value = course
    loadCourseContent(course.id)
  }

  async function enterCourse(course) {
    selectedCourse.value = course

    try {
      const data = await request({ url: `/document/course/${course.id}/enroll`, method: 'post' })
      if (!data.already_enrolled && !data.reactivated) {
        showToast('成功加入课程！', 'success')
      }
    } catch (error) {
    }

    loadCourseContent(course.id)
  }

  function enterPlayerMode() {
    if (!selectedCourse.value) return

    router.push({
      name: 'student-player',
      params: { courseId: selectedCourse.value.id },
      query: { title: selectedCourse.value.title },
    })
  }

  function exitCourse() {
    saveCurrentNodeChatHistory()
    selectedCourse.value = null
    scriptNodes.value = []
    chatMessages.value = []
    currentNodeIndex.value = 0
    nodeProgressMap.value = {}
    nodeChatHistory.value = {}
    canInput.value = false
    courseSlides.value = []
    courseSlidesTotal.value = 0
    currentSlidePage.value = 1
    currentNodeAudioUrl.value = ''
    currentNodeAudioDuration.value = 0
  }

  function saveCurrentNodeChatHistory() {
    const idx = currentNodeIndex.value
    if (idx >= 0 && chatMessages.value.length > 0) {
      nodeChatHistory.value[idx] = [...chatMessages.value]
    }
  }

  function saveMessageToNodeHistory(nodeIndex, message) {
    if (!nodeChatHistory.value[nodeIndex]) {
      nodeChatHistory.value[nodeIndex] = []
    }
    nodeChatHistory.value[nodeIndex].push(message)
  }

  async function loadCourseContent(courseId) {
    try {
      showToast('正在加载课程内容...', 'info')

      const data = await request({ url: `/document/course/${courseId}`, method: 'get' })

      if (data) {
        if (data.nodes && data.nodes.length > 0) {
          scriptNodes.value = data.nodes.map(node => ({
            id: node.id,
            node_index: node.node_index,
            node_type: node.node_type || 'lecture',
            title: node.title || `章节 ${node.node_index + 1}`,
            content: node.content || '',
            duration: node.duration || 60,
            is_key_point: node.is_key_point || false,
            page_start: node.page_start || 1,
            page_end: node.page_end || 1,
            audio_url: node.audio_url || '',
            audio_duration: node.audio_duration || 0,
          }))
        }

        if (data.progress) {
          updateProgressFromServer(data.progress)
        }

        loadCourseSlides(courseId)
        updateCurrentNodeMedia()

        showToast(`课程加载成功: ${scriptNodes.value.length} 个知识点`, 'success')
      }
    } catch (error) {
      showToast('加载课程内容失败', 'error')
    }
  }

  async function loadCourseSlides(courseId) {
    try {
      const data = await request({ url: `/document/course/${courseId}/slides`, method: 'get' })
      if (data && data.slides) {
        courseSlides.value = data.slides
        courseSlidesTotal.value = data.total_pages || 0
      } else {
        courseSlides.value = []
        courseSlidesTotal.value = 0
      }
    } catch (error) {
      courseSlides.value = []
      courseSlidesTotal.value = 0
    }
  }

  function updateCurrentNodeMedia() {
    const node = scriptNodes.value[currentNodeIndex.value]
    if (!node) {
      currentSlidePage.value = 1
      currentNodeAudioUrl.value = ''
      currentNodeAudioDuration.value = 0
      return
    }

    currentSlidePage.value = node.page_start || 1
    currentNodeAudioUrl.value = node.audio_url || ''
    currentNodeAudioDuration.value = node.audio_duration || 0
  }

  function onSlidePageChange(page) {
    currentSlidePage.value = page
  }

  function onNodeAudioEnded() {
    const node = scriptNodes.value[currentNodeIndex.value]
    if (node) {
      markNodeCompleted(currentNodeIndex.value)
    }
  }

  function onAutoPlayBlocked() {
    showToast('请点击播放按钮开始收听音频', 'info')
  }

  function updateProgressFromServer(progressData) {
    if (!progressData) return

    if (progressData.nodes_progress) {
      progressData.nodes_progress.forEach(np => {
        nodeProgressMap.value[np.index] = {
          completed: np.is_completed,
          score: np.understanding_score ? np.understanding_score * 100 : null,
          level: np.understanding_level,
          questions: np.question_count || 0,
        }
      })
    }
  }

  async function startLearning() {
    if (scriptNodes.value.length === 0) {
      showToast('课程内容为空', 'warning')
      return
    }

    currentNodeIndex.value = 0
    canInput.value = false

    updateCurrentNodeMedia()
    pendingAutoPlay.value = true

    await streamCurrentNode()
  }

  function onAutoPlayTriggered() {
    pendingAutoPlay.value = false
  }

  async function streamCurrentNode() {
    if (currentNodeIndex.value >= scriptNodes.value.length) {
      showToast('🎉 课程学习完成！', 'success')
      canInput.value = false
      return
    }

    const node = scriptNodes.value[currentNodeIndex.value]
    const streamNodeIndex = currentNodeIndex.value
    isStreaming.value = true
    streamingContent.value = ''
    canInput.value = false

    const fullContent = `## ${node.title}\n\n${node.content}`

    const chunkSize = 15
    let position = 0

    while (position < fullContent.length && isComponentMounted.value) {
      if (currentNodeIndex.value !== streamNodeIndex) return
      await new Promise(resolve => setTimeout(resolve, 30))
      position += chunkSize
      streamingContent.value = fullContent.substring(0, position)
      triggerScroll()
    }

    if (currentNodeIndex.value !== streamNodeIndex) return

    chatMessages.value.push({
      id: Date.now(),
      role: 'ai',
      content: fullContent,
      nodeId: node.id,
      nodeIndex: streamNodeIndex,
    })

    isStreaming.value = false
    streamingContent.value = ''

    markNodeVisited(streamNodeIndex)

    await generateQAForNode(node, streamNodeIndex)

    if (currentNodeIndex.value === streamNodeIndex) {
      canInput.value = true
    }
    triggerScroll()
  }

  function markNodeVisited(index) {
    if (!nodeProgressMap.value[index]) {
      nodeProgressMap.value[index] = {
        completed: false,
        score: null,
        level: null,
        questions: 0,
      }
    }
  }

  function markNodeCompleted(index) {
    if (!nodeProgressMap.value[index]) {
      nodeProgressMap.value[index] = {
        completed: false,
        score: null,
        level: null,
        questions: 0,
      }
    }
    nodeProgressMap.value[index].completed = true
  }

  async function generateQAForNode(node, nodeIndex) {
    requestNodeIndex.value = nodeIndex
    try {
      showToast('正在生成互动问答...', 'info')

      const data = await request({
        url: '/chat/quiz',
        method: 'post',
        data: {
          courseId: selectedCourse.value.id,
          nodeId: node.id,
          nodeTitle: node.title,
        },
      })

      if (!data || !data.quiz) {
        if (currentNodeIndex.value === nodeIndex) {
          chatMessages.value.push({
            id: Date.now() + 1,
            role: 'ai',
            content: `### ❓ 互动问答\n\n关于"${node.title}"这个知识点，您有什么疑问或需要进一步解释的地方吗？`,
            isQA: true,
            nodeIndex: nodeIndex,
          })
          canInput.value = true
        }
        return
      }

      const quizMessage = {
        id: Date.now() + 1,
        role: 'ai',
        content: `### ❓ 互动问答`,
        quiz: data.quiz,
        selectedAnswer: null,
        answerRevealed: false,
        isQA: true,
        nodeIndex: nodeIndex,
      }

      if (currentNodeIndex.value !== nodeIndex) {
        saveMessageToNodeHistory(nodeIndex, quizMessage)
        return
      }

      chatMessages.value.push(quizMessage)
      triggerScroll()
    } catch (error) {
      if (currentNodeIndex.value !== nodeIndex) return

      chatMessages.value.push({
        id: Date.now() + 1,
        role: 'ai',
        content: `### ❓ 互动问答\n\n关于"${node.title}"这个知识点，您有什么疑问或需要进一步解释的地方吗？`,
        isQA: true,
        nodeIndex: nodeIndex,
      })
      triggerScroll()
    }
  }

  function selectQuizOption(msg, optionKey) {
    if (msg.answerRevealed) return

    msg.selectedAnswer = optionKey
    msg.answerRevealed = true

    const isCorrect = optionKey === msg.quiz.correct_answer

    const analysis = {
      level: isCorrect ? 'high' : 'low',
      score: isCorrect ? 0.9 : 0.3,
      keywordsWeak: isCorrect ? [] : [msg.quiz.question.substring(0, 20)],
      suggestions: isCorrect ? '掌握良好，继续学习' : msg.quiz.explanation,
    }

    updateNodeUnderstanding(currentNodeIndex.value, analysis)

    triggerScroll()
  }

  async function sendMessage() {
    if (!userInput.value.trim() || isStreaming.value || !canInput.value) return

    const message = userInput.value.trim()
    const sendNodeIndex = currentNodeIndex.value
    userInput.value = ''

    chatMessages.value.push({
      id: Date.now(),
      role: 'user',
      content: message,
      nodeIndex: sendNodeIndex,
    })

    canInput.value = false
    triggerScroll()

    try {
      const currentNode = scriptNodes.value[sendNodeIndex]

      const data = await request({
        url: '/chat/ask',
        method: 'post',
        data: {
          courseId: selectedCourse.value.id,
          currentNodeId: currentNode?.id,
          question: message,
          strictMode: false,
        },
      })

      const aiMessage = {
        id: Date.now() + 1,
        role: 'ai',
        content: data.answer,
        understandingAnalysis: data.understandingAnalysis,
        nodeIndex: sendNodeIndex,
      }

      if (currentNodeIndex.value !== sendNodeIndex) {
        saveMessageToNodeHistory(sendNodeIndex, aiMessage)
        return
      }

      if (data.understandingAnalysis) {
        const analysis = data?.understandingAnalysis
        if (!analysis) {
          showToast('理解度分析暂时不可用', 'warning')
          return
        }
        updateNodeUnderstanding(
          sendNodeIndex,
          data.understandingAnalysis
        )
      }

      chatMessages.value.push(aiMessage)
    } catch (error) {
      if (currentNodeIndex.value !== sendNodeIndex) return

      chatMessages.value.push({
        id: Date.now() + 1,
        role: 'ai',
        content: '抱歉，处理您的回答时出现了错误，请稍后重试。',
        nodeIndex: sendNodeIndex,
      })
    }

    if (currentNodeIndex.value === sendNodeIndex) {
      canInput.value = true
    }
    triggerScroll()
  }

  function updateNodeUnderstanding(index, analysis) {
    if (!nodeProgressMap.value[index]) {
      nodeProgressMap.value[index] = {
        completed: false,
        score: null,
        level: null,
        questions: 0,
      }
    }

    nodeProgressMap.value[index].score = typeof analysis.score === 'number' ? analysis.score * 100 : 0
    nodeProgressMap.value[index].level = analysis.level
    nodeProgressMap.value[index].questions += 1
    saveProgressToServer(index, analysis)

    if (analysis.score >= 0.7) {
      nodeProgressMap.value[index].completed = true
    }
  }

  async function saveProgressToServer(index, analysis) {
    try {
      const node = scriptNodes.value[index]
      if (!node || !selectedCourse.value) return

      await request({
        url: '/progress/sync',
        method: 'post',
        data: {
          courseId: selectedCourse.value.id,
          nodeId: node.id,
          nodeIndex: index,
          understandingLevel: analysis.level,
          understandingScore: analysis.score,
          studyTime: 60,
          totalNodes: scriptNodes.value.length,
        },
      })
    } catch (error) {
    }
  }

  function jumpToNode(index) {
    if (index === currentNodeIndex.value) return
    if (index < 0 || index >= scriptNodes.value.length) return

    saveCurrentNodeChatHistory()

    currentNodeIndex.value = index
    canInput.value = false
    isStreaming.value = false
    streamingContent.value = ''

    updateCurrentNodeMedia()

    const savedHistory = nodeChatHistory.value[index]
    if (savedHistory && savedHistory.length > 0) {
      chatMessages.value = [...savedHistory]
      canInput.value = true
      triggerScroll()
      return
    }

    chatMessages.value = []

    chatMessages.value.push({
      id: Date.now(),
      role: 'ai',
      content: `## 📍 跳转至：${scriptNodes.value[index]?.title || `节点 ${index + 1}`}\n\n正在加载内容，请稍候...`,
      nodeIndex: index,
    })

    setTimeout(() => {
      if (isComponentMounted.value) {
        streamCurrentNode()
      }
    }, 300)
  }

  onMounted(() => {
    loadAvailableCourses()
  })

  onUnmounted(() => {
    isComponentMounted.value = false
  })

  return {
    selectedCourse,
    availableCourses,
    isLoadingCourses,
    scriptNodes,
    currentNodeIndex,
    chatMessages,
    userInput,
    isStreaming,
    streamingContent,
    canInput,
    nodeProgressMap,
    courseSlides,
    courseSlidesTotal,
    currentSlidePage,
    currentNodeAudioUrl,
    currentNodeAudioDuration,
    scrollTrigger,
    pendingAutoPlay,
    agentLabel,
    overallProgress,
    renderContent,
    getStatusLabel,
    formatDuration,
    getNodeTypeIcon,
    isNodeCompleted,
    getNodeProgress,
    getUnderstandingClass,
    getLevelLabel,
    loadAvailableCourses,
    selectCourse,
    enterCourse,
    exitCourse,
    enterPlayerMode,
    startLearning,
    onAutoPlayTriggered,
    sendMessage,
    selectQuizOption,
    jumpToNode,
    onSlidePageChange,
    onNodeAudioEnded,
    onAutoPlayBlocked,
  }
}
