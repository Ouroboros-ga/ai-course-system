<template>
  <div class="student-dashboard">
    <!-- 课程选择界面 -->
    <div v-if="!selectedCourse" class="course-selection">
      <div class="selection-header">
        <h2>📚 我的课程</h2>
        <p class="subtitle">选择老师制作的智课开始学习</p>
      </div>

      <div class="courses-container">
        <div v-if="isLoadingCourses" class="loading-state">
          <div class="spinner"></div>
          <span>正在加载课程...</span>
        </div>

        <div v-else-if="availableCourses.length === 0" class="empty-state">
          <div class="empty-icon">📖</div>
          <h3>暂无可用课程</h3>
          <p>老师还没有发布任何智课</p>
        </div>

        <div v-else class="courses-grid">
          <div
            v-for="course in availableCourses"
            :key="course.id"
            class="course-card"
            @click="selectCourse(course)"
          >
            <div class="card-header">
              <span class="course-icon">📐</span>
              <span class="status-badge" :class="course.status">
                {{ getStatusLabel(course.status) }}
              </span>
            </div>
            <div class="card-body">
              <h3 class="course-title">{{ course.title }}</h3>
              <p class="course-desc">{{ course.description || '暂无描述' }}</p>
              <div class="course-meta">
                <span class="meta-item">👨‍🏫 {{ course.teacher_name || '未知教师' }}</span>
                <span class="meta-item">📖 {{ course.total_nodes || 0 }} 个知识点</span>
                <span class="meta-item">⏱️ {{ formatDuration(course.total_duration) }}</span>
              </div>
            </div>
            <div class="card-footer">
              <button
                class="start-btn"
                @click.stop="enterCourse(course)"
                :disabled="course.status !== 'published'"
              >
                {{ course.status === 'published' ? '🚀 开始学习 →' : '⏳ 未发布' }}
              </button>
              <button
                v-if="course.status === 'published'"
                class="preview-btn"
                @click.stop="previewCourse(course)"
              >
                👁️ 预览
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 学习界面（类Chat） -->
    <div v-else class="learning-interface">
      <!-- 左侧：学习进度面板 -->
      <div class="progress-panel">
        <div class="panel-header">
          <h3>{{ selectedCourse.title }}</h3>
          <button class="back-btn" @click="exitCourse">← 返回</button>
        </div>

        <!-- 章节导航树 -->
        <div class="chapter-tree">
          <div class="tree-header">
            <span>📋 课程结构</span>
            <span class="node-count">{{ scriptNodes.length }} 个节点</span>
          </div>

          <div v-if="scriptNodes.length === 0" class="tree-empty">
            正在加载课程内容...
          </div>

          <div v-else class="tree-list">
            <div
              v-for="(node, index) in scriptNodes"
              :key="node.id"
              class="tree-node"
              :class="{
                active: currentNodeIndex === index,
                completed: isNodeCompleted(index),
                current: currentNodeIndex === index
              }"
              @click="jumpToNode(index)"
            >
              <div class="node-status">
                <span v-if="isNodeCompleted(index)" class="status-icon completed">✅</span>
                <span v-else-if="currentNodeIndex === index" class="status-icon current">▶️</span>
                <span v-else class="status-icon pending">⭕</span>
              </div>

              <div class="node-info">
                <span class="node-type-icon">{{ getNodeTypeIcon(node.node_type) }}</span>
                <span class="node-title">{{ node.title || `节点 ${index + 1}` }}</span>
              </div>

              <!-- 学理解度可视化 -->
              <div v-if="getNodeProgress(index)" class="understanding-bar">
                <div
                  class="understanding-fill"
                  :style="{ width: getNodeProgress(index).score + '%' }"
                  :class="getUnderstandingClass(getNodeProgress(index).level)"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 总体学习进度 -->
        <div class="overall-progress">
          <div class="progress-label">总体进度</div>
          <div class="progress-bar">
            <div
              class="progress-fill"
              :style="{ width: overallProgress + '%' }"
            ></div>
          </div>
          <div class="progress-text">{{ overallProgress.toFixed(0) }}% 完成</div>
        </div>
      </div>

      <!-- 右侧：Chat式学习区域 -->
      <div class="chat-learning-area">
        <!-- 消息列表 -->
        <div class="message-list" ref="messageListRef">
          <!-- 欢迎消息 -->
          <div class="message-row ai-message">
            <div class="avatar ai-avatar">AI</div>
            <div class="bubble ai-bubble">
              <div class="welcome-content">
                <h4>🎓 欢迎来到《{{ selectedCourse.title }}》</h4>
                <p>我将按照文档结构为您讲解课程内容，每讲完一个小节会进行互动问答来检验您的理解程度。</p>
                <button
                  v-if="!isStreaming && currentNodeIndex === 0"
                  class="start-learning-btn"
                  @click="startLearning"
                >
                  🚀 开始学习
                </button>
              </div>
            </div>
          </div>

          <!-- 流式输出的消息 -->
          <div
            v-for="(msg, index) in chatMessages"
            :key="msg.id || index"
            :class="['message-row', msg.role === 'user' ? 'user-message' : 'ai-message']"
          >
            <div class="avatar" :class="msg.role === 'user' ? 'user-avatar' : 'ai-avatar'">
              {{ msg.role === 'user' ? '👤' : 'AI' }}
            </div>
            <div class="bubble" :class="msg.role === 'user' ? 'user-bubble' : 'ai-bubble'">
              <!-- AI消息：Markdown+KaTeX渲染 -->
              <div v-if="msg.role === 'ai'" class="ai-content markdown-body" v-html="renderContent(msg.content)"></div>
              <!-- 用户消息 -->
              <div v-else class="user-content">{{ msg.content }}</div>

              <!-- 学理解度分析结果（仅AI问答后显示） -->
              <div v-if="msg.understandingAnalysis" class="analysis-card">
                <div class="analysis-header">
                  <span>🧠 理解度分析</span>
                  <span
                    class="level-badge"
                    :class="msg.understandingAnalysis.level"
                  >
                    {{ getLevelLabel(msg.understandingAnalysis.level) }}
                  </span>
                </div>
                <div class="analysis-score">
                  <div class="score-circle" :style="{ '--score': msg.understandingAnalysis.score }">
                    {{ (msg.understandingAnalysis.score * 100).toFixed(0) }}%
                  </div>
                </div>
                <div v-if="msg.understandingAnalysis.keywordsWeak?.length" class="keywords-weak">
                  <span class="label">薄弱点：</span>
                  <span
                    v-for="kw in msg.understandingAnalysis.keywordsWeak"
                    :key="kw"
                    class="keyword-tag weak"
                  >{{ kw }}</span>
                </div>
                <div v-if="msg.understandingAnalysis.suggestions" class="suggestions">
                  💡 {{ msg.understandingAnalysis.suggestions }}
                </div>
              </div>
            </div>
          </div>

          <!-- 流式输出中的消息 -->
          <div v-if="isStreaming" class="message-row ai-message streaming">
            <div class="avatar ai-avatar">AI</div>
            <div class="bubble ai-bubble">
              <div class="streaming-content markdown-body" v-html="renderContent(streamingContent)"></div>
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <div class="input-wrapper">
            <input
              type="text"
              v-model="userInput"
              placeholder="输入您的问题或回答..."
              @keyup.enter="sendMessage"
              :disabled="isStreaming || !canInput"
              class="chat-input"
            />
            <button
              class="send-btn"
              @click="sendMessage"
              :disabled="!userInput.trim() || isStreaming || !canInput"
            >
              发送
            </button>
          </div>
          <div class="input-hint" v-if="!canInput">
            ⏳ 请等待当前内容讲解完成...
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import katex from 'katex'
import { showToast } from '@/utils/toast'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'

