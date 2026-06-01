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

        <!-- AI生成PPT -->
        <div class="ai-ppt-section">
          <div class="section-title">
            <span class="icon">✨</span>
            AI生成PPT课件
          </div>
          <button class="ai-ppt-btn" @click="showPPTGeneration = true">
            输入主题，AI自动生成课件
          </button>
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

          <!-- 音频预览区 -->
          <div class="audio-section">
            <div class="audio-controls">
              <button
                class="audio-btn play-btn"
                :class="{ playing: isPlaying }"
                @click="toggleAudioPlay"
                :disabled="!audioUrl"
              >
                {{ isPlaying ? '⏸' : '▶️' }}
              </button>
              <div class="audio-info">
                <div class="audio-progress">
                  <input
                    type="range"
                    min="0"
                    max="100"
                    :value="audioProgress"
                    @input="seekAudio"
                    class="progress-slider"
                  />
                </div>
                <div class="audio-time">
                  {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
                </div>
              </div>
            </div>
            <audio
              ref="audioRef"
              :src="audioUrlWithToken"
              @timeupdate="onTimeUpdate"
              @loadedmetadata="onLoadedMetadata"
              @ended="onEnded"
              style="display: none;"
            ></audio>
            <button class="audio-btn primary" @click="generateTTS" :disabled="isGeneratingTTS || isTTSGenerating || !currentContent">
              {{ isGeneratingTTS ? '生成中...': isTTSGenerating ? `语音生成中 $ {ttsProgress.completed}/${ttsProgress.total}` : '🔊 预览语音' }}
            </button>
            <div v-if="isTTSGenerating" class="tts-progress-hint">
              后台正在批量生成语音 ({{ ttsProgress.completed }}/{{ ttsProgress.total }})
            </div>
          </div>
        </div>

        <!-- 素材与音色选择 -->
        <div v-if="currentNode" class="asset-selector-section">
          <div class="section-label">素材与音色设置</div>
          <div class="asset-selector-grid">
            <div class="asset-selector-item">
              <label>人脸视频</label>
              <select v-model="nodeAssetFaceVideo" class="asset-select">
                <option value="">使用默认</option>
                <option v-for="a in faceVideoOptions" :key="a.id" :value="a.id">
                  {{ a.file_name }}{{ a.is_default ? ' (默认)' : '' }}
                </option>
              </select>
            </div>
            <div class="asset-selector-item">
              <label>参考音频</label>
              <select v-model="nodeAssetRefAudio" class="asset-select">
                <option value="">使用默认</option>
                <option v-for="a in refAudioOptions" :key="a.id" :value="a.id">
                  {{ a.file_name }}{{ a.is_default ? ' (默认)' : '' }}
                </option>
              </select>
            </div>
            <div class="asset-selector-item">
              <label>语音音色</label>
              <select v-model="nodeVoice" class="asset-select">
                <option value="">使用默认</option>
                <optgroup label="克隆音色（我的声音）">
                  <option v-for="a in clonedVoiceOptions" :key="a.clone_voice_id" :value="a.clone_voice_id">
                    {{ a.file_name }}（克隆）
                  </option>
                </optgroup>
                <optgroup label="预置音色">
                  <option value="zh_female_shuangkuaisisi_moon_bigtts">女声-爽快思思</option>
                  <option value="zh_male_chunhou_zhiboshuangkuai">男声-醇厚主播</option>
                </optgroup>
              </select>
            </div>
          </div>
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
            class="action-btn version-btn"
            @click="showVersionPanel = !showVersionPanel"
          >
            📋 版本管理
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

        <!-- 版本管理面板 -->
        <div v-if="showVersionPanel && courseId" class="version-panel">
          <div class="version-header">
            <span>📋 脚本版本管理</span>
            <button class="version-close" @click="showVersionPanel = false">✕</button>
          </div>
          <div class="version-actions">
            <input
              v-model="newVersionName"
              type="text"
              class="version-input"
              placeholder="版本名称（可选）"
            />
            <button class="action-btn primary" @click="handleCreateSnapshot" :disabled="isCreatingSnapshot">
              {{ isCreatingSnapshot ? '创建中...' : '📸 创建快照' }}
            </button>
          </div>
          <div v-if="versionList.length === 0" class="version-empty">暂无版本记录</div>
          <div v-else class="version-list">
            <div
              v-for="v in versionList"
              :key="v.id"
              class="version-item"
              :class="{ active: v.is_active }"
            >
              <div class="version-info">
                <span class="version-tag">v{{ v.version }}</span>
                <span class="version-name">{{ v.version_name || '未命名' }}</span>
                <span v-if="v.is_active" class="version-badge">当前</span>
              </div>
              <div class="version-meta">
                {{ v.node_count }}个节点 · {{ formatVersionTime(v.created_at) }}
              </div>
              <button
                v-if="!v.is_active"
                class="action-btn rollback-btn"
                @click="handleRollback(v.id, v.version)"
              >
                回滚
              </button>
            </div>
          </div>
        </div>

        <!-- 学生统计面板（已禁用） -->
<!--        <div v-if="courseId && showStudentStats" class="student-stats-panel">-->
<!--          <div class="stats-header" @click="toggleStatsPanel">-->
<!--            <span>👥 学生学习情况</span>-->
<!--            <span class="stats-toggle">{{ showStatsDetail ? '▼' : '▶' }}</span>-->
<!--          </div>-->

<!--          <div v-if="showStatsDetail" class="stats-content">-->
<!--            &lt;!&ndash; 统计概览 &ndash;&gt;-->
<!--            <div class="stats-overview">-->
<!--              <div class="stat-card">-->
<!--                <div class="stat-number">{{ courseStats.totalStudents || 0 }}</div>-->
<!--                <div class="stat-label">选课人数</div>-->
<!--              </div>-->
<!--              <div class="stat-card">-->
<!--                <div class="stat-number">{{ courseStats.avgProgress || 0 }}%</div>-->
<!--                <div class="stat-label">平均进度</div>-->
<!--              </div>-->
<!--              <div class="stat-card">-->
<!--                <div class="stat-number">{{ courseStats.avgUnderstanding || 0 }}%</div>-->
<!--                <div class="stat-label">平均理解度</div>-->
<!--              </div>-->
<!--              <div class="stat-card">-->
<!--                <div class="stat-number">{{ courseStats.totalStudyHours || 0 }}h</div>-->
<!--                <div class="stat-label">总学习时长</div>-->
<!--              </div>-->
<!--            </div>-->

<!--            &lt;!&ndash; 进度分布条 &ndash;&gt;-->
<!--            <div v-if="courseStats.progressDistribution" class="progress-distribution">-->
<!--              <div class="dist-item" v-for="(count, label) in progressLabels" :key="label">-->
<!--                <span class="dist-label">{{ label }}</span>-->
<!--                <div class="dist-bar-bg">-->
<!--                  <div-->
<!--                    class="dist-bar-fill"-->
<!--                    :style="{ width: getDistPercent(count) + '%' }"-->
<!--                    :class="'dist-' + label"-->
<!--                  ></div>-->
<!--                </div>-->
<!--                <span class="dist-count">{{ count }}人</span>-->
<!--              </div>-->
<!--            </div>-->

<!--            &lt;!&ndash; 学生列表 &ndash;&gt;-->
<!--            <div v-if="studentsList.length > 0" class="students-list">-->
<!--              <div class="list-header">学生详情</div>-->
<!--              <div-->
<!--                v-for="student in studentsList"-->
<!--                :key="student.enrollmentId"-->
<!--                class="student-row"-->
<!--              >-->
<!--                <div class="student-name">{{ student.username }}</div>-->
<!--                <div class="student-progress-wrap">-->
<!--                  <div class="mini-progress-bar">-->
<!--                    <div-->
<!--                      class="mini-progress-fill"-->
<!--                      :style="{ width: student.progress + '%' }"-->
<!--                      :class="getProgressClass(student.progress)"-->
<!--                    ></div>-->
<!--                  </div>-->
<!--                  <span class="progress-text">{{ student.progress }}%</span>-->
<!--                </div>-->
<!--                <span-->
<!--                  class="understanding-badge"-->
<!--                  :class="'level-' + student.level"-->
<!--                >{{ getLevelLabel(student.level) }}</span>-->
<!--              </div>-->
<!--            </div>-->
<!--            <div v-else-if="!isLoadingStats && courseStats.totalStudents === 0" class="no-students">-->
<!--              暂无学生选择此课程（请先发布课程）-->
<!--            </div>-->
<!--          </div>-->
<!--        </div>-->
      </div>
    </div>

    <MappingEditor
      v-model:visible="showMappingEditor"
      :courseId="courseId"
      @applied="showToast('映射已应用，视频生成将使用新映射', 'success')"
    />
    <PPTGenerationDialog
      v-model:visible="showPPTGeneration"
      :courseId="courseId"
      @generated="handlePPTGenerated"
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
import MappingEditor from '@/components/profile/LoginIn/courses/MappingEditor.vue'
import PPTGenerationDialog from '@/components/profile/LoginIn/courses/PPTGenerationDialog.vue'
import { getAssetList } from '@/api/asset.js'
import { createScriptSnapshot, getScriptVersions, rollbackScriptVersion, saveCourseNodes } from '@/api/script_editor.js'

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
      courseId.value = Number(id)
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
          page_start: node.page_start || 1,
          page_end: node.page_end || 1,
          extra_data: node.extra_data || {},
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
  loadTeacherAssets()
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
  avgStudyHoursPerStudent: 0,
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

// AI生成PPT
const showPPTGeneration = ref(false)

// 素材选择器
const faceVideoOptions = ref([])
const refAudioOptions = ref([])
const clonedVoiceOptions = computed(() =>
  refAudioOptions.value.filter(a => a.clone_status === 'success' && a.clone_voice_id)
)
const nodeAssetFaceVideo = ref('')
const nodeAssetRefAudio = ref('')
const nodeVoice = ref('')

// 版本管理
const showVersionPanel = ref(false)
const versionList = ref([])
const newVersionName = ref('')
const isCreatingSnapshot = ref(false)

// PPT生成完成后的回调
const handlePPTGenerated = (data) => {
  if (data?.course_id) {
    courseId.value = data.course_id
    showToast('PPT课件已生成，正在加载课程数据...', 'success')
    // 重新加载课程数据
    setTimeout(() => {
      window.location.href = `/teacher?courseId=${data.course_id}`
    }, 1000)
  }
}

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

const audioUrlWithToken = computed(() => {
  if (!audioUrl.value) return ''
  if (audioUrl.value.startsWith('blob:')) return audioUrl.value
  const token = localStorage.getItem('token')
  const separator = audioUrl.value.includes('?') ? '&' : '?'
  return token ? `${audioUrl.value}${separator}token=${token}` : audioUrl.value
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

      if (courseId.value) {
        loadCourseStats()
      }

      if (res.ttsStatus === 'processing' && courseId.value) {
        pollTTSStatus(courseId.value)
      }
    }
  } catch (error) {
    showToast(error.message || '文档处理失败，请重试', 'error')
  } finally {
    isUploading.value = false
    uploadProgress.value = '准备上传...'
  }
}

