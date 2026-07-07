<template>
  <div class="teacher-dashboard">
    <LoadingSpinner v-if="isCourseLoading" text="正在加载课程数据..." full-page />
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
            <Folder class="icon" :size="16" />
            上传文档
          </div>
          <div v-if="isFileUploaded" class="uploaded-state">
            <div class="uploaded-info">
              <CheckCircle class="uploaded-icon" :size="18" />
              <span>文档已上传并解析</span>
            </div>
            <button class="back-btn" @click="router.back()"><ArrowLeft :size="14" /> 返回</button>
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
                <FileText class="upload-icon" :size="48" />
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
            <Sparkles class="icon" :size="16" />
            AI生成PPT课件
          </div>
          <button class="ai-ppt-btn" @click="showPPTGeneration = true">
            输入主题，AI自动生成课件与视频
          </button>
        </div>

        <!-- 知识结构树 -->
        <div class="tree-section">
          <div class="section-title">
            <Network class="icon" :size="16" />
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
                <component :is="getNodeIcon(node.node_type)" class="node-icon" :size="14" />
                <span class="node-text">{{ node.title || `章节 ${index + 1}` }}</span>
                <span v-if="node.is_key_point" class="key-badge">重点</span>
                <PenLine v-if="node.has_content" class="content-badge" :size="12" />
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
              <ChevronLeft :size="14" /> 上一个
            </button>
            <span class="page-indicator">
              {{ currentNodeIndex + 1 }} / {{ knowledgeTree.length || 1 }}
            </span>
            <button
              class="nav-btn primary"
              :disabled="currentNodeIndex >= knowledgeTree.length - 1"
              @click="nextNode"
            >
              下一个 <ChevronRight :size="14" />
            </button>
          </div>
          <div v-if="currentNode" class="duration-info">
            <Clock :size="14" /> 预计时长: {{ currentNode.duration || 0 }}分钟
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
                <Eye :size="14" /> 预览模式
              </button>
              <button
                class="switch-btn"
                :class="{ active: isEditMode }"
                @click="enterEditMode"
              >
                <Pencil :size="14" /> 编辑模式
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
                <component :is="isPlaying ? Pause : Play" :size="18" />
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
              {{ isGeneratingTTS ? '生成中...': isTTSGenerating ? `语音生成中 ${ttsProgress.completed}/${ttsProgress.total}` : '预览语音' }}
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
            <Save :size="14" /> 保存当前修改
          </button>
          <button class="action-btn primary" @click="saveAllNodes">
            <Lock :size="14" /> 保存全部修改
          </button>
          <button
            v-if="courseId"
            class="action-btn version-btn"
            @click="showVersionPanel = !showVersionPanel"
          >
            <ClipboardList :size="14" /> 版本管理
          </button>
          <button
            v-if="courseId"
            class="action-btn"
            :class="{ 'publish-btn': !isPublished, 'unpublish-btn': isPublished }"
            @click="togglePublishCourse"
            :disabled="isPublishing"
          >
            {{ isPublishing ? '处理中...' : (isPublished ? '已发布' : '发布课程') }}
          </button>
        </div>

        <!-- 版本管理面板 -->
        <div v-if="showVersionPanel && courseId" class="version-panel">
          <div class="version-header">
            <span><ClipboardList :size="16" /> 脚本版本管理</span>
            <button class="version-close" @click="showVersionPanel = false"><X :size="16" /></button>
          </div>
          <div class="version-actions">
            <input
              v-model="newVersionName"
              type="text"
              class="version-input"
              placeholder="版本名称（可选）"
            />
            <button class="action-btn primary" @click="handleCreateSnapshot" :disabled="isCreatingSnapshot">
              {{ isCreatingSnapshot ? '创建中...' : '创建快照' }}
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
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
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
import {
  Folder, CheckCircle, ArrowLeft, FileText, Sparkles, Network,
  BookOpen, ClipboardList, PenLine, Tag, Star, Lightbulb, Ruler,
  Clock, Eye, Pencil, Pause, Play, Volume2, Save, Lock, Camera,
  Megaphone, Rocket, ChevronLeft, ChevronRight, X, HelpCircle,
} from 'lucide-vue-next'

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
    'chapter': BookOpen,
    'section': ClipboardList,
    'subsection': FileText,
    'paragraph': PenLine,
    'title': Tag,
    'key_point': Star,
    'example': Lightbulb,
    'formula': Ruler,
    'summary': ClipboardList,
    'lecture': BookOpen,
    'question': HelpCircle,
  }
  return iconMap[nodeType] || BookOpen
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
  font-size: var(--text-base);
  line-height: var(--leading-loose);
  color: var(--color-text-secondary);
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin-top: 1.5em;
  margin-bottom: 0.8em;
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.markdown-body h1 { font-size: 1.8em; border-bottom: 2px solid var(--color-border); padding-bottom: 0.3em; }
.markdown-body h2 { font-size: 1.5em; border-bottom: 1px solid var(--color-border); padding-bottom: 0.25em; }
.markdown-body h3 { font-size: 1.25em; }