const counter = useCounterStore()

// 引入样式
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.css'

// ========== 状态变量 ==========
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
const messageListRef = ref(null)

// 学习进度数据
const nodeProgressMap = ref({})

// Marked实例
const markedInstance = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    }
  })
)
markedInstance.setOptions({ gfm: true, breaks: true })

// ========== 计算属性 ==========

// 总体学习进度
const overallProgress = computed(() => {
  if (scriptNodes.value.length === 0) return 0
  const completed = scriptNodes.value.filter((_, i) => isNodeCompleted(i)).length
  return (completed / scriptNodes.value.length) * 100
})

// ========== 方法 ==========

// 获取状态标签
function getStatusLabel(status) {
  const map = { published: '已发布', draft: '草稿', archived: '已归档' }
  return map[status] || status
}

// 格式化时长
function formatDuration(seconds) {
  if (!seconds) return '0分钟'
  const mins = Math.floor(seconds / 60)
  return `${mins}分钟`
}

// 获取节点类型图标
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

// 检查节点是否已完成
function isNodeCompleted(index) {
  const progress = nodeProgressMap.value[index]
  return progress?.completed || false
}

// 获取节点进度
function getNodeProgress(index) {
  return nodeProgressMap.value[index] || null
}

// 获取理解度等级样式
function getUnderstandingClass(level) {
  const map = {
    excellent: 'level-excellent',
    high: 'level-high',
    medium: 'level-medium',
    low: 'level-low',
  }
  return map[level] || 'level-medium'
}