const isTTSGenerating = ref(false)
const ttsProgress = ref({ status: 'idle', total: 0, completed: 0 })

const pollTTSStatus = async (cId) => {
  isTTSGenerating.value = true
  ttsProgress.value = { status: 'processing', total: 0, completed: 0 }
  showToast('TTS语音正在后台生成中...', 'info')

  const maxAttempts = 120
  let attempt = 0

  const poll = async () => {
    try {
      const data = await request({
        url: `/document/course/${cId}/tts-status`,
        method: 'get',
      })

      if (data) {
        ttsProgress.value = {
          status: data.status,
          total: data.total || 0,
          completed: data.completed || 0,
        }

        if (data.status === 'completed') {
          isTTSGenerating.value = false
          showToast(`TTS语音生成完成: ${data.completed}/${data.total} 个节点`, 'success')
          await loadCourseNodesAndMerge(cId)
          if (currentNode.value && currentNode.value.audio_url) {
            audioUrl.value = currentNode.value.audio_url
          }
          return
        }

        if (data.status === 'failed') {
          isTTSGenerating.value = false
          const errorCount = (data.errors || []).length
          showToast(`TTS语音生成部分失败: ${data.completed}/${data.total} 成功, ${errorCount} 失败`, 'warning')
          await loadCourseNodesAndMerge(cId)
          if (currentNode.value && currentNode.value.audio_url) {
            audioUrl.value = currentNode.value.audio_url
          }
          return
        }
      }

      attempt++
      if (attempt < maxAttempts) {
        setTimeout(poll, 3000)
      } else {
        isTTSGenerating.value = false
        showToast('TTS语音生成超时，请稍后刷新页面查看', 'warning')
      }
    } catch (err) {
      attempt++
      if (attempt < maxAttempts) {
        setTimeout(poll, 5000)
      } else {
        isTTSGenerating.value = false
        showToast('TTS状态查询失败', 'error')
      }
    }
  }

  setTimeout(poll, 2000)
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
            treeNode.audio_url = matchedNode.audio_url || ''
            treeNode.audio_duration = matchedNode.audio_duration || 0
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
  if (isEditMode.value && hasChanges.value) {
    if (confirm('当前有未保存的修改，是否保存？')) {
      saveCurrentNode()
    }
  }

  currentNodeIndex.value = index
  isEditMode.value = false
  hasChanges.value = false
  editContent.value = currentContent.value

  stopAudio()
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
  }
  const node = knowledgeTree.value[index]
  if (node && node.audio_url) {
    audioUrl.value = node.audio_url
  } else {
    audioUrl.value = ''
  }
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
const saveCurrentNode = async () => {
  if (currentNode.value && editContent.value) {
    knowledgeTree.value[currentNodeIndex.value].content = editContent.value
    // 更新素材选择到extra_data
    const extraData = currentNode.value.extra_data || {}
    if (nodeAssetFaceVideo.value) extraData.face_video_asset_id = nodeAssetFaceVideo.value
    else delete extraData.face_video_asset_id
    if (nodeAssetRefAudio.value) extraData.ref_audio_asset_id = nodeAssetRefAudio.value
    else delete extraData.ref_audio_asset_id
    if (nodeVoice.value) extraData.voice = nodeVoice.value
    else delete extraData.voice
    knowledgeTree.value[currentNodeIndex.value].extra_data = extraData
    hasChanges.value = false
    isEditMode.value = false
    // 持久化到后端
    if (courseId.value && currentNode.value.id) {
      try {
        await saveCourseNodes(courseId.value, [{
          id: currentNode.value.id,
          content: editContent.value,
          extra_data: extraData,
        }])
        showToast('当前章节已保存', 'success')
      } catch (e) {
        showToast('保存到服务器失败', 'error')
      }
    } else {
      showToast('当前章节已保存', 'success')
    }
  }
}

