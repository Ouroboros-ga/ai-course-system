<template>
  <div class="sidebar">
    <!-- 文档上传区域 -->
    <div class="upload-section">
      <div class="section-title"><span class="icon">📁</span>上传文档</div>

      <div v-if="isFileUploaded" class="uploaded-state">
        <div class="uploaded-info"><span class="uploaded-icon">✅</span><span>文档已上传并解析</span></div>
        <button class="back-btn" @click="$emit('back')">← 返回</button>
      </div>

      <template v-else>
        <div class="upload-area" :class="{ 'is-uploading': isUploading }"
          @click="$emit('upload-click')" @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false" @drop.prevent="handleDrop"
        >
          <div v-if="!isUploading" class="upload-placeholder">
            <div class="upload-icon">📄</div>
            <div class="upload-text">点击或拖拽上传文档</div>
            <div class="upload-hint">支持 PDF、DOCX、PPTX（最大50MB）</div>
          </div>
          <div v-else class="uploading-state">
            <LoadingSpinner :text="uploadProgress" />
          </div>
        </div>
        <input ref="fileInput" type="file" accept=".pdf,.docx,.pptx" style="display:none" @change="handleFileSelect" />
      </template>

      <!-- 解析信息 -->
      <div v-if="parseInfo" class="parse-info">
        <div class="info-item"><span class="label">公式数量:</span><span class="value">{{ parseInfo.formulaCount }}</span></div>
        <div class="info-item"><span class="label">表格数量:</span><span class="value">{{ parseInfo.tableCount }}</span></div>
        <div class="info-item"><span class="label">知识点:</span><span class="value">{{ parseInfo.knowledgePointCount }}</span></div>
      </div>
    </div>

    <!-- AI 生成 PPT -->
    <div class="ai-ppt-section">
      <div class="section-title"><span class="icon">✨</span>AI 生成 PPT</div>
      <button class="ai-ppt-btn" @click="$emit('show-ppt')">生成课程幻灯片</button>
    </div>

    <!-- 知识结构树 -->
    <div class="tree-section">
      <div class="section-title"><span class="icon">🌳</span>知识结构
        <span v-if="knowledgeTree.length > 0" class="node-count">({{ knowledgeTree.length }})</span>
      </div>
      <div class="tree-container">
        <div v-if="knowledgeTree.length === 0 && !isUploading" class="empty-tree">暂无知识点</div>
        <div v-else-if="isUploading" class="empty-tree loading"><LoadingSpinner text="解析中..." /></div>
        <div v-else class="tree-list">
          <div v-for="(node, index) in knowledgeTree" :key="node.id || index"
            class="tree-node" :class="{ active: selectedNodeId === node.id }"
            @click="$emit('select-node', node)">
            <span class="node-type-icon">{{ getNodeIcon(node.node_type) }}</span>
            <span class="node-title">{{ node.title || `节点 ${index + 1}` }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

defineProps({
  isCourseLoading: Boolean,
  isFileUploaded: Boolean,
  isUploading: Boolean,
  uploadProgress: String,
  parseInfo: Object,
  knowledgeTree: Array,
  selectedNodeId: [Number, String],
})

defineEmits(['upload-click', 'back', 'show-ppt', 'select-node', 'file-selected'])

const isDragging = ref(false)
const fileInput = ref(null)

function handleDragOver(e) { isDragging.value = true }
function handleDragLeave() { isDragging.value = false }

function handleDrop(e) {
  isDragging.value = false
  const files = e.dataTransfer.files
  if (files.length) emit('file-selected', files[0])
}

function handleFileSelect(e) {
  const file = e.target.files?.[0]
  if (file) emit('file-selected', file)
}

function triggerUpload() { fileInput.value?.click() }

const emit = defineEmits(['upload-click', 'back', 'show-ppt', 'select-node', 'file-selected'])

function getNodeIcon(type) {
  const icons = { chapter: '📖', section: '📑', key_point: '⭐', quiz: '❓', summary: '📝' }
  return icons[type] || '📄'
}
</script>

<style scoped>
.sidebar { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 16px; }
.upload-section, .ai-ppt-section, .tree-section { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.section-title { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 12px; display: flex; align-items: center; gap: 6px; }
.section-title .icon { font-size: 16px; }
.upload-area { border: 2px dashed #d1d5db; border-radius: 8px; padding: 24px; text-align: center; cursor: pointer; transition: all 0.2s; }
.upload-area:hover, .upload-area.is-dragging { border-color: #6366f1; background: #eef2ff; }
.upload-icon { font-size: 32px; margin-bottom: 8px; }
.upload-text { font-size: 14px; color: #374151; margin-bottom: 4px; }
.upload-hint { font-size: 12px; color: #9ca3af; }
.uploaded-state { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.uploaded-info { display: flex; align-items: center; gap: 8px; color: #059669; font-size: 14px; }
.back-btn { padding: 6px 16px; background: #f3f4f6; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.parse-info { margin-top: 12px; padding-top: 12px; border-top: 1px solid #e5e7eb; }
.info-item { display: flex; justify-content: space-between; font-size: 13px; color: #6b7280; margin-bottom: 4px; }
.ai-ppt-btn { width: 100%; padding: 10px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; }
.tree-container { max-height: 400px; overflow-y: auto; }
.empty-tree { text-align: center; color: #9ca3af; padding: 20px; font-size: 13px; }
.tree-list { display: flex; flex-direction: column; gap: 2px; }
.tree-node { padding: 8px 10px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 13px; color: #374151; transition: background 0.15s; }
.tree-node:hover { background: #f3f4f6; }
.tree-node.active { background: #eef2ff; color: #4f46e5; font-weight: 500; }
.node-count { font-size: 12px; color: #9ca3af; font-weight: normal; }
.node-type-icon { font-size: 14px; flex-shrink: 0; }
.node-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