.markdown-body p { margin: 1em 0; }

.markdown-body code:not(pre code) {
  background: var(--color-surface-2);
  color: var(--color-danger-hover);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.markdown-body pre {
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-body pre code {
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0;
}

.markdown-body blockquote {
  border-left: 4px solid var(--color-primary);
  background: var(--color-bg);
  padding: var(--space-3) var(--space-5);
  margin: 1em 0;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  color: var(--color-text-secondary);
}

.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--color-border);
  padding: 10px 14px;
  text-align: left;
}

.markdown-body th {
  background: var(--color-surface-2);
  font-weight: var(--font-semibold);
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
  background: var(--color-bg);
  border-radius: var(--radius-md);
  overflow-x: auto;
}

.katex-error {
  color: var(--color-danger-hover);
  background: var(--color-danger-light);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}

.placeholder {
  color: var(--color-text-muted);
  text-align: center;
  padding: var(--space-8) var(--space-5);
}
</style>

<style scoped>
.teacher-dashboard {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
  background: var(--color-bg);
  padding: var(--space-5);
  box-sizing: border-box;
}

.dashboard-header {
  margin-bottom: var(--space-5);
}

.dashboard-header h2 {
  font-size: var(--text-lg);
  color: var(--color-text);
  font-weight: var(--font-semibold);
}

.dashboard-content {
  display: flex;
  gap: var(--space-5);
  height: calc(100vh - 140px);
}

/* 左侧边栏 */
.sidebar {
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  flex-shrink: 0;
}

.upload-section,
.tree-section,
.ai-ppt-section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-sm);
}

.ai-ppt-btn {
  width: 100%;
  padding: var(--space-3);
  border: 2px dashed var(--color-primary);
  border-radius: var(--radius-md);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--duration-slow) var(--ease);
}

.ai-ppt-btn:hover {
  background: var(--color-secondary-light);
  border-color: var(--color-primary-hover);
  box-shadow: var(--shadow-primary);
}

.section-title {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.node-count {
  font-size: var(--text-xs);
  color: var(--color-primary);
  font-weight: var(--font-normal);
}

.upload-area {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-6) var(--space-4);
  text-align: center;
  cursor: pointer;
  transition: var(--duration-slow) var(--ease);
  position: relative;
}

.uploaded-state {
  border: 2px solid var(--color-success);
  border-radius: var(--radius-md);
  padding: var(--space-5) var(--space-4);
  text-align: center;
  background: var(--color-success-light);
}

.uploaded-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  color: var(--color-success-hover);
  font-weight: var(--font-medium);
  font-size: var(--text-sm);
}

.uploaded-icon {
  color: var(--color-success);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3) var(--space-5);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--color-primary-foreground);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--duration-normal) var(--ease);
}

.back-btn:hover {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}

.upload-area:hover:not(.is-uploading) {
  border-color: var(--color-primary);
  background: var(--color-surface-2);
}

.upload-area.is-uploading {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.upload-icon {
  color: var(--color-primary);
  margin-bottom: var(--space-3);
}

.upload-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
  font-weight: var(--font-medium);
}

.upload-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
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
  border: 3px solid var(--color-border);
  border-top: 3px solid var(--color-primary);
  border-radius: var(--radius-full);
  animation: spin 1s linear infinite;
  margin: 0 auto var(--space-3);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-hint {
  font-size: var(--text-xs);
  color: var(--color-primary);
  margin-top: var(--space-2);
}

/* 解析信息 */
.parse-info {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.info-item {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-sm);
}

.info-item .label {
  color: var(--color-text-secondary);
}

.info-item .value {
  color: var(--color-text);
  font-weight: var(--font-semibold);
}

/* 知识结构树 */
.tree-container {
  max-height: calc(100vh - 380px);
  overflow-y: auto;
}

.empty-tree {
  text-align: center;
  color: var(--color-text-muted);
  padding: var(--space-10) var(--space-5);
  font-size: var(--text-sm);
}