// 保存所有节点
const saveAllNodes = async () => {
  if (isEditMode.value) {
    saveCurrentNode()
    return
  }
  // 批量保存所有节点到后端
  if (courseId.value) {
    try {
      const nodes = knowledgeTree.value.map(n => ({
        id: n.id,
        title: n.title,
        content: n.content,
        page_start: n.page_start,
        page_end: n.page_end,
        extra_data: n.extra_data,
      }))
      await saveCourseNodes(courseId.value, nodes)
      showToast('所有修改已保存', 'success')
    } catch (e) {
      showToast('保存到服务器失败', 'error')
    }
  } else {
    showToast('所有修改已保存到本地', 'success')
  }
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

  const node = currentNode.value
  if (!node || !node.id || !courseId.value) {
    showToast('请先上传文档并选择节点', 'warning')
    return
  }

  isGeneratingTTS.value = true
  showToast('正在生成语音...', 'info')

  try {
    const res = await request({
      url: `/document/course/${courseId.value}/node/${node.id}/synthesize-audio`,
      method: 'post',
    })

    if (res && res.audio_url) {
      if (audioUrl.value && audioUrl.value.startsWith('blob:')) {
        URL.revokeObjectURL(audioUrl.value)
      }
      audioUrl.value = res.audio_url
      node.audio_url = res.audio_url
      node.audio_duration = res.audio_duration || 0
      showToast('语音生成成功', 'success')
    } else {
      showToast('语音生成失败', 'error')
    }
  } catch (error) {
    let errorMsg = '语音生成失败，请重试'
    if (error.response) {
      const status = error.response.status
      if (status === 503) {
        errorMsg = '语音合成服务认证失败，TTS凭证可能已过期，请联系管理员更新配置'
      } else if (status === 504) {
        errorMsg = '语音合成服务响应超时，请稍后重试'
      } else if (status === 500) {
        errorMsg = '语音合成服务内部错误，请稍后重试'
      }
    } else if (error.message) {
      if (error.message.includes('503') || error.message.includes('认证')) {
        errorMsg = '语音合成服务认证失败，TTS凭证可能已过期，请联系管理员更新配置'
      }
    }
    showToast(errorMsg, 'error')
  } finally {
    isGeneratingTTS.value = false
  }
}