// 获取等级标签
function getLevelLabel(level) {
  const labels = {
    excellent: '优秀',
    high: '良好',
    medium: '一般',
    low: '需加强',
  }
  return labels[level] || level
}

// 内容渲染（Markdown + KaTeX）
function renderContent(text) {
  if (!text) return ''

  try {
    // 提取公式
    const formulas = []
    let index = 0
    let processedText = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, formula) => {
      const placeholder = `%%BLOCK_${index}%%`
      formulas.push({ placeholder, formula: formula.trim(), isBlock: true })
      index++
      return placeholder
    })
    processedText = processedText.replace(/\$([^\$\n]+?)\$/g, (match, formula) => {
      const placeholder = `%%INLINE_${index}%%`
      formulas.push({ placeholder, formula: formula.trim(), isBlock: false })
      index++
      return placeholder
    })

    // 解析Markdown
    const rawHtml = markedInstance.parse(processedText, { async: false })

    // 渲染公式
    let result = rawHtml
    formulas.forEach(({ placeholder, formula, isBlock }) => {
      try {
        const rendered = katex.renderToString(formula, {
          displayMode: isBlock,
          throwOnError: false,
        })
        const wrappedHtml = isBlock
          ? `<div class="katex-block">${rendered}</div>`
          : `<span class="katex-inline">${rendered}</span>`
        result = result.replace(placeholder, wrappedHtml)
      } catch (e) {
        console.warn('KaTeX渲染失败:', e.message)
      }
    })

    return DOMPurify.sanitize(result, { ADD_ATTR: ['class', 'style'], ADD_TAGS: ['span', 'div'] })
  } catch (e) {
    console.error('渲染失败:', e)
    return `<pre>${text}</pre>`
  }
}

// 加载可用课程列表
async function loadAvailableCourses() {
  isLoadingCourses.value = true
  try {
    const response = await fetch(`http://localhost:8000/api/v1/document/courses`, {
      headers: { Authorization: `Bearer ${counter.token}` }
    })

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200) {
        availableCourses.value = data.data.courses || []
      }
    } else {
      console.error('加载课程失败')
    }
  } catch (error) {
    console.error('加载课程出错:', error)
    showToast('加载课程失败', 'error')
  } finally {
    isLoadingCourses.value = false
  }
}

// 选择课程
function selectCourse(course) {
  selectedCourse.value = course
  loadCourseContent(course.id)
}

