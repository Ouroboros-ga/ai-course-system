<template>
  <div class="teacher-dashboard">
    <div v-if="isCourseLoading" class="course-loading">
      <div class="spinner"></div>
      <span>正在加载课程数据...</span>
    </div>
    <template v-else>
    <div class="dashboard-header">
      <h2>{{ isEditMode ? '编辑课程' : '基于Docling层级结构的知识点导航与学习' }}</h2>
    </div>

    <div class="dashboard-content">
      <!-- 左侧边栏 -->
      <div class="sidebar">
        <!-- 文档上传区域 -->
        <div class="upload-section">
          <div class="section-title">
            <span class="icon">📁</span>
            上传文档
          </div>
          <div v-if="isFileUploaded" class="uploaded-state">
            <div class="uploaded-info">
              <span class="uploaded-icon">✅</span>
              <span>文档已上传并解析</span>
            </div>
            <button class="back-btn" @click="router.back()">← 返回</button>
          </div>
          <template v-else>
            <div
              class="upload-area"
              :class="{ 'is-uploading': isUploading }"
              @click="triggerFileUpload"
              @dragover.prevent="handleDragOver"
              @dragleave.prevent="handleDragLeave"
              @drop.prevent="handleDrop"
            >
              <input
                type="file"
                ref="fileInput"
                accept=".pdf,.docx,.pptx"
                style="display: none"
                @change="handleFileSelect"
              />
              <div v-if="!isUploading" class="upload-placeholder">
                <div class="upload-icon">📄</div>
                <div class="upload-text">点击或拖拽上传文档</div>
                <div class="upload-hint">支持 PDF、DOCX、PPTX（最大50MB）</div>
              </div>
              <div v-else class="uploading-state">
                <div class="spinner"></div>
                <div>正在解析文档...</div>
                <div class="progress-hint">{{ uploadProgress }}</div>
              </div>
            </div>
          </template>

          <!-- 解析信息 -->
          <div v-if="parseInfo" class="parse-info">
            <div class="info-item">
              <span class="label">公式数量:</span>
              <span class="value">{{ parseInfo.formulaCount }}</span>
            </div>
            <div class="info-item">
              <span class="label">表格数量:</span>
              <span class="value">{{ parseInfo.tableCount }}</span>
            </div>
            <div class="info-item">
              <span class="label">知识点:</span>
              <span class="value">{{ parseInfo.knowledgePointCount }}</span>
            </div>
          </div>
        </div>

        <!-- 知识结构树 -->
        <div class="tree-section">
          <div class="section-title">
            <span class="icon">🌳</span>
            知识结构树
            <span v-if="knowledgeTree.length > 0" class="node-count">({{ knowledgeTree.length }})</span>
          </div>
          <div class="tree-container">
            <div v-if="knowledgeTree.length === 0 && !isUploading" class="empty-tree">
              暂无知识结构，请先上传文档
            </div>
            <div v-else-if="isUploading" class="empty-tree loading">
              正在构建知识结构...
            </div>
            <div v-else class="tree-list">
              <div
                v-for="(node, index) in knowledgeTree"
                :key="node.id || index"
                class="tree-node"
                :class="{ active: currentNodeIndex === index }"
                :style="{ paddingLeft: (12 + (node.level || 0) * 16) + 'px' }"
                @click="selectNode(index)"
              >
                <span class="node-icon">{{ getNodeIcon(node.node_type) }}</span>
                <span class="node-text">{{ node.title || `章节 ${index + 1}` }}</span>
                <span v-if="node.is_key_point" class="key-badge">重点</span>
                <span v-if="node.has_content" class="content-badge">📝</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧主内容区 -->
      <div class="content-main">
        <!-- 顶部导航栏 -->
        <div class="content-header">
          <div class="nav-info">
            <button
              class="nav-btn"
              :disabled="currentNodeIndex <= 0"
              @click="previousNode"
            >
              ◀ 上一个
            </button>
            <span class="page-indicator">
              {{ currentNodeIndex + 1 }} / {{ knowledgeTree.length || 1 }}
            </span>
            <button
              class="nav-btn primary"
              :disabled="currentNodeIndex >= knowledgeTree.length - 1"
              @click="nextNode"
            >
              下一个 ▶
            </button>
          </div>
          <div v-if="currentNode" class="duration-info">
            ⏱️ 预计时长: {{ currentNode.duration || 0 }}分钟
          </div>
        </div>

        <!-- 章节内容 -->
        <div class="chapter-section">
          <div class="chapter-header">
            <h3>{{ currentChapterTitle }}</h3>
            <span class="chapter-tag">{{ getNodeTypeLabel(currentNode?.node_type) }}</span>
          </div>

          <!-- 内容展示区（Markdown + KaTeX渲染） -->
          <div class="content-display">
            <div class="editor-label">智课文本内容</div>
            <div
              v-if="!isEditMode"
              class="markdown-content markdown-body"
              v-html="renderedContent"
            ></div>
            <textarea
              v-else
              v-model="editContent"
              class="content-textarea"
              placeholder="编辑内容..."
            ></textarea>

            <!-- 编辑/预览切换 -->
            <div class="mode-switch">
              <button
                class="switch-btn"
                :class="{ active: !isEditMode }"
                @click="isEditMode = false"
              >
                👁️ 预览模式
              </button>
              <button
                class="switch-btn"
                :class="{ active: isEditMode }"
                @click="enterEditMode"
              >
                ✏️ 编辑模式
              </button>
            </div>
          </div>

          <!-- 音频播放器（已禁用） -->
        </div>

        <!-- 底部操作按钮 -->
        <div class="action-bar">
          <button
            v-if="courseId"
            class="action-btn mapping-btn"
            @click="showMappingEditor = true"
          >
            智课PPT展示管理
          </button>
          <button class="action-btn" @click="saveCurrentNode" :disabled="!hasChanges">
            💾 保存当前修改
          </button>
          <button class="action-btn primary" @click="saveAllNodes">
            🔒 保存全部修改
          </button>
          <button
            v-if="courseId"
            class="action-btn"
            :class="{ 'publish-btn': !isPublished, 'unpublish-btn': isPublished }"
            @click="togglePublishCourse"
            :disabled="isPublishing"
          >
            {{ isPublishing ? '处理中...' : (isPublished ? '📢 已发布' : '🚀 发布课程') }}
          </button>
        </div>

        <!-- 学生统计面板（已禁用） -->
      </div>
    </div>

    <DigitalHumanWindow v-if="courseId && counter.isTeacher" />
    <MappingEditor
      v-model:visible="showMappingEditor"
      :courseId="courseId"
      @applied="showToast('映射已应用，视频生成将使用新映射', 'success')"
    />
  </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import katex from 'katex'