// ==================== 素材与版本管理功能 ====================

// 加载老师素材列表
const loadTeacherAssets = async () => {
  try {
    const res = await getAssetList()
    const assets = res.data?.data || res.data || []
    faceVideoOptions.value = assets.filter(a => a.asset_type === 'face_video')
    refAudioOptions.value = assets.filter(a => a.asset_type === 'ref_audio')
  } catch (e) {
    // 静默失败，素材选择器显示空列表
  }
}

// 监听当前节点变化，同步素材选择
watch(currentNode, (node) => {
  if (node?.extra_data) {
    nodeAssetFaceVideo.value = node.extra_data.face_video_asset_id || ''
    nodeAssetRefAudio.value = node.extra_data.ref_audio_asset_id || ''
    nodeVoice.value = node.extra_data.voice || ''
  } else {
    nodeAssetFaceVideo.value = ''
    nodeAssetRefAudio.value = ''
    nodeVoice.value = ''
  }
})

// 加载版本列表
const loadVersionList = async () => {
  if (!courseId.value) return
  try {
    const res = await getScriptVersions(courseId.value)
    versionList.value = res.data?.data || res.data || []
  } catch (e) {
    versionList.value = []
  }
}

// 监听版本面板显示
watch(showVersionPanel, (val) => {
  if (val) loadVersionList()
})