// 进入课程
async function enterCourse(course) {
  selectedCourse.value = course

  // 调用选课API
  try {
    const response = await fetch(`http://localhost:8000/api/v1/document/course/${course.id}/enroll`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${counter.token}` }
    })

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200) {
        console.log('选课成功:', data.data)
        if (!data.data.already_enrolled && !data.data.reactivated) {
          showToast('成功加入课程！', 'success')
        }
      }
    } else {
      const errorData = await response.json()
      showToast(errorData.message || '选课失败', 'warning')
    }
  } catch (error) {
    console.error('选课请求失败:', error)
    // 即使选课API失败，也继续加载课程内容（允许离线学习）
  }

  loadCourseContent(course.id)
}

// 预览课程（不选课，只查看内容）
function previewCourse(course) {
  selectedCourse.value = course
  loadCourseContent(course.id)
  showToast('预览模式：学习进度不会保存', 'info')
}

// 退出课程
function exitCourse() {
  selectedCourse.value = null
  scriptNodes.value = []
  chatMessages.value = []
  currentNodeIndex.value = 0
  nodeProgressMap.value = {}
  canInput.value = false
}

// 加载课程内容和脚本节点
async function loadCourseContent(courseId) {
  try {
    showToast('正在加载课程内容...', 'info')

    // 加载课程详情和节点
    const response = await fetch(
      `http://localhost:8000/api/v1/document/course/${courseId}`,
      { headers: { Authorization: `Bearer ${counter.token}` } }
    )

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200 && data.data) {
        // 设置节点数据
        if (data.data.nodes && data.data.nodes.length > 0) {
          scriptNodes.value = data.data.nodes.map(node => ({
            id: node.id,
            node_index: node.node_index,
            node_type: node.node_type || 'lecture',
            title: node.title || `章节 ${node.node_index + 1}`,
            content: node.content || '',
            duration: node.duration || 60,
            is_key_point: node.is_key_point || false,
          }))
        }

        // 加载学习进度
        if (data.data.progress) {
          updateProgressFromServer(data.data.progress)
        }

        showToast(`课程加载成功: ${scriptNodes.value.length} 个知识点`, 'success')
      }
    }
  } catch (error) {
    console.error('加载课程内容失败:', error)
    showToast('加载课程内容失败', 'error')
  }
}

// 更新进度数据
function updateProgressFromServer(progressData) {
  if (!progressData) return

  if (progressData.nodes_progress) {
    progressData.nodes_progress.forEach(np => {
      nodeProgressMap.value[np.index] = {
        completed: np.is_completed,
        score: np.understanding_score ? np.understanding_score * 100 : 0,
        level: np.understanding_level,
        questions: np.question_count || 0,
      }
    })
  }
}

// 开始学习
async function startLearning() {
  if (scriptNodes.value.length === 0) {
    showToast('课程内容为空', 'warning')
    return
  }

  currentNodeIndex.value = 0
  canInput.value = false

  // 从第一个节点开始流式输出
  await streamCurrentNode()
}

// 流式输出当前节点内容
async function streamCurrentNode() {
  if (currentNodeIndex.value >= scriptNodes.value.length) {
    showToast('🎉 课程学习完成！', 'success')
    canInput.value = false
    return
  }

  const node = scriptNodes.value[currentNodeIndex.value]
  isStreaming.value = true
  streamingContent.value = ''
  canInput.value = false

  // 构建带标题的内容
  const fullContent = `## ${node.title}\n\n${node.content}`

  // 模拟流式输出效果
  const chunkSize = 15
  let position = 0

  while (position < fullContent.length) {
    await new Promise(resolve => setTimeout(resolve, 30))
    position += chunkSize
    streamingContent.value = fullContent.substring(0, position)
    scrollToBottom()
  }

  // 输出完成，添加到消息列表
  chatMessages.value.push({
    id: Date.now(),
    role: 'ai',
    content: fullContent,
    nodeId: node.id,
    nodeIndex: currentNodeIndex.value,
  })

  isStreaming.value = false
  streamingContent.value = ''

  // 标记节点为已访问
  markNodeVisited(currentNodeIndex.value)

  // 生成AI问答
  await generateQAForNode(node)

  // 允许用户输入
  canInput.value = true
  scrollToBottom()
}

// 标记节点为已访问
function markNodeVisited(index) {
  if (!nodeProgressMap.value[index]) {
    nodeProgressMap.value[index] = {
      completed: false,
      score: 0,
      level: null,
      questions: 0,
    }
  }
}