.empty-tree.loading {
  animation: pulse 2s ease-in-out infinite;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.tree-node {
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: var(--transition-color);
  position: relative;
}

.tree-node:hover {
  background: var(--color-surface-2);
}

.tree-node.active {
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
  font-weight: var(--font-medium);
  box-shadow: var(--shadow-primary);
}

.tree-node.active .node-icon {
  color: var(--color-primary);
}

.node-icon {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.node-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-badge {
  padding: var(--space-1) var(--space-2);
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  flex-shrink: 0;
}

.content-badge {
  color: var(--color-primary);
  flex-shrink: 0;
}

/* 右侧主内容 */
.content-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
  min-width: 0;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
  gap: var(--space-3);
}

.nav-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.nav-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: var(--transition-color);
}

.nav-btn:hover:not(:disabled) {
  background: var(--color-surface-2);
  border-color: var(--color-border-hover);
}

.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nav-btn.primary {
  background: var(--color-primary);
  color: var(--color-primary-foreground);
  border-color: var(--color-primary);
}

.nav-btn.primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.page-indicator {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  min-width: 50px;
  text-align: center;
  font-weight: var(--font-medium);
}

.duration-info {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.chapter-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
}

.chapter-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.chapter-header h3 {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  flex: 1;
  margin: 0;
}

.chapter-tag {
  padding: var(--space-1) var(--space-3);
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.content-display {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
}

.editor-label {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
}

.markdown-content {
  flex: 1;
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  overflow-y: auto;
  max-height: 400px;
  line-height: var(--leading-loose);
}

.content-textarea {
  flex: 1;
  min-height: 200px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  resize: vertical;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text);
}

.content-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.mode-switch {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-2);
}

.switch-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  flex: 1;
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: var(--transition-color);
}

.switch-btn:hover {
  background: var(--color-surface-2);
}

.switch-btn.active {
  background: var(--color-primary);
  color: var(--color-primary-foreground);
  border-color: var(--color-primary);
}

/* 音频区域 */
.audio-section {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  flex-wrap: wrap;
}

.audio-controls {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 250px;
}

.play-btn {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary);
  color: var(--color-primary-foreground);
  border: none;
  cursor: pointer;
  transition: var(--duration-normal) var(--ease);
  flex-shrink: 0;
}

.play-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
  transform: translateY(-2px);
}

.play-btn.playing {
  background: var(--color-danger);
}

.play-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.audio-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.audio-progress {
  width: 100%;
}

.progress-slider {
  width: 100%;
  height: 6px;
  border-radius: var(--radius-sm);
  outline: none;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  background: var(--color-border);
}

.progress-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  cursor: pointer;
}

.progress-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  cursor: pointer;
  border: none;
}

.audio-time {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  text-align: right;
}

.audio-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: var(--transition-color);
  white-space: nowrap;
}

.audio-btn:hover:not(:disabled) {
  background: var(--color-surface-2);
}

.audio-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.audio-btn.primary {
  background: var(--gradient-success);
  color: var(--color-primary-foreground);
  border-color: transparent;
}

.audio-btn.primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-success);
}

.tts-progress-hint {
  font-size: var(--text-xs);
  color: var(--color-primary);
  margin-top: var(--space-1);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 素材与音色选择 */
.asset-selector-section {
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.section-label {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
}

.asset-selector-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}

.asset-selector-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.asset-selector-item label {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
}

.asset-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  cursor: pointer;
  outline: none;
}

.asset-select:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* 版本管理面板 */
.version-panel {
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  margin-top: var(--space-3);
}

.version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
  font-weight: var(--font-semibold);
  font-size: var(--text-sm);
  color: var(--color-text);
}

.version-header span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.version-close {
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: var(--space-1);
  transition: var(--transition-color);
}

.version-close:hover {
  color: var(--color-text-secondary);
}

.version-actions {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.version-input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  outline: none;
  background: var(--color-surface);
  color: var(--color-text);
}

.version-input:focus {
  border-color: var(--color-primary);
}

.version-empty {
  text-align: center;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  padding: var(--space-4);
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.version-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  transition: var(--transition-color);
}

.version-item.active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.version-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
}