import { showToast } from '@/utils/toast'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'
import request from '@/utils/request.js'
import DigitalHumanWindow from '@/components/chat/DigitalHumanWindow.vue'
import MappingEditor from '@/components/profile/LoginIn/courses/MappingEditor.vue'

const counter = useCounterStore()
const router = useRouter()
const route = useRoute()

// 引入KaTeX样式（非scoped）
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.css'

const fileInput = ref(null)
const audioRef = ref(null)
const knowledgeTree = ref([])
const currentNodeIndex = ref(0)
const editContent = ref('')
const isEditMode = ref(false)
const isUploading = ref(false)
const uploadProgress = ref('准备上传...')
const parseInfo = ref(null)
const isFileUploaded = ref(false)
const courseId = ref(null)
const isCourseLoading = ref(false)

const loadExistingCourse = async (id) => {
  isCourseLoading.value = true
  try {
    const data = await request({ url: `/document/course/${id}`, method: 'get' })

    if (data) {
      courseId.value = id
      isEditMode.value = true
      isFileUploaded.value = true

      if (data.title) {
        document.title = data.title
      }

      if (data.nodes && data.nodes.length > 0) {
        knowledgeTree.value = data.nodes.map((node, index) => ({
          id: node.id || `node_${index}`,
          node_type: node.node_type || (node.level === 0 ? 'chapter' : node.level === 1 ? 'section' : 'subsection'),
          title: node.title || `节点 ${index + 1}`,
          content: node.content || '',
          duration: node.duration || 15,
          is_key_point: node.is_key_point || false,
          level: node.level || 0,
          path: node.path || '',
          has_content: !!node.content,
        }))
      }

      if (data.mindMapJson) {
        buildKnowledgeTreeFromMindMap(data.mindMapJson, data.title || '课程')
        if (data.nodes && data.nodes.length > 0) {
          await loadCourseNodesAndMerge(id)
        }
      }

      if (data.ragInfo) {
        parseInfo.value = data.ragInfo
      }

      if (data.audioUrl) {
        audioUrl.value = data.audioUrl
      }

      if (data.status === 'published') {
        isPublished.value = true
      }

      currentNodeIndex.value = 0
      if (knowledgeTree.value.length > 0) {
        selectNode(0)
      }

      showToast(`课程加载完成: ${knowledgeTree.value.length} 个知识点`, 'success')

      loadCourseStats()
    }
  } catch (error) {
    showToast('加载课程失败，请重试', 'error')
  } finally {
    isCourseLoading.value = false
  }
}