// 为当前节点生成AI问答
async function generateQAForNode(node) {
  try {
    showToast('正在生成互动问答...', 'info')

    const response = await fetch('http://localhost:8000/api/v1/chat/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${counter.token}`,
      },
      body: JSON.stringify({
        courseId: selectedCourse.value.id,
        currentNodeId: node.id,
        question: `请根据以下内容生成一个检验理解的问题：\n\n${node.content.substring(0, 500)}`,
        strictMode: false,
      }),
    })

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200) {
        // 添加AI问答消息
        chatMessages.value.push({
          id: Date.now() + 1,
          role: 'ai',
          content: `### ❓ 互动问答\n\n${data.data.answer}\n\n请回答以上问题以检验您的理解程度：`,
          understandingAnalysis: data.data.understandingAnalysis,
          isQA: true,
        })

        scrollToBottom()
      }
    }
  } catch (error) {
    console.error('生成问答失败:', error)
    // 如果API调用失败，使用默认问题
    chatMessages.value.push({
      id: Date.now() + 1,
      role: 'ai',
      content: `### ❓ 互动问答\n\n关于"${node.title}"这个知识点，您有什么疑问或需要进一步解释的地方吗？`,
      isQA: true,
    })
    scrollToBottom()
  }
}

// 发送用户消息
async function sendMessage() {
  if (!userInput.value.trim() || isStreaming.value || !canInput.value) return

  const message = userInput.value.trim()
  userInput.value = ''

  // 添加用户消息
  chatMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: message,
  })

  canInput.value = false
  scrollToBottom()

  try {
    // 调用AI问答接口分析回答
    const currentNode = scriptNodes.value[currentNodeIndex.value]

    const response = await fetch('http://localhost:8000/api/v1/chat/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${counter.token}`,
      },
      body: JSON.stringify({
        courseId: selectedCourse.value.id,
        currentNodeId: currentNode?.id,
        question: message,
        strictMode: false,
      }),
    })

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200) {
        // 更新学理解度
        if (data.data.understandingAnalysis) {
          updateNodeUnderstanding(
            currentNodeIndex.value,
            data.data.understandingAnalysis
          )
        }

        // 添加AI回复
        chatMessages.value.push({
          id: Date.now() + 1,
          role: 'ai',
          content: data.data.answer,
          understandingAnalysis: data.data.understandingAnalysis,
        })
      }
    }
  } catch (error) {
    console.error('发送消息失败:', error)
    chatMessages.value.push({
      id: Date.now() + 1,
      role: 'ai',
      content: '抱歉，处理您的回答时出现了错误，请稍后重试。',
    })
  }

  canInput.value = true
  scrollToBottom()
}

// 更新节点的理解度数据
function updateNodeUnderstanding(index, analysis) {
  if (!nodeProgressMap.value[index]) {
    nodeProgressMap.value[index] = {
      completed: false,
      score: 0,
      level: null,
      questions: 0,
    }
  }

  nodeProgressMap.value[index].score = analysis.score * 100
  nodeProgressMap.value[index].level = analysis.level
  nodeProgressMap.value[index].questions += 1

  // 如果理解度超过70%，标记为基本掌握
  if (analysis.score >= 0.7) {
    nodeProgressMap.value[index].completed = true
  }

  // 保存到服务器
  saveProgressToServer(index, analysis)
}