// 创建版本快照
const handleCreateSnapshot = async () => {
  if (!courseId.value) return
  isCreatingSnapshot.value = true
  try {
    // 先保存当前修改
    if (hasChanges.value) {
      await saveAllNodes()
    }
    await createScriptSnapshot(courseId.value, newVersionName.value || undefined)
    newVersionName.value = ''
    showToast('版本快照已创建', 'success')
    await loadVersionList()
  } catch (e) {
    showToast('创建快照失败', 'error')
  } finally {
    isCreatingSnapshot.value = false
  }
}

// 回滚到指定版本
const handleRollback = async (scriptId, version) => {
  if (!confirm(`确定要回滚到 v${version} 吗？当前未保存的修改将丢失。`)) return
  try {
    await rollbackScriptVersion(courseId.value, scriptId)
    showToast(`已回滚到 v${version}，正在重新加载...`, 'success')
    // 重新加载课程数据
    setTimeout(() => {
      window.location.href = `/teacher?courseId=${courseId.value}`
    }, 1000)
  } catch (e) {
    showToast('回滚失败', 'error')
  }
}

// 格式化版本时间
const formatVersionTime = (isoStr) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`
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
        avgStudyHoursPerStudent: statsData.avg_study_hours_per_student,
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
.tree-section,
.ai-ppt-section {
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.ai-ppt-btn {
  width: 100%;
  padding: 12px;
  border: 2px dashed #6366f1;
  border-radius: 8px;
  background: linear-gradient(135deg, #f0f0ff, #e8e8ff);
  color: #6366f1;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
}

.ai-ppt-btn:hover {
  background: linear-gradient(135deg, #e8e8ff, #d8d8ff);
  border-color: #4f46e5;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
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

.tts-progress-hint {
  font-size: 12px;
  color: #6366f1;
  margin-top: 4px;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 素材与音色选择 */
.asset-selector-section {
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
}

.asset-selector-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.asset-selector-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.asset-selector-item label {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
}

.asset-select {
  padding: 6px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  color: #374151;
  background: white;
  cursor: pointer;
  outline: none;
}

.asset-select:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* 版本管理面板 */
.version-panel {
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  margin-top: 12px;
}

.version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
  font-size: 14px;
}

.version-close {
  background: none;
  border: none;
  font-size: 16px;
  cursor: pointer;
  color: #9ca3af;
  padding: 4px;
}

.version-close:hover {
  color: #374151;
}

.version-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.version-input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}

.version-input:focus {
  border-color: #6366f1;
}

.version-empty {
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
  padding: 16px;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.version-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  transition: all 0.2s;
}

.version-item.active {
  border-color: #6366f1;
  background: #f0f0ff;
}

.version-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.version-tag {
  background: #6366f1;
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.version-name {
  font-size: 13px;
  color: #374151;
}

.version-badge {
  background: #10b981;
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.version-meta {
  font-size: 12px;
  color: #9ca3af;
}

.rollback-btn {
  padding: 4px 12px !important;
  font-size: 12px !important;
  background: #f59e0b !important;
  color: white !important;
  border-color: transparent !important;
}

.rollback-btn:hover {
  background: #d97706 !important;
}

.version-btn {
  background: #8b5cf6 !important;
  color: white !important;
  border-color: transparent !important;
}

.version-btn:hover {
  background: #7c3aed !important;
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