onMounted(() => {
  const routeCourseId = route.params.courseId
  if (routeCourseId) {
    loadExistingCourse(routeCourseId)
  }
})

// 发布课程相关
const isPublished = ref(false)
const isPublishing = ref(false)

// 学生统计相关
const showStudentStats = ref(true)
const showStatsDetail = ref(true)
const isLoadingStats = ref(false)
const courseStats = ref({
  totalStudents: 0,
  avgProgress: 0,
  avgUnderstanding: 0,
  totalStudyHours: 0,
  progressDistribution: null,
})
const studentsList = ref([])

// 音频状态
const audioUrl = ref('')
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const audioProgress = ref(0)
const isGeneratingTTS = ref(false)

// 标记是否有未保存的修改
const hasChanges = ref(false)

// 映射编辑器
const showMappingEditor = ref(false)

// 初始化Marked实例
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

// 当前节点
const currentNode = computed(() => {
  if (knowledgeTree.value.length > 0 && currentNodeIndex.value < knowledgeTree.value.length) {
    return knowledgeTree.value[currentNodeIndex.value]
  }
  return null
})

// 当前章节标题
const currentChapterTitle = computed(() => {
  if (currentNode.value) {
    return currentNode.value.title || `章节 ${currentNodeIndex.value + 1}`
  }
  return '请上传文档开始使用'
})

// 当前内容（用于显示）
const currentContent = computed(() => {
  if (currentNode.value) {
    return currentNode.value.content || ''
  }
  return ''
})

/**
 * 提取并替换数学公式，避免被Markdown解析器处理
 */
function extractFormulas(text) {
  const formulas = []
  let index = 0

  // 处理块级公式 $$...$$
  let processedText = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, formula) => {
    const placeholder = `%%BLOCK_FORMULA_${index}%%`
    formulas.push({ placeholder, formula: formula.trim(), isBlock: true })
    index++
    return placeholder
  })

  // 处理行内公式 $...$
  processedText = processedText.replace(/\$([^$\n]+?)\$/g, (match, formula) => {
    const placeholder = `%%INLINE_FORMULA_${index}%%`
    formulas.push({ placeholder, formula: formula.trim(), isBlock: false })
    index++
    return placeholder
  })

  return { text: processedText, formulas }
}

/**
 * 渲染数学公式
 */
function renderFormulas(html, formulas) {
  let result = html

  formulas.forEach(({ placeholder, formula, isBlock }) => {
    try {
      const rendered = katex.renderToString(formula, {
        displayMode: isBlock,
        throwOnError: false,
        output: 'html',
        strict: false,
        trust: true
      })

      const wrappedHtml = isBlock
        ? `<div class="katex-block">${rendered}</div>`
        : `<span class="katex-inline">${rendered}</span>`

      result = result.replace(placeholder, wrappedHtml)
    } catch (error) {
      const errorHtml = isBlock
        ? `<div class="katex-error">$$${formula}$$</div>`
        : `<span class="katex-error">$${formula}$</span>`
      result = result.replace(placeholder, errorHtml)
    }
  })

  return result
}

// 渲染后的内容（Markdown + KaTeX）
const renderedContent = computed(() => {
  if (!currentContent.value) {
    return '<p class="placeholder">等待AI解析内容...</p>'
  }

  try {
    // 步骤1: 提取数学公式
    const { text: textWithoutFormulas, formulas } = extractFormulas(currentContent.value)

    // 步骤2: 解析Markdown
    const rawHtml = markedInstance.parse(textWithoutFormulas, { async: false })

    // 步骤3: 渲染数学公式
    const htmlWithFormulas = renderFormulas(rawHtml, formulas)

    // 步骤4: 使用DOMPurify清理
    const cleanHtml = DOMPurify.sanitize(htmlWithFormulas, {
      ADD_ATTR: ['class'],
      ADD_TAGS: ['span', 'div']
    })

    return cleanHtml
  } catch (error) {
    return `<pre>${currentContent.value}</pre>`
  }
})

// 获取节点图标
function getNodeIcon(nodeType) {
  const iconMap = {
    'chapter': '📖',
    'section': '📑',
    'subsection': '📄',
    'paragraph': '📝',
    'title': '🏷️',
    'key_point': '⭐',
    'example': '💡',
    'formula': '📐',
    'summary': '📋',
    'lecture': '📚',
    'question': '❓',
  }
  return iconMap[nodeType] || '📚'
}

// 获取节点类型标签
function getNodeTypeLabel(nodeType) {
  const labelMap = {
    'chapter': '章节',
    'section': '小节',
    'subsection': '段落',
    'title': '标题',
    'key_point': '知识点',
    'example': '示例',
    'formula': '公式',
    'summary': '总结',
    'lecture': '讲解',
    'question': '提问',
  }
  return labelMap[nodeType] || '内容'
}

