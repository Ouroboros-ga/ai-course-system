<template>
  <div class="knowledge-progress-page">
    <div class="page-header">
      <h1>📚 知识图谱管理</h1>
      <p class="subtitle">教师工作台 - 管理智课内容与知识点脚本</p>
    </div>

    <div class="main-content">
      <div class="sidebar">
        <div class="course-list-section">
          <h3>📁 我的课程</h3>
          <div class="course-list" v-if="courses.length > 0">
            <div 
              v-for="course in courses" 
              :key="course.id"
              class="course-item"
              :class="{ active: selectedCourseId === course.id }"
              @click="loadCourseHierarchy(course.id)"
            >
              <span class="course-icon">📖</span>
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
              <div class="upload-icon">📄</div>
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
          <h3>🌳 知识结构树</h3>
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
          <div class="empty-icon">📖</div>
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
                ◀ 上一个
              </button>
              <span class="node-counter">{{ currentNodeIndex + 1 }} / {{ totalNodes }}</span>
              <button
                class="nav-btn"
                @click="navigateNext"
                :disabled="!canNavigateNext"
                title="下一个节点 (→)"
              >
                下一个 ▶
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
                <span v-if="currentNode?.is_key_point" class="key-point-badge">⭐ 重点</span>
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
                <h4>🔊 语音播放</h4>
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
                  :src="currentAudioUrl"
                  controls
                  @ended="onAudioEnded"
                ></audio>
              </div>
            </div>
          </div>

          <div class="action-bar">
            <button class="save-btn" @click="saveChangesToDatabase" :disabled="!hasChanges || isSaving">
              {{ isSaving ? '保存中...' : '💾 保存到数据库' }}
            </button>
            <button class="save-all-btn" @click="saveAllChanges" :disabled="isSavingAll">
              {{ isSavingAll ? '保存中...' : '💾 保存全部修改' }}
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
  
  isGeneratingAudio.value = true
  
  try {
    const response = await fetch('/api/v1/document/tts/synthesize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        text: editedContent.value
      })
    })
    
    if (!response.ok) {
      throw new Error('语音生成失败')
    }
    
    const blob = await response.blob()
    currentAudioUrl.value = URL.createObjectURL(blob)
    showToast('语音生成成功', 'success')
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
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
  padding: 24px;
}

.page-header {
  text-align: center;
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 28px;
  color: #1f2937;
  margin-bottom: 8px;
}

.subtitle {
  color: #6b7280;
  font-size: 14px;
}

.main-content {
  display: flex;
  gap: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.sidebar {
  width: 320px;
  flex-shrink: 0;
}

.course-list-section {
  background: white;
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.course-list-section h3 {
  font-size: 16px;
  color: #374151;
  margin-bottom: 16px;
}

.course-list {
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 16px;
}

.course-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-bottom: 8px;
}

.course-item:hover {
  background: #f3f4f6;
}

.course-item.active {
  background: #e0e7ff;
  border: 1px solid #818cf8;
}

.course-icon {
  font-size: 24px;
}

.course-info {
  flex: 1;
}

.course-title {
  font-size: 14px;
  font-weight: 500;
  color: #1f2937;
}

.course-meta {
  font-size: 12px;
  color: #6b7280;
}

.no-courses {
  text-align: center;
  padding: 20px;
  color: #9ca3af;
}

.upload-section {
  border-top: 1px solid #e5e7eb;
  padding-top: 16px;
}

.upload-section h4 {
  font-size: 14px;
  color: #374151;
  margin-bottom: 12px;
}

.upload-area {
  border: 2px dashed #d1d5db;
  border-radius: 12px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.upload-area:hover {
  border-color: #4f46e5;
  background: #f5f3ff;
}

.upload-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.upload-area p {
  color: #6b7280;
  font-size: 13px;
  margin: 4px 0;
}

.supported-formats {
  font-size: 11px !important;
  color: #9ca3af !important;
}

.tree-section {
  background: white;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  max-height: calc(100vh - 450px);
  overflow-y: auto;
}

.tree-section h3 {
  font-size: 16px;
  color: #374151;
  margin-bottom: 16px;
}

.tree-container {
  font-size: 14px;
}

.content-area {
  flex: 1;
  min-width: 0;
}

.empty-state {
  background: white;
  border-radius: 16px;
  padding: 80px 40px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 20px;
  color: #374151;
  margin-bottom: 8px;
}

.empty-state p {
  color: #6b7280;
  font-size: 14px;
}

.node-editor {
  background: white;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  height: calc(100vh - 150px);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 16px 16px 0 0;
}

.node-path {
  font-size: 13px;
  color: #6b7280;
}

.path-separator {
  margin: 0 6px;
  color: #d1d5db;
}

.node-nav {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-btn {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.nav-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
}

.nav-btn:disabled {
  background: #e5e7eb;
  color: #9ca3af;
  cursor: not-allowed;
}

.node-counter {
  font-size: 13px;
  color: #6b7280;
  min-width: 80px;
  text-align: center;
}

.node-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.content-header h2 {
  font-size: 20px;
  color: #1f2937;
  margin: 0;
}

.node-meta {
  display: flex;
  gap: 8px;
}

.level-badge {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

.level-1 {
  background: #fef3c7;
  color: #92400e;
}

.level-2 {
  background: #dbeafe;
  color: #1e40af;
}

.level-3 {
  background: #dcfce7;
  color: #166534;
}

.level-4, .level-5 {
  background: #f3e8ff;
  color: #7c3aed;
}

.key-point-badge {
  background: #fef3c7;
  color: #d97706;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
}

.editor-section {
  margin-bottom: 24px;
}

.editor-section label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
}

.editor-section .hint {
  font-size: 12px;
  color: #9ca3af;
  font-weight: normal;
}

.content-editor {
  width: 100%;
  min-height: 200px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  transition: border-color 0.2s ease;
  box-sizing: border-box;
}

.content-editor:focus {
  outline: none;
  border-color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.audio-section {
  background: #f9fafb;
  border-radius: 12px;
  padding: 16px;
}

.audio-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.audio-header h4 {
  font-size: 14px;
  color: #374151;
  margin: 0;
}

.generate-audio-btn {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.generate-audio-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.generate-audio-btn:disabled {
  background: #e5e7eb;
  color: #9ca3af;
  cursor: not-allowed;
}

.audio-player {
  background: white;
  border-radius: 8px;
  padding: 12px;
}

.audio-player audio {
  width: 100%;
  height: 40px;
}

.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 0 0 16px 16px;
}

.save-btn, .save-all-btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.save-btn {
  background: white;
  border: 1px solid #d1d5db;
  color: #374151;
}

.save-btn:hover:not(:disabled) {
  border-color: #4f46e5;
  color: #4f46e5;
}

.save-btn:disabled {
  background: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
}

.save-all-btn {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  border: none;
  color: white;
}

.save-all-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
}

.save-all-btn:disabled {
  background: #e5e7eb;
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
