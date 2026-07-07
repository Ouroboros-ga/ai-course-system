<template>
  <div class="knowledge-progress-page">
    <div class="page-header">
      <h1><BookOpen :size="24" /> 知识图谱管理</h1>
      <p class="subtitle">教师工作台 - 管理智课内容与知识点脚本</p>
    </div>

    <div class="main-content">
      <div class="sidebar">
        <div class="course-list-section">
          <h3><Folder :size="16" /> 我的课程</h3>
          <div class="course-list" v-if="courses.length > 0">
            <div 
              v-for="course in courses" 
              :key="course.id"
              class="course-item"
              :class="{ active: selectedCourseId === course.id }"
              @click="loadCourseHierarchy(course.id)"
            >
              <span class="course-icon"><BookOpen :size="16" /></span>
              <div class="course-info">
                <div class="course-title">{{ course.title }}</div>
                <div class="course-meta">{{ course.total_nodes || 0 }} 个知识点</div>
              </div>
            </div>
          </div>
          <div v-else class="no-courses">
            <p>暂无课程</p>
          </div>
          
          <div class="upload-section">
            <h4>上传新文档</h4>
            <div
              class="upload-area"
              @click="triggerUpload"
              @dragover.prevent
              @drop.prevent="handleDrop"
            >
              <div class="upload-icon"><FileText :size="32" /></div>
              <p>点击或拖拽上传</p>
              <p class="supported-formats">PDF, DOCX, PPTX</p>
            </div>
            <input
              type="file"
              ref="fileInput"
              @change="handleFileChange"
              accept=".pdf,.docx,.doc,.pptx,.ppt"
              style="display: none"
            />
          </div>
        </div>

        <div class="tree-section" v-if="treeData">
          <h3><Network :size="16" /> 知识结构树</h3>
          <div class="tree-container">
            <KnowledgeTreeNode
              :node="treeData"
              :selected-id="selectedNodeId"
              :expanded-ids="expandedIds"
              @select="handleNodeSelect"
              @toggle="handleToggleExpand"
            />
          </div>
        </div>
      </div>

      <div class="content-area">
        <div v-if="!treeData" class="empty-state">
          <div class="empty-icon"><BookOpen :size="48" /></div>
          <h3>请选择课程或上传文档</h3>
          <p>选择已有课程或上传新文档开始编辑</p>
        </div>

        <div v-else class="node-editor">
          <div class="node-header">
            <div class="node-path">
              <span v-for="(part, idx) in currentNodePath" :key="idx">
                {{ part }}
                <span v-if="idx < currentNodePath.length - 1" class="path-separator">/</span>
              </span>
            </div>
            <div class="node-nav">
              <button
                class="nav-btn"
                @click="navigatePrev"
                :disabled="!canNavigatePrev"
                title="上一个节点 (←)"
              >
                <ChevronLeft :size="12" /> 上一个
              </button>
              <span class="node-counter">{{ currentNodeIndex + 1 }} / {{ totalNodes }}</span>
              <button
                class="nav-btn"
                @click="navigateNext"
                :disabled="!canNavigateNext"
                title="下一个节点 (→)"
              >
                下一个 <ChevronRight :size="12" />
              </button>
            </div>
          </div>

          <div class="node-content">
            <div class="content-header">
              <h2>{{ currentNode?.title || '选择一个节点' }}</h2>
              <div class="node-meta">
                <span class="level-badge" :class="'level-' + currentNode?.level">
                  {{ getLevelLabel(currentNode?.level) }}
                </span>
                <span v-if="currentNode?.is_key_point" class="key-point-badge"><Star :size="12" /> 重点</span>
              </div>
            </div>

            <div class="editor-section">
              <label>智课文本内容 <span class="hint">(编辑后点击保存按钮更新数据库)</span></label>
              <textarea
                v-model="editedContent"
                class="content-editor"
                placeholder="在此编辑智课文本..."
                @input="markAsModified"
              ></textarea>
            </div>

            <div class="audio-section" v-if="currentNode">
              <div class="audio-header">
                <h4><Volume2 :size="14" /> 语音播放</h4>
                <button
                  class="generate-audio-btn"
                  @click="generateAudioForNode"
                  :disabled="isGeneratingAudio"
                >
                  {{ isGeneratingAudio ? '生成中...' : '生成语音' }}
                </button>
              </div>
              <div class="audio-player" v-if="currentAudioUrl">
                <audio
                  ref="audioRef"
                  :src="currentAudioUrlWithToken"
                  controls
                  @ended="onAudioEnded"
                ></audio>
              </div>
            </div>
          </div>

          <div class="action-bar">
            <button class="save-btn" @click="saveChangesToDatabase" :disabled="!hasChanges || isSaving">
              <Save :size="14" v-if="!isSaving" /> {{ isSaving ? '保存中...' : '保存到数据库' }}
            </button>
            <button class="save-all-btn" @click="saveAllChanges" :disabled="isSavingAll">
              <Save :size="14" v-if="!isSavingAll" /> {{ isSavingAll ? '保存中...' : '保存全部修改' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import KnowledgeTreeNode from './KnowledgeTreeNode.vue'
import { BookOpen, Folder, FileText, Network, Star, Volume2, Save, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import api from '@/api/index.js'
import { showToast } from '@/utils/toast'
import { useCounterStore } from '@/stores/counter.js'

const counter = useCounterStore()

const fileInput = ref(null)
const courses = ref([])
const selectedCourseId = ref(null)
const treeData = ref(null)
const selectedNodeId = ref(null)
const expandedIds = ref(new Set(['root']))
const flatNodes = ref([])
const currentNodeIndex = ref(0)
const editedContent = ref('')
const hasChanges = ref(false)
const isGeneratingAudio = ref(false)
const isSaving = ref(false)
const isSavingAll = ref(false)
const currentAudioUrl = ref('')
const audioRef = ref(null)
const modifiedNodes = ref(new Set())

onMounted(() => {
  loadCourses()
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

const loadCourses = async () => {
  try {
    const res = await api.user.getMyInfo()
    if (res && res.data && res.data.courses) {
      courses.value = res.data.courses
    }
  } catch (err) {
    courses.value = [
      { id: 1, title: '高等数学 - 微积分基础', total_nodes: 12 },
      { id: 2, title: '线性代数 - 矩阵运算', total_nodes: 8 },
      { id: 3, title: '概率论与数理统计', total_nodes: 15 },
    ]
  }
}

const loadCourseHierarchy = async (courseId) => {
  selectedCourseId.value = courseId
  try {
    showToast('正在加载课程结构...', 'info')
    const res = await api.chat.getDocumentHierarchy(courseId)
    
    if (res && res.data) {
      treeData.value = res.data.hierarchy
      flatNodes.value = res.data.flat_nodes || []
      
      if (flatNodes.value.length > 0) {
        selectNode(flatNodes.value[0].node_id)
      }
      showToast('课程结构加载成功', 'success')
    }
  } catch (err) {
    showToast('加载失败，请重试', 'error')
  }
}

const triggerUpload = () => {
  fileInput.value?.click()
}

const handleFileChange = async (e) => {
  const file = e.target.files[0]
  if (file) {
    await uploadFile(file)
  }
}

const handleDrop = async (e) => {
  const file = e.dataTransfer.files[0]
  if (file) {
    await uploadFile(file)
  }
}

const uploadFile = async (file) => {
  try {
    showToast('正在上传并解析文档...', 'info')
    
    const formData = new FormData()
    formData.append('file', file)
    formData.append('fileName', file.name)
    formData.append('userId', counter.userData.id)

    const res = await api.chat.uploadFile(formData)
    
    if (res) {
      selectedCourseId.value = res.courseId
      processUploadResult(res)
      showToast('文档解析成功！', 'success')
      loadCourses()
    }
  } catch (err) {
    showToast(err.message || '上传失败', 'error')
  }
}

const processUploadResult = (result) => {
  if (result.mindMapJson) {
    treeData.value = result.mindMapJson
    flatNodes.value = []
    flattenTree(result.mindMapJson)
    if (flatNodes.value.length > 0) {
      selectNode(flatNodes.value[0].node_id)
    }
  }
}

const flattenTree = (node, parentPath = '', parentLevel = 0) => {
  if (!node) return
  
  const path = parentPath ? `${parentPath}/${node.text || node.title}` : (node.text || node.title)
  const nodeId = node.node_id || node.id || `node_${flatNodes.value.length}`
  const nodeLevel = node.level || (parentLevel + 1)
  
  const hasContent = node.content && node.content.trim().length > 10
  const hasChildren = node.children && node.children.length > 0
  
  if (hasContent || (!hasChildren && nodeLevel >= 2)) {
    flatNodes.value.push({
      node_id: nodeId,
      title: node.text || node.title || '未命名',
      level: nodeLevel,
      path: path,
      content: node.content || '',
      is_key_point: node.highlight || false,
      duration: node.duration || 0,
      node_type: node.node_type || 'lecture',
      audio_url: node.audio_url || '',
      audio_duration: node.audio_duration || 0,
      children: []
    })
  }
  
  if (node.children && node.children.length > 0) {
    node.children.forEach(child => {
      flattenTree(child, path, nodeLevel)
    })
  }
}

const handleNodeSelect = (nodeId) => {
  selectNode(nodeId)
}

const selectNode = (nodeId) => {
  if (hasChanges.value) {
    if (!confirm('当前有未保存的修改，是否放弃？')) return
  }
  
  selectedNodeId.value = nodeId
  const index = flatNodes.value.findIndex(n => n.node_id === nodeId)
  if (index !== -1) {
    currentNodeIndex.value = index
    const node = flatNodes.value[index]
    editedContent.value = node.content || ''
    hasChanges.value = false

    if (currentAudioUrl.value && currentAudioUrl.value.startsWith('blob:')) {
      URL.revokeObjectURL(currentAudioUrl.value)
    }
    if (node.audio_url) {
      currentAudioUrl.value = node.audio_url
    } else {
      currentAudioUrl.value = ''
    }
  }
}

const handleToggleExpand = (nodeId) => {
  if (expandedIds.value.has(nodeId)) {
    expandedIds.value.delete(nodeId)
  } else {
    expandedIds.value.add(nodeId)
  }
  expandedIds.value = new Set(expandedIds.value)
}

const currentNode = computed(() => {
  return flatNodes.value[currentNodeIndex.value] || null
})

const currentNodePath = computed(() => {
  if (!currentNode.value) return []
  return currentNode.value.path.split('/').filter(p => p)
})

const currentAudioUrlWithToken = computed(() => {
  if (!currentAudioUrl.value) return ''
  if (currentAudioUrl.value.startsWith('blob:')) return currentAudioUrl.value
  const token = localStorage.getItem('token')
  const separator = currentAudioUrl.value.includes('?') ? '&' : '?'
  return token ? `${currentAudioUrl.value}${separator}token=${token}` : currentAudioUrl.value
})

const totalNodes = computed(() => flatNodes.value.length)

const canNavigatePrev = computed(() => currentNodeIndex.value > 0)

const canNavigateNext = computed(() => currentNodeIndex.value < flatNodes.value.length - 1)

const navigatePrev = () => {
  if (canNavigatePrev.value) {
    if (hasChanges.value) {
      if (!confirm('当前有未保存的修改，是否继续？')) return
    }
    currentNodeIndex.value--
    selectNode(flatNodes.value[currentNodeIndex.value].node_id)
  }
}

const navigateNext = () => {
  if (canNavigateNext.value) {
    if (hasChanges.value) {
      if (!confirm('当前有未保存的修改，是否继续？')) return
    }
    currentNodeIndex.value++
    selectNode(flatNodes.value[currentNodeIndex.value].node_id)
  }
}

const getLevelLabel = (level) => {
  const labels = {
    1: '章节',
    2: '小节',
    3: '知识点',
    4: '细节',
    5: '要点'
  }
  return labels[level] || `L${level}`
}

const markAsModified = () => {
  hasChanges.value = true
  if (currentNode.value) {
    modifiedNodes.value.add(currentNode.value.node_id)
  }
}

const saveChangesToDatabase = async () => {
  if (!currentNode.value || !hasChanges.value || !selectedCourseId.value) return
  
  isSaving.value = true
  
  try {
    await api.chat.updateNodeContent(
      selectedCourseId.value,
      currentNode.value.node_id,
      editedContent.value
    )
    
    const nodeIndex = flatNodes.value.findIndex(n => n.node_id === currentNode.value.node_id)
    if (nodeIndex !== -1) {
      flatNodes.value[nodeIndex].content = editedContent.value
    }
    
    modifiedNodes.value.delete(currentNode.value.node_id)
    hasChanges.value = false
    showToast('已保存到数据库', 'success')
  } catch (err) {
    showToast('保存失败: ' + (err.message || '未知错误'), 'error')
  } finally {
    isSaving.value = false
  }
}

const saveAllChanges = async () => {
  if (!selectedCourseId.value || modifiedNodes.value.size === 0) {
    showToast('没有需要保存的修改', 'info')
    return
  }
  
  isSavingAll.value = true
  let successCount = 0
  let failCount = 0
  
  for (const nodeId of modifiedNodes.value) {
    const node = flatNodes.value.find(n => n.node_id === nodeId)
    if (node && node.content) {
      try {
        await api.chat.updateNodeContent(
          selectedCourseId.value,
          nodeId,
          node.content
        )
        successCount++
      } catch (err) {
        failCount++
      }
    }
  }
  
  modifiedNodes.value.clear()
  hasChanges.value = false
  isSavingAll.value = false
  
  if (failCount === 0) {
    showToast(`全部保存成功 (${successCount} 个节点)`, 'success')
  } else {
    showToast(`保存完成：成功 ${successCount} 个，失败 ${failCount} 个`, 'warning')
  }
}

const generateAudioForNode = async () => {
  if (!editedContent.value || !editedContent.value.trim()) {
    showToast('请先输入文本内容', 'warning')
    return
  }

  const node = flatNodes.value[currentNodeIndex.value]
  if (!node || !selectedCourseId.value) {
    showToast('请先选择课程和节点', 'warning')
    return
  }

  const nodeId = node.node_id
  if (!nodeId || typeof nodeId === 'string' && nodeId.startsWith('node_')) {
    showToast('该节点尚未同步到数据库，请先保存内容', 'warning')
    return
  }

  isGeneratingAudio.value = true

  try {
    const response = await fetch(
      `/api/v1/document/course/${selectedCourseId.value}/node/${nodeId}/synthesize-audio`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
        },
      }
    )

    const result = await response.json()

    if (result.code === 200 && result.data && result.data.audio_url) {
      if (currentAudioUrl.value && currentAudioUrl.value.startsWith('blob:')) {
        URL.revokeObjectURL(currentAudioUrl.value)
      }
      currentAudioUrl.value = result.data.audio_url
      node.audio_url = result.data.audio_url
      node.audio_duration = result.data.audio_duration || 0
      showToast('语音生成成功', 'success')
    } else {
      throw new Error(result.message || '语音生成失败')
    }
  } catch (err) {
    showToast('语音生成失败: ' + err.message, 'error')
  } finally {
    isGeneratingAudio.value = false
  }
}

const onAudioEnded = () => {
  if (canNavigateNext.value) {
    setTimeout(() => {
      navigateNext()
    }, 1000)
  }
}

const handleKeydown = (e) => {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') {
    return
  }
  
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    navigatePrev()
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    navigateNext()
  }
}
</script>

<style scoped>
.knowledge-progress-page {
  min-height: calc(100vh - var(--navbar-height));
  background: var(--color-bg);
  padding: var(--space-5);
}

.page-header {
  text-align: center;
  margin-bottom: var(--space-6);
}

.page-header h1 {
  font-size: var(--text-2xl);
  color: var(--color-text);
  margin-bottom: var(--space-2);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.subtitle {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.main-content {
  display: flex;
  gap: var(--space-5);
  max-width: 1400px;
  margin: 0 auto;
}

.sidebar {
  width: 320px;
  flex-shrink: 0;
}

.course-list-section {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
  box-shadow: var(--shadow-sm);
}

.course-list-section h3 {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.course-list {
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: var(--space-4);
}

.course-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
  margin-bottom: var(--space-2);
}

.course-item:hover {
  background: var(--color-surface-2);
}

.course-item.active {
  background: var(--color-primary-light);
  border: 1px solid var(--color-primary);
}

.course-icon {
  display: flex;
  align-items: center;
  color: var(--color-primary);
}

.course-info {
  flex: 1;
}

.course-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text);
}

.course-meta {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.no-courses {
  text-align: center;
  padding: var(--space-4);
  color: var(--color-text-muted);
}

.upload-section {
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-4);
}

.upload-section h4 {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
}

.upload-area {
  border: 2px dashed var(--color-border-hover);
  border-radius: var(--radius-lg);
  padding: var(--space-5) var(--space-4);
  text-align: center;
  cursor: pointer;
  transition: all var(--duration-slow) var(--ease);
}

.upload-area:hover {
  border-color: var(--color-primary-hover);
  background: var(--color-primary-light);
}

.upload-icon {
  margin-bottom: var(--space-2);
  display: flex;
  justify-content: center;
  align-items: center;
  color: var(--color-text-muted);
}

.upload-area p {
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  margin: var(--space-1) 0;
}

.supported-formats {
  font-size: var(--text-xs) !important;
  color: var(--color-text-muted) !important;
}

.tree-section {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  box-shadow: var(--shadow-sm);
  max-height: calc(100vh - 450px);
  overflow-y: auto;
}

.tree-section h3 {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.tree-container {
  font-size: var(--text-sm);
}

.content-area {
  flex: 1;
  min-width: 0;
}

.empty-state {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: 80px var(--space-7);
  text-align: center;
  box-shadow: var(--shadow-sm);
}

.empty-icon {
  margin-bottom: var(--space-4);
  display: flex;
  justify-content: center;
  align-items: center;
  color: var(--color-text-muted);
}

.empty-state h3 {
  font-size: var(--text-xl);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.empty-state p {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.node-editor {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  height: calc(100vh - 150px);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-2);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
}

.node-path {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.path-separator {
  margin: 0 var(--space-1);
  color: var(--color-border-hover);
}

.node-nav {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.nav-btn {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.nav-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.nav-btn:disabled {
  background: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.node-counter {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  min-width: 80px;
  text-align: center;
}

.node-content {
  flex: 1;
  padding: var(--space-5);
  overflow-y: auto;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.content-header h2 {
  font-size: var(--text-xl);
  color: var(--color-text);
  margin: 0;
}

.node-meta {
  display: flex;
  gap: var(--space-2);
}

.level-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
}

.level-1 {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.level-2 {
  background: var(--color-info-light);
  color: var(--color-info);
}

.level-3 {
  background: var(--color-success-light);
  color: var(--color-success);
}

.level-4, .level-5 {
  background: var(--color-primary-light);
  color: var(--color-secondary);
}

.key-point-badge {
  background: var(--color-warning-light);
  color: var(--color-warning);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.editor-section {
  margin-bottom: var(--space-5);
}

.editor-section label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.editor-section .hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: normal;
}

.content-editor {
  width: 100%;
  min-height: 200px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
  line-height: 1.6;
  resize: vertical;
  transition: border-color var(--duration-normal) var(--ease);
  box-sizing: border-box;
}

.content-editor:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--shadow-primary);
}

.audio-section {
  background: var(--color-surface-2);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}

.audio-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

.audio-header h4 {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.generate-audio-btn {
  background: var(--gradient-success);
  color: var(--color-text-inverse);
  border: none;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
}

.generate-audio-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.generate-audio-btn:disabled {
  background: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.audio-player {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.audio-player audio {
  width: 100%;
  height: 40px;
}

.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
  border-radius: 0 0 var(--radius-xl) var(--radius-xl);
}

.save-btn, .save-all-btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.save-btn {
  background: var(--color-surface);
  border: 1px solid var(--color-border-hover);
  color: var(--color-text-secondary);
}

.save-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.save-btn:disabled {
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.save-all-btn {
  background: var(--gradient-primary);
  border: none;
  color: var(--color-text-inverse);
}

.save-all-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.save-all-btn:disabled {
  background: var(--color-border);
  cursor: not-allowed;
}

@media (max-width: 1024px) {
  .main-content {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
  }

  .tree-section {
    max-height: 300px;
  }

  .node-editor {
    height: auto;
    min-height: 500px;
  }
}
</style>