// 触发文件选择
const triggerFileUpload = () => {
  fileInput.value?.click()
}

// 拖拽处理
const handleDragOver = () => {}
const handleDragLeave = () => {}

// 文件选择处理
const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) {
    processFile(file)
  }
}

// 拖拽文件处理
const handleDrop = (event) => {
  event.preventDefault()
  const file = event.dataTransfer.files[0]
  if (file) {
    processFile(file)
  }
}

// 处理文件上传和解析
const processFile = async (file) => {
  // 验证文件类型
  const validTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation'
  ]

  if (!validTypes.includes(file.type) && !file.name.match(/\.(pdf|docx|pptx)$/i)) {
    showToast('仅支持 PDF、DOCX、PPTX 格式', 'error')
    return
  }

  // 验证文件大小（最大50MB）
  if (file.size > 50 * 1024 * 1024) {
    showToast('文件大小超过限制（最大50MB）', 'error')
    return
  }

  isUploading.value = true
  uploadProgress.value = '正在上传文件...'
  knowledgeTree.value = []
  parseInfo.value = null
  audioUrl.value = ''

  try {
    showToast(`正在处理文档: ${file.name}`, 'info')

    // 构建FormData
    const formData = new FormData()
    formData.append('file', file)
    formData.append('fileName', file.name)
    formData.append('userId', counter.userData.id)

    uploadProgress.value = '正在调用Docling解析...'

    // 调用后端API上传和解析文档
    const res = await api.chat.uploadFile(formData)

    if (res) {
      uploadProgress.value = '正在构建知识结构...'

      // 保存课程ID
      courseId.value = res.courseId

      // 设置解析信息
      if (res.ragInfo) {
        parseInfo.value = res.ragInfo
      }

      // 使用mindMapJson构建层级化知识树
      if (res.mindMapJson) {
        buildKnowledgeTreeFromMindMap(res.mindMapJson, res.title || file.name)
      }

      // 从后端获取脚本节点内容，与知识树节点匹配
      if (res.courseId) {
        await loadCourseNodesAndMerge(res.courseId)
      }

      // 设置默认音频URL
      if (res.audioUrl) {
        audioUrl.value = res.audioUrl
      }

      currentNodeIndex.value = 0
      isFileUploaded.value = true
      showToast(`文档解析完成: ${knowledgeTree.value.length} 个知识点`, 'success')

      // 加载课程统计信息（如果有课程ID）
      if (courseId.value) {
        loadCourseStats()
      }
    }
  } catch (error) {
    showToast(error.message || '文档处理失败，请重试', 'error')
  } finally {
    isUploading.value = false
    uploadProgress.value = '准备上传...'
  }
}

// 从mindMapJson构建层级化知识树（展平为可导航列表）
const buildKnowledgeTreeFromMindMap = (mindMap, title) => {
  knowledgeTree.value = []
  
  if (!mindMap || !mindMap.children || mindMap.children.length === 0) {
    if (mindMap && mindMap.text) {
      knowledgeTree.value = [{
        id: 'root',
        node_type: 'chapter',
        title: mindMap.text || title,
        content: '',
        duration: 30,
        is_key_point: false,
        level: 0,
      }]
    }
    return
  }
  
  const flatten = (node, level, parentPath) => {
    const nodeTitle = node.text || node.name || node.label || ''
    const path = parentPath ? `${parentPath}/${nodeTitle}` : nodeTitle
    const hasContent = node.has_content || false
    const isHighlight = node.highlight || false
    
    const item = {
      id: `node_${knowledgeTree.value.length}`,
      node_type: level === 0 ? 'chapter' : level === 1 ? 'section' : 'subsection',
      title: nodeTitle,
      content: '',
      duration: level === 0 ? 30 : level === 1 ? 15 : 10,
      is_key_point: isHighlight,
      level: level,
      path: path,
      has_content: hasContent,
    }
    
    knowledgeTree.value.push(item)
    
    if (node.children && node.children.length > 0) {
      for (const child of node.children) {
        flatten(child, level + 1, path)
      }
    }
  }
  
  if (mindMap.children && mindMap.children.length > 0) {
    for (const child of mindMap.children) {
      flatten(child, 0, mindMap.text || title)
    }
  }
}