// 保存进度到服务器
async function saveProgressToServer(index, analysis) {
  try {
    const node = scriptNodes.value[index]
    if (!node || !selectedCourse.value) return

    const response = await fetch('http://localhost:8000/api/v1/progress/sync', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${counter.token}`,
      },
      body: JSON.stringify({
        courseId: selectedCourse.value.id,
        nodeId: node.id,
        nodeIndex: index,
        understandingLevel: analysis.level,
        understandingScore: analysis.score,
        studyTime: 60, // 默认学习时长（秒）
        totalNodes: scriptNodes.value.length,
      }),
    })

    if (response.ok) {
      const data = await response.json()
      if (data.code === 200) {
        console.log('进度保存成功:', data.data)
      }
    } else {
      console.error('进度保存失败')
    }
  } catch (error) {
    console.error('保存进度请求失败:', error)
  }
}

// 跳转到指定节点
function jumpToNode(index) {
  if (index === currentNodeIndex.value) return
  if (index < 0 || index >= scriptNodes.value.length) return

  currentNodeIndex.value = index
  canInput.value = false
  isStreaming.value = false
  streamingContent.value = ''

  // 清空当前聊天记录，重新开始该节点的学习
  chatMessages.value = []

  // 添加跳转提示
  chatMessages.value.push({
    id: Date.now(),
    role: 'ai',
    content: `## 📍 跳转至：${scriptNodes.value[index]?.title || `节点 ${index + 1}`}\n\n正在加载内容，请稍候...`,
  })

  // 延迟后开始流式输出该节点内容
  setTimeout(() => {
    streamCurrentNode()
  }, 300)
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

// 组件挂载时加载课程
onMounted(() => {
  loadAvailableCourses()
})
</script>

<!-- 全局样式 -->
<style>
/* Markdown内容样式 */
.markdown-body {
  font-size: 15px;
  line-height: 1.8;
  color: #374151;
}

.markdown-body h1, .markdown-body h2, .markdown-body h3,
.markdown-body h4 {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #111827;
}

.markdown-body h2 {
  font-size: 1.4em;
  border-bottom: 2px solid #e5e7eb;
  padding-bottom: 0.3em;
}

.markdown-body p { margin: 0.8em 0; }

.markdown-body code:not(pre code) {
  background: #f1f5f9;
  color: #dc2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.markdown-body pre {
  background: #1e293b;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-body pre code {
  background: transparent;
  color: #e2e8f0;
}

.markdown-body blockquote {
  border-left: 4px solid #6366f1;
  background: #f8fafc;
  padding: 8px 16px;
  margin: 1em 0;
  border-radius: 0 8px 8px 0;
  color: #4b5563;
}

.markdown-body ul, .markdown-body ol {
  padding-left: 1.5em;
  margin: 0.5em 0;
}

.markdown-body li { margin: 0.3em 0; }

/* KaTeX公式 */
.katex-inline { display: inline; padding: 0 2px; }

.katex-block {
  display: block;
  text-align: center;
  margin: 1em 0;
  padding: 1em;
  background: #f8fafc;
  border-radius: 8px;
  overflow-x: auto;
}
</style>

<style scoped>
.student-dashboard {
  width: 100%;
  height: calc(100vh - 80px);
  background: #f5f7fa;
  overflow: hidden;
}

/* ========== 课程选择界面 ========== */
.course-selection {
  height: 100%;
  padding: 24px;
  overflow-y: auto;
}

.selection-header {
  margin-bottom: 24px;
}

.selection-header h2 {
  font-size: 28px;
  color: #111827;
  margin-bottom: 8px;
}

.subtitle {
  font-size: 16px;
  color: #6b7280;
}

.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
  max-width: 1400px;
}

