<template>
  <div class="sidebar">
    <!-- 文档上传区域 -->
    <div class="upload-section">
      <div class="section-title"><Folder class="title-icon" :size="16" />上传文档</div>

      <div v-if="isFileUploaded" class="uploaded-state">
        <div class="uploaded-info"><CheckCircle class="uploaded-icon" :size="18" /><span>文档已上传并解析</span></div>
        <button class="back-btn" @click="$emit('back')"><ArrowLeft :size="14" /> 返回</button>
      </div>

      <template v-else>
        <div class="upload-area" :class="{ 'is-uploading': isUploading, 'is-dragging': isDragging }"
          @click="$emit('upload-click')" @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false" @drop.prevent="handleDrop"
        >
          <div v-if="!isUploading" class="upload-placeholder">
            <FileText class="upload-icon" :size="32" />
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
      <div class="section-title"><Sparkles class="title-icon" :size="16" />AI 生成 PPT</div>
      <button class="ai-ppt-btn" @click="$emit('show-ppt')">生成课程幻灯片</button>
    </div>

    <!-- 知识结构树 -->
    <div class="tree-section">
      <div class="section-title"><Network class="title-icon" :size="16" />知识结构
        <span v-if="knowledgeTree.length > 0" class="node-count">({{ knowledgeTree.length }})</span>
      </div>
      <div class="tree-container">
        <div v-if="knowledgeTree.length === 0 && !isUploading" class="empty-tree">暂无知识点</div>
        <div v-else-if="isUploading" class="empty-tree loading"><LoadingSpinner text="解析中..." /></div>
        <div v-else class="tree-list">
          <div v-for="(node, index) in knowledgeTree" :key="node.id || index"
            class="tree-node" :class="{ active: selectedNodeId === node.id }"
            @click="$emit('select-node', node)">
            <component :is="getNodeIcon(node.node_type)" class="node-type-icon" :size="14" />
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
import {
  Folder, CheckCircle, ArrowLeft, FileText, Sparkles, Network,
  BookOpen, ClipboardList, Star, HelpCircle, PenLine,
} from 'lucide-vue-next'

defineProps({
  isCourseLoading: Boolean,
  isFileUploaded: Boolean,
  isUploading: Boolean,
  uploadProgress: String,
  parseInfo: Object,
  knowledgeTree: Array,
  selectedNodeId: [Number, String],
})

const emit = defineEmits(['upload-click', 'back', 'show-ppt', 'select-node', 'file-selected'])

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

function getNodeIcon(type) {
  const icons = {
    chapter: BookOpen,
    section: ClipboardList,
    key_point: Star,
    quiz: HelpCircle,
    summary: PenLine,
  }
  return icons[type] || FileText
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.upload-section,
.ai-ppt-section,
.tree-section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-sm);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.title-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.upload-area {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-6);
  text-align: center;
  cursor: pointer;
  transition: var(--transition-color);
}

.upload-area:hover,
.upload-area.is-dragging {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.upload-icon {
  color: var(--color-primary);
  margin-bottom: var(--space-2);
}

.upload-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}

.upload-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.uploaded-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.uploaded-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-success-hover);
  font-size: var(--text-sm);
}

.uploaded-icon {
  color: var(--color-success);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: var(--transition-color);
}

.back-btn:hover {
  background: var(--color-surface-3);
  color: var(--color-text);
}

.parse-info {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.info-item {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.info-item .value {
  color: var(--color-text);
  font-weight: var(--font-semibold);
}

.ai-ppt-btn {
  width: 100%;
  padding: var(--space-3);
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  transition: var(--duration-normal) var(--ease);
}

.ai-ppt-btn:hover {
  background: var(--gradient-primary-hover);
  box-shadow: var(--shadow-primary);
}

.tree-container {
  max-height: 400px;
  overflow-y: auto;
}

.empty-tree {
  text-align: center;
  color: var(--color-text-muted);
  padding: var(--space-5);
  font-size: var(--text-sm);
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.tree-node {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: var(--transition-color);
}

.tree-node:hover {
  background: var(--color-surface-2);
}

.tree-node.active {
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
  font-weight: var(--font-medium);
}

.tree-node.active .node-type-icon {
  color: var(--color-primary);
}

.node-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: var(--font-normal);
}

.node-type-icon {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.node-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