// 加载课程节点并合并内容到知识树
const loadCourseNodesAndMerge = async (courseIdParam) => {
  try {
    const data = await request({ url: `/document/course/${courseIdParam}`, method: 'get' })

    if (data && data.nodes) {
      const scriptNodes = data.nodes
        
        for (const treeNode of knowledgeTree.value) {
          const matchedNode = scriptNodes.find(sn => 
            sn.title && sn.title.trim() === treeNode.title.trim()
          )
          if (matchedNode && matchedNode.content) {
            treeNode.content = matchedNode.content
            treeNode.id = matchedNode.id
            treeNode.duration = matchedNode.duration || treeNode.duration
            treeNode.is_key_point = matchedNode.is_key_point || treeNode.is_key_point
          }
        }
        
        const nodesWithContent = knowledgeTree.value.filter(n => n.content)
        const nodesWithoutContent = knowledgeTree.value.filter(n => !n.content)
        
        if (nodesWithoutContent.length > 0 && scriptNodes.length > 0) {
          const usedIndices = new Set()
          for (const treeNode of nodesWithoutContent) {
            for (let i = 0; i < scriptNodes.length; i++) {
              if (!usedIndices.has(i) && scriptNodes[i].content) {
                treeNode.content = scriptNodes[i].content
                treeNode.id = scriptNodes[i].id
                treeNode.duration = scriptNodes[i].duration || treeNode.duration
                usedIndices.add(i)
                break
              }
            }
          }
        }
      }
  } catch (error) {
  }
}

// 选择节点
const selectNode = (index) => {
  // 保存当前节点的修改（如果有）
  if (isEditMode.value && hasChanges.value) {
    if (confirm('当前有未保存的修改，是否保存？')) {
      saveCurrentNode()
    }
  }

  currentNodeIndex.value = index
  isEditMode.value = false
  hasChanges.value = false
  editContent.value = currentContent.value

  // 重置音频状态
  stopAudio()
}

// 上一个节点
const previousNode = () => {
  if (currentNodeIndex.value > 0) {
    selectNode(currentNodeIndex.value - 1)
  }
}

// 下一个节点
const nextNode = () => {
  if (currentNodeIndex.value < knowledgeTree.value.length - 1) {
    selectNode(currentNodeIndex.value + 1)
  }
}

// 进入编辑模式
const enterEditMode = () => {
  editContent.value = currentContent.value
  isEditMode.value = true
  hasChanges.value = false
}

// 监听编辑内容变化
watch(editContent, (newVal) => {
  if (isEditMode.value && newVal !== currentContent.value) {
    hasChanges.value = true
  }
})

// 保存当前节点修改
const saveCurrentNode = () => {
  if (currentNode.value && editContent.value) {
    knowledgeTree.value[currentNodeIndex.value].content = editContent.value
    hasChanges.value = false
    isEditMode.value = false
    showToast('当前章节已保存', 'success')
  }
}

// 保存所有节点
const saveAllNodes = () => {
  if (isEditMode.value) {
    saveCurrentNode()
  }
  showToast('所有修改已保存到本地', 'success')
}

// ==================== 音频功能 ====================

// 切换音频播放
const toggleAudioPlay = () => {
  if (!audioRef.value || !audioUrl.value) return

  if (isPlaying.value) {
    audioRef.value.pause()
  } else {
    audioRef.value.play().catch(e => {
      showToast('音频播放失败', 'error')
    })
  }
  isPlaying.value = !isPlaying.value
}

// 停止播放
const stopAudio = () => {
  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.currentTime = 0
  }
  isPlaying.value = false
  currentTime.value = 0
  audioProgress.value = 0
}

// 音频时间更新
const onTimeUpdate = () => {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
    if (duration.value > 0) {
      audioProgress.value = (currentTime.value / duration.value) * 100
    }
  }
}

// 音频元数据加载完成
const onLoadedMetadata = () => {
  if (audioRef.value) {
    duration.value = audioRef.value.duration
  }
}

// 音频播放结束
const onEnded = () => {
  isPlaying.value = false
  currentTime.value = 0
  audioProgress.value = 0
}

// 进度跳转
const seekAudio = (e) => {
  if (audioRef.value && duration.value > 0) {
    const time = (e.target.value / 100) * duration.value
    audioRef.value.currentTime = time
    currentTime.value = time
    audioProgress.value = e.target.value
  }
}