.version-tag {
  background: var(--color-primary);
  color: var(--color-primary-foreground);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.version-name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.version-badge {
  background: var(--color-success);
  color: var(--color-primary-foreground);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}

.version-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.rollback-btn {
  padding: var(--space-1) var(--space-3) !important;
  font-size: var(--text-xs) !important;
  background: var(--color-warning) !important;
  color: var(--color-primary-foreground) !important;
  border-color: transparent !important;
}

.rollback-btn:hover {
  background: var(--color-warning-hover) !important;
}

.version-btn {
  background: var(--color-secondary) !important;
  color: var(--color-primary-foreground) !important;
  border-color: transparent !important;
}

.version-btn:hover {
  background: var(--color-secondary-hover) !important;
}

/* 底部操作按钮 */
.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
  flex-wrap: wrap;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--duration-normal) var(--ease);
}

.action-btn:hover:not(:disabled) {
  background: var(--color-surface-2);
  transform: translateY(-2px);
  color: var(--color-text);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.primary {
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  border-color: transparent;
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.action-btn.mapping-btn {
  background: linear-gradient(135deg, var(--color-warning), var(--color-danger));
  color: var(--color-primary-foreground);
  border-color: transparent;
  font-weight: var(--font-semibold);
  font-size: var(--text-base);
  padding: var(--space-3) var(--space-7);
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
}

.action-btn.mapping-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.45);
}

/* 响应式设计 */
@media (max-width: 1024px) {
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

@media (max-width: 1024px) {
  .asset-selector-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dashboard-content {
    height: auto;
  }
}

@media (max-width: 768px) {
  .teacher-dashboard {
    padding: var(--space-3);
  }

  .dashboard-header h2 {
    font-size: var(--text-base);
  }

  .content-main {
    padding: var(--space-3);
  }

  .asset-selector-grid {
    grid-template-columns: 1fr;
  }

  .action-bar {
    flex-direction: column;
  }

  .action-btn {
    width: 100%;
  }

  .audio-section {
    flex-direction: column;
    align-items: stretch;
  }

  .audio-controls {
    min-width: 0;
  }

  .version-actions {
    flex-direction: column;
  }
}

/* 发布按钮样式 */
.publish-btn {
  background: var(--gradient-success) !important;
  color: var(--color-primary-foreground) !important;
  border-color: transparent !important;
}

.publish-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-success) !important;
}

.unpublish-btn {
  background: var(--gradient-warning) !important;
  color: var(--color-primary-foreground) !important;
  border-color: transparent !important;
}

.unpublish-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4) !important;
}

/* 学生统计面板 */
.student-stats-panel {
  margin-top: var(--space-4);
  padding: var(--space-4);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.stats-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3);
  cursor: pointer;
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  user-select: none;
}

.stats-header:hover {
  background: var(--color-surface-2);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}

.stats-toggle {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.stats-content {
  padding-top: var(--space-3);
}

.stats-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.stat-card {
  text-align: center;
  padding: var(--space-3) var(--space-2);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}

.stat-number {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--color-primary);
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin-top: var(--space-1);
}

/* 进度分布 */
.progress-distribution {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.dist-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.dist-label {
  width: 50px;
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.dist-bar-bg {
  flex: 1;
  height: 8px;
  background: var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: var(--radius-sm);
  transition: width var(--duration-slow) var(--ease);
}

.dist-未开始 { background: var(--color-border-hover); }
.dist-初学 { background: var(--color-info-light); }
.dist-进阶 { background: var(--color-secondary); }
.dist-熟练 { background: var(--color-success-light); }
.dist-完成 { background: var(--color-success); }

.dist-count {
  width: 40px;
  text-align: right;
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
}

/* 学生列表 */
.students-list {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.list-header {
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg);
  font-weight: var(--font-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}

.student-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-surface-2);
  transition: var(--transition-color);
}

.student-row:last-child {
  border-bottom: none;
}

.student-row:hover {
  background: var(--color-surface-2);
}

.student-name {
  width: 80px;
  font-weight: var(--font-medium);
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-progress-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.mini-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: var(--radius-sm);
  transition: width var(--duration-normal) var(--ease);
}

.mini-progress-fill.high { background: var(--color-success); }
.mini-progress-fill.medium { background: var(--color-warning); }
.mini-progress-fill.low { background: var(--color-danger); }

.progress-text {
  width: 40px;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  text-align: right;
}

.understanding-badge {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  flex-shrink: 0;
}

.level-excellent { background: var(--color-success-light); color: var(--color-success-hover); }
.level-high { background: var(--color-info-light); color: var(--color-info); }
.level-medium { background: var(--color-warning-light); color: var(--color-warning-hover); }
.level-low { background: var(--color-danger-light); color: var(--color-danger-hover); }

.no-students {
  text-align: center;
  padding: var(--space-5);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}
</style>