.course-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.course-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-icon { font-size: 32px; }

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.published { background: #d1fae5; color: #065f46; }
.status-badge.draft { background: #fef3c7; color: #92400e; }
.status-badge.archived { background: #f3f4f6; color: #6b7280; }

.course-title {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.course-desc {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.5;
  margin: 0;
}

.course-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #9ca3af;
}

.start-btn {
  width: 100%;
  padding: 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.start-btn:hover {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.start-btn:disabled {
  background: linear-gradient(135deg, #9ca3af, #6b7280);
  cursor: not-allowed;
  opacity: 0.6;
}

.preview-btn {
  flex: 1;
  padding: 10px;
  background: #f3f4f6;
  color: #374151;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.preview-btn:hover {
  background: #e5e7eb;
  transform: scale(1.02);
}

.card-footer {
  display: flex;
  gap: 10px;
}

.loading-state, .empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #6b7280;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.empty-icon { font-size: 64px; margin-bottom: 16px; }

/* ========== 学习界面 ========== */
.learning-interface {
  display: flex;
  height: 100%;
  gap: 0;
}

/* ========== 左侧进度面板 ========== */
.progress-panel {
  width: 320px;
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.panel-header {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.back-btn {
  padding: 6px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.back-btn:hover { background: #f3f4f6; }

.chapter-tree {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}

.node-count { color: #6366f1; font-weight: normal; }

.tree-empty {
  text-align: center;
  color: #9ca3af;
  padding: 40px 20px;
  font-size: 13px;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tree-node {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s ease;
  position: relative;
}

.tree-node:hover { background: #f3f4f6; }

.tree-node.active {
  background: linear-gradient(135deg, #eef2ff, #f5f3ff);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}

.tree-node.completed { opacity: 0.75; }

.node-status { flex-shrink: 0; }

.status-icon { font-size: 14px; }

.node-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.node-type-icon { font-size: 13px; flex-shrink: 0; }

.node-title {
  font-size: 13px;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node.active .node-title {
  color: #4f46e5;
  font-weight: 500;
}

/* 理解度条 */
.understanding-bar {
  position: absolute;
  bottom: 0;
  left: 38px;
  right: 8px;
  height: 3px;
  background: #e5e7eb;
  border-radius: 2px;
  overflow: hidden;
}

.understanding-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}

.understanding-fill.level-excellent { background: #10b981; }
.understanding-fill.level-high { background: #6366f1; }
.understanding-fill.level-medium { background: #f59e0b; }
.understanding-fill.level-low { background: #ef4444; }

/* 总体进度 */
.overall-progress {
  padding: 16px;
  border-top: 1px solid #e5e7eb;
  background: #fafbfc;
}

.progress-label {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
}

.progress-bar {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

/* ========== 右侧Chat学习区 ========== */
.chat-learning-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fafbfc;
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-row {
  display: flex;
  gap: 12px;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.user-message { flex-direction: row-reverse; }

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: bold;
  flex-shrink: 0;
}

.ai-avatar {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #2563eb;
}

.user-avatar {
  background: #e5e7eb;
  color: #374151;
}

.bubble {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: 12px;
  line-height: 1.6;
}

.ai-bubble {
  background: white;
  border: 1px solid #e5e7eb;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.user-bubble {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border-top-right-radius: 4px;
}

.welcome-content h4 {
  margin: 0 0 8px 0;
  color: #111827;
}

.welcome-content p {
  margin: 0 0 12px 0;
  color: #6b7280;
  font-size: 14px;
}

.start-learning-btn {
  padding: 10px 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.start-learning-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.ai-content, .user-content {
  word-wrap: break-word;
}

.user-content { color: white; }

/* 分析卡片 */
.analysis-card {
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 600;
  color: #374151;
}

.level-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.level-badge.excellent { background: #d1fae5; color: #065f46; }
.level-badge.high { background: #dbeafe; color: #1e40af; }
.level-badge.medium { background: #fef3c7; color: #92400e; }
.level-badge.low { background: #fee2e2; color: #991b1b; }

.analysis-score {
  display: flex;
  justify-content: center;
  margin: 8px 0;
}

.score-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  background: conic-gradient(#6366f1 calc(var(--score) * 3.6deg), #e5e7eb 0);
  color: #374151;
}

.keywords-weak {
  margin: 8px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.label { font-weight: 500; color: #6b7280; margin-right: 4px; }

.keyword-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.keyword-tag.weak { background: #fee2e2; color: #991b1b; }

.suggestions {
  margin-top: 8px;
  padding: 8px;
  background: #fffbeb;
  border-radius: 4px;
  font-size: 12px;
  color: #92400e;
}

/* 流式输出动画 */
.streaming .ai-bubble {
  border-color: #93c5fd;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0 0 0;
  justify-content: flex-start;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #6366f1;
  border-radius: 50%;
  animation: bounce 1.4s ease-in-out infinite;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 输入区域 */
.input-area {
  padding: 16px 20px;
  background: white;
  border-top: 1px solid #e5e7eb;
}

.input-wrapper {
  display: flex;
  gap: 8px;
  max-width: 900px;
  margin: 0 auto;
}

.chat-input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid #d1d5db;
  border-radius: 24px;
  font-size: 14px;
  outline: none;
  transition: all 0.2s ease;
}

.chat-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.chat-input:disabled {
  background: #f9fafb;
  cursor: not-allowed;
}

.send-btn {
  padding: 12px 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
}

/* 响应式设计 */
@media (max-width: 1024px) {
  .learning-interface {
    flex-direction: column;
  }

  .progress-panel {
    width: 100%;
    max-height: 300px;
  }

  .chapter-tree {
    max-height: 180px;
  }
}
</style>