// 格式化时间
const formatTime = (seconds) => {
  if (!seconds || isNaN(seconds)) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

// 生成TTS语音
const generateTTS = async () => {
  if (!currentContent.value) {
    showToast('没有可生成语音的内容', 'warning')
    return
  }

  isGeneratingTTS.value = true
  showToast('正在生成语音...', 'info')

  try {
    // 调用后端TTS API
    const formData = new FormData()
    formData.append('text', currentContent.value.substring(0, 500)) // 限制文本长度
    formData.append('output_format', 'mp3')

    const blob = await request({
      url: '/document/tts/synthesize',
      method: 'post',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
      responseType: 'blob'
    })

    if (audioUrl.value) {
      URL.revokeObjectURL(audioUrl.value)
    }
    audioUrl.value = URL.createObjectURL(blob)
    showToast('语音生成成功', 'success')
  } catch (error) {
    showToast(error.message || '语音生成失败，请重试', 'error')
  } finally {
    isGeneratingTTS.value = false
  }
}

// ==================== 发布课程功能 ====================

const togglePublishCourse = async () => {
  if (!courseId.value) return

  isPublishing.value = true
  try {
    const endpoint = isPublished.value ? 'unpublish' : 'publish'
    await request({ url: `/document/course/${courseId.value}/${endpoint}`, method: 'post' })
    isPublished.value = !isPublished.value
    showToast(isPublished.value ? '课程已发布' : '课程已取消发布', 'success')

    await loadCourseStats()
  } catch (error) {
    showToast(error.message || '操作失败', 'error')
  } finally {
    isPublishing.value = false
  }
}

// ==================== 学生统计功能 ====================

const progressLabels = computed(() => {
  const dist = courseStats.value.progressDistribution || {}
  return [
    { label: '未开始', count: dist.not_started || 0 },
    { label: '初学', count: dist.beginner || 0 },
    { label: '进阶', count: dist.intermediate || 0 },
    { label: '熟练', count: dist.advanced || 0 },
    { label: '完成', count: dist.completed || 0 },
  ]
})

const toggleStatsPanel = () => {
  showStatsDetail.value = !showStatsDetail.value
  if (showStatsDetail.value && courseId.value) {
    loadCourseStats()
  }
}

const getDistPercent = (count) => {
  const total = courseStats.value.totalStudents || 1
  return Math.round((count / total) * 100)
}

const getProgressClass = (progress) => {
  if (progress >= 80) return 'high'
  if (progress >= 50) return 'medium'
  return 'low'
}

const getLevelLabel = (level) => {
  const labels = { excellent: '优秀', high: '良好', medium: '一般', low: '需加强' }
  return labels[level] || level
}

const loadCourseStats = async () => {
  if (!courseId.value) return

  isLoadingStats.value = true
  try {
    const statsData = await request({ url: `/document/course/${courseId.value}/stats`, method: 'get' })

    if (statsData) {
      courseStats.value = {
        totalStudents: statsData.total_students,
        avgProgress: statsData.avg_progress,
        avgUnderstanding: statsData.avg_understanding,
        totalStudyHours: statsData.total_study_hours,
        progressDistribution: statsData.progress_distribution,
      }

      if (courseStats.value.totalStudents > 0) {
        await loadStudentsList()
      } else {
        studentsList.value = []
      }
    }
  } catch (error) {
  } finally {
    isLoadingStats.value = false
  }
}

const loadStudentsList = async () => {
  try {
    const data = await request({ url: `/document/course/${courseId.value}/students`, method: 'get' })

    if (data) {
      studentsList.value = data.students.map(s => ({
        enrollmentId: s.enrollment_id,
        username: s.username,
        progress: s.overall_progress,
        level: s.understanding_level,
        understandingScore: s.avg_understanding_score,
        studyMinutes: s.total_study_minutes,
      }))
    }
  } catch (error) {
  }
}
</script>

<!-- 全局样式（用于KaTeX和代码高亮） -->
<style>
/* KaTeX样式已在组件内引入 */

/* Markdown内容样式 */
.markdown-body {
  font-size: 16px;
  line-height: 1.8;
  color: #374151;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin-top: 1.5em;
  margin-bottom: 0.8em;
  font-weight: 600;
  color: #111827;
}

.markdown-body h1 { font-size: 1.8em; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.3em; }
.markdown-body h2 { font-size: 1.5em; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.25em; }
.markdown-body h3 { font-size: 1.25em; }

.markdown-body p { margin: 1em 0; }

.markdown-body code:not(pre code) {
  background: #f1f5f9;
  color: #dc2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Menlo', monospace;
  font-size: 0.9em;
}

.markdown-body pre {
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-body pre code {
  background: transparent;
  color: #e2e8f0;
  padding: 0;
}

.markdown-body blockquote {
  border-left: 4px solid #6366f1;
  background: #f8fafc;
  padding: 12px 20px;
  margin: 1em 0;
  border-radius: 0 8px 8px 0;
  color: #4b5563;
}

.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid #e5e7eb;
  padding: 10px 14px;
  text-align: left;
}

.markdown-body th {
  background: #f9fafb;
  font-weight: 600;
}

/* KaTeX公式样式 */
.katex-inline {
  display: inline;
  padding: 0 2px;
}

.katex-block {
  display: block;
  text-align: center;
  margin: 1.5em 0;
  padding: 1em;
  background: #f8fafc;
  border-radius: 8px;
  overflow-x: auto;
}

.katex-error {
  color: #dc2626;
  background: #fee2e2;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.placeholder {
  color: #9ca3af;
  text-align: center;
  padding: 40px 20px;
}
</style>

<style scoped>
.teacher-dashboard {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
  background: #f5f7fa;
  padding: 20px;
  box-sizing: border-box;
}

.course-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--navbar-height));
  gap: 16px;
  color: #6b7280;
  font-size: 16px;
}

.course-loading .spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.dashboard-header {
  margin-bottom: 20px;
}

.dashboard-header h2 {
  font-size: 18px;
  color: #333;
  font-weight: 600;
}

.dashboard-content {
  display: flex;
  gap: 20px;
  height: calc(100vh - 140px);
}

/* 左侧边栏 */
.sidebar {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex-shrink: 0;
}

.upload-section,
.tree-section {
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon {
  font-size: 16px;
}

.node-count {
  font-size: 12px;
  color: #6366f1;
  font-weight: normal;
}

.upload-area {
  border: 2px dashed #d1d5db;
  border-radius: 8px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
}

.uploaded-state {
  border: 2px solid #10b981;
  border-radius: 8px;
  padding: 20px 16px;
  text-align: center;
  background: linear-gradient(135deg, #ecfdf5, #f0fdf4);
}

.uploaded-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 16px;
  color: #059669;
  font-weight: 500;
  font-size: 14px;
}

.uploaded-icon {
  font-size: 18px;
}

.back-btn {
  width: 100%;
  padding: 10px 20px;
  border: 1px solid #6366f1;
  border-radius: 8px;
  background: #6366f1;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.back-btn:hover {
  background: #4f46e5;
  border-color: #4f46e5;
}

.upload-area:hover:not(.is-uploading) {
  border-color: #6366f1;
  background: #f9fafb;
}

.upload-area.is-uploading {
  border-color: #6366f1;
  background: linear-gradient(135deg, #eef2ff, #f5f3ff);
}

.upload-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.upload-text {
  font-size: 14px;
  color: #374151;
  margin-bottom: 4px;
  font-weight: 500;
}

.upload-hint {
  font-size: 12px;
  color: #9ca3af;
}

/* 上传动画 */
.uploading-state {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top: 3px solid #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-hint {
  font-size: 12px;
  color: #6366f1;
  margin-top: 8px;
}

/* 解析信息 */
.parse-info {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.info-item .label {
  color: #6b7280;
}

.info-item .value {
  color: #111827;
  font-weight: 600;
}

/* 知识结构树 */
.tree-container {
  max-height: calc(100vh - 380px);
  overflow-y: auto;
}

.empty-tree {
  text-align: center;
  color: #9ca3af;
  padding: 40px 20px;
  font-size: 13px;
}

.empty-tree.loading {
  animation: pulse 2s ease-in-out infinite;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tree-node {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #4b5563;
  transition: all 0.2s ease;
  position: relative;
}

.tree-node:hover {
  background: #f3f4f6;
}

.tree-node.active {
  background: linear-gradient(135deg, #eef2ff, #f5f3ff);
  color: #4f46e5;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}

.node-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.node-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-badge {
  padding: 2px 6px;
  background: #fef3c7;
  color: #92400e;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.content-badge {
  font-size: 11px;
  flex-shrink: 0;
}

/* 右侧主内容 */
.content-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  min-width: 0;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
  flex-wrap: wrap;
  gap: 12px;
}

.nav-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-btn {
  padding: 6px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.nav-btn:hover:not(:disabled) {
  background: #f3f4f6;
  border-color: #9ca3af;
}

.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nav-btn.primary {
  background: #6366f1;
  color: white;
  border-color: #6366f1;
}

.nav-btn.primary:hover:not(:disabled) {
  background: #5558e6;
}

.page-indicator {
  font-size: 14px;
  color: #6b7280;
  min-width: 50px;
  text-align: center;
  font-weight: 500;
}

.duration-info {
  font-size: 13px;
  color: #6b7280;
}

.chapter-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.chapter-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.chapter-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  flex: 1;
  margin: 0;
}

.chapter-tag {
  padding: 4px 12px;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  color: #92400e;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.content-display {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.editor-label {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}

.markdown-content {
  flex: 1;
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafbfc;
  overflow-y: auto;
  max-height: 400px;
  line-height: 1.8;
}

.content-textarea {
  flex: 1;
  min-height: 200px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  font-family: inherit;
  background: white;
}

.content-textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.mode-switch {
  display: flex;
  gap: 8px;
  padding-top: 8px;
}

.switch-btn {
  flex: 1;
  padding: 8px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.switch-btn:hover {
  background: #f3f4f6;
}

.switch-btn.active {
  background: #6366f1;
  color: white;
  border-color: #6366f1;
}

/* 音频区域 */
.audio-section {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  flex-wrap: wrap;
}

.audio-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 250px;
}

.play-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  background: #6366f1;
  color: white;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.play-btn:hover:not(:disabled) {
  background: #5558e6;
  transform: scale(1.05);
}

.play-btn.playing {
  background: #ef4444;
}

.play-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.audio-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.audio-progress {
  width: 100%;
}

.progress-slider {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  background: #e5e7eb;
}

.progress-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #6366f1;
  cursor: pointer;
}

.progress-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #6366f1;
  cursor: pointer;
  border: none;
}

.audio-time {
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

.audio-btn {
  padding: 8px 20px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.audio-btn:hover:not(:disabled) {
  background: #f3f4f6;
}

.audio-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.audio-btn.primary {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
  border-color: transparent;
}

.audio-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}

/* 底部操作按钮 */
.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
  flex-wrap: wrap;
}

.action-btn {
  padding: 10px 24px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: white;
  color: #374151;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover:not(:disabled) {
  background: #f3f4f6;
  transform: translateY(-1px);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.primary {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border-color: transparent;
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.action-btn.mapping-btn {
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: white;
  border-color: transparent;
  font-weight: 600;
  font-size: 15px;
  padding: 10px 28px;
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
}

.action-btn.mapping-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.45);
}

/* 响应式设计 */
@media (max-width: 1200px) {
  .dashboard-content {
    flex-direction: column;
    height: auto;
  }

  .sidebar {
    width: 100%;
  }

  .tree-container {
    max-height: 300px;
  }

  .main-content {
    min-height: 600px;
  }
}

/* 发布按钮样式 */
.publish-btn {
  background: linear-gradient(135deg, #10b981, #059669) !important;
  color: white !important;
  border-color: transparent !important;
}

.publish-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4) !important;
}

.unpublish-btn {
  background: linear-gradient(135deg, #f59e0b, #d97706) !important;
  color: white !important;
  border-color: transparent !important;
}

.unpublish-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4) !important;
}

/* 学生统计面板 */
.student-stats-panel {
  margin-top: 16px;
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
}

.stats-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  cursor: pointer;
  font-weight: 600;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
  user-select: none;
}

.stats-header:hover {
  background: #f1f5f9;
  border-radius: 8px 8px 0 0;
}

.stats-toggle {
  font-size: 12px;
  color: #6b7280;
}

.stats-content {
  padding-top: 12px;
}

.stats-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
  padding: 12px 8px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.stat-number {
  font-size: 24px;
  font-weight: 700;
  color: #6366f1;
}

.stat-label {
  font-size: 12px;
  color: #6b7280;
  margin-top: 4px;
}

/* 进度分布 */
.progress-distribution {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px;
  background: white;
  border-radius: 8px;
}

.dist-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.dist-label {
  width: 50px;
  color: #4b5563;
  flex-shrink: 0;
}

.dist-bar-bg {
  flex: 1;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.dist-未开始 { background: #d1d5db; }
.dist-初学 { background: #93c5fd; }
.dist-进阶 { background: #a78bfa; }
.dist-熟练 { background: #86efac; }
.dist-完成 { background: #34d399; }

.dist-count {
  width: 40px;
  text-align: right;
  color: #6b7280;
  font-weight: 500;
}

/* 学生列表 */
.students-list {
  background: white;
  border-radius: 8px;
  overflow: hidden;
}

.list-header {
  padding: 10px 14px;
  background: #f8fafc;
  font-weight: 600;
  font-size: 13px;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
}

.student-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid #f3f4f6;
  transition: background 0.2s ease;
}

.student-row:last-child {
  border-bottom: none;
}

.student-row:hover {
  background: #f9fafb;
}

.student-name {
  width: 80px;
  font-weight: 500;
  font-size: 13px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-progress-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.mini-progress-bar {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.mini-progress-fill.high { background: #10b981; }
.mini-progress-fill.medium { background: #f59e0b; }
.mini-progress-fill.low { background: #ef4444; }

.progress-text {
  width: 40px;
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

.understanding-badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.level-excellent { background: #d1fae5; color: #065f46; }
.level-high { background: #dbeafe; color: #1e40af; }
.level-medium { background: #fef3c7; color: #92400e; }
.level-low { background: #fee2e2; color: #991b1b; }

.no-students {
  text-align: center;
  padding: 20px;
  color: #9ca3af;
  font-size: 13px;
}
</style>
