<template>
  <Teleport to="body">
    <div v-if="visible" class="mapping-overlay" @click="handleClose">
      <div class="mapping-modal" @click.stop>
        <div class="modal-header">
          <h3>知识点 ↔ PPT页面 映射编辑</h3>
          <button class="close-btn" @click="handleClose">✕</button>
        </div>

        <div class="modal-toolbar">
          <button class="toolbar-btn" @click="handleAutoMap" :disabled="loading">
            自动映射
          </button>
          <button class="toolbar-btn primary" @click="handleAiMatch" :disabled="loading">
            AI智能匹配
          </button>
          <button class="toolbar-btn success" @click="handleApply" :disabled="loading || !hasChanges">
            应用到脚本
          </button>
          <span v-if="hasChanges" class="change-hint">有未应用的更改</span>
        </div>

        <div class="modal-body" v-if="!loading || mappingData.nodes.length > 0">
          <!-- 左侧：知识点列表 -->
          <div class="panel nodes-panel">
            <div class="panel-title">知识点列表 ({{ mappingData.total_nodes }})</div>
            <div class="node-list">
              <div
                v-for="node in mappingData.nodes"
                :key="node.node_id"
                class="node-item"
                :class="{
                  active: selectedNodeId === node.node_id,
                  manual: node.is_manual,
                  'key-point': node.is_key_point,
                }"
                @click="selectNode(node)"
              >
                <div class="node-header">
                  <span class="node-index">#{{ node.node_index + 1 }}</span>
                  <span class="node-title">{{ node.title || '未命名节点' }}</span>
                  <span v-if="node.is_manual" class="badge manual-badge">手动</span>
                  <span v-if="node.is_key_point" class="badge key-badge">重点</span>
                </div>
                <div class="node-mapping-info">
                  <span class="page-range">
                    PPT 第 {{ node.page_start }}-{{ node.page_end }} 页
                  </span>
                  <span class="confidence" :class="getConfidenceClass(node.confidence)">
                    {{ (node.confidence * 100).toFixed(0) }}%
                  </span>
                </div>
                <div v-if="node.content_preview" class="node-preview">
                  {{ node.content_preview }}...
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：PPT页面内容 -->
          <div class="panel pages-panel">
            <div class="panel-title">PPT页面内容 ({{ mappingData.total_pages }} 页)</div>
            <div class="page-list">
              <div
                v-for="page in mappingData.pages"
                :key="page.page_no"
                class="page-item"
                :class="{
                  highlighted: isPageInSelectedRange(page.page_no),
                }"
              >
                <div class="page-header">
                  <span class="page-no">第 {{ page.page_no }} 页</span>
                  <span
                    v-if="isPageInSelectedRange(page.page_no)"
                    class="mapped-mark"
                  >已映射</span>
                </div>
                <div class="page-text">{{ page.text }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-else class="loading-state">
          <div class="spinner"></div>
          <span>加载映射数据中...</span>
        </div>

        <!-- 底部：选中节点的映射编辑 -->
        <div v-if="selectedNode" class="modal-footer">
          <div class="edit-row">
            <span class="edit-label">
              <strong>{{ selectedNode.title || '未命名节点' }}</strong>
              的PPT页面范围：
            </span>
            <div class="edit-inputs">
              <label>起始页</label>
              <input
                type="number"
                v-model.number="editPageStart"
                :min="1"
                :max="mappingData.total_pages"
                class="page-input"
              />
              <label>结束页</label>
              <input
                type="number"
                v-model.number="editPageEnd"
                :min="editPageStart"
                :max="mappingData.total_pages"
                class="page-input"
              />
              <button class="save-btn" @click="handleSaveNodeMapping">
                保存
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import {
  getMappingDetail,
  autoGenerateMapping,
  aiMatchMapping,
  updateNodeMapping,
  applyMapping,
} from '@/api/mapping.js'
import { showToast } from '@/utils/toast.js'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  courseId: {
    type: Number,
    default: null,
  },
})

const emit = defineEmits(['update:visible', 'applied'])

const loading = ref(false)
const hasChanges = ref(false)
const selectedNodeId = ref(null)
const editPageStart = ref(1)
const editPageEnd = ref(1)

const mappingData = ref({
  course_id: null,
  script_id: null,
  nodes: [],
  pages: [],
  total_nodes: 0,
  total_pages: 0,
})

const selectedNode = computed(() =>
  mappingData.value.nodes.find((n) => n.node_id === selectedNodeId.value) || null
)

// 弹窗打开时加载数据
watch(
  () => props.visible,
  (val) => {
    if (val && props.courseId) {
      loadMapping()
    }
  }
)

async function loadMapping() {
  loading.value = true
  try {
    const data = await getMappingDetail(props.courseId)
    mappingData.value = data || mappingData.value
  } catch (e) {
    showToast('加载映射数据失败', 'error')
  } finally {
    loading.value = false
  }
}

function selectNode(node) {
  selectedNodeId.value = node.node_id
  editPageStart.value = node.page_start
  editPageEnd.value = node.page_end
}

function isPageInSelectedRange(pageNo) {
  if (!selectedNode.value) return false
  return pageNo >= selectedNode.value.page_start && pageNo <= selectedNode.value.page_end
}

function getConfidenceClass(confidence) {
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'medium'
  return 'low'
}

async function handleAutoMap() {
  loading.value = true
  try {
    await autoGenerateMapping(props.courseId)
    showToast('自动映射生成成功', 'success')
    hasChanges.value = true
    await loadMapping()
  } catch (e) {
    showToast('自动映射失败', 'error')
  } finally {
    loading.value = false
  }
}

async function handleAiMatch() {
  loading.value = true
  try {
    await aiMatchMapping(props.courseId)
    showToast('AI匹配完成', 'success')
    hasChanges.value = true
    await loadMapping()
  } catch (e) {
    showToast('AI匹配失败', 'error')
  } finally {
    loading.value = false
  }
}

async function handleSaveNodeMapping() {
  if (!selectedNodeId.value) return
  try {
    await updateNodeMapping(
      props.courseId,
      selectedNodeId.value,
      editPageStart.value,
      editPageEnd.value
    )
    showToast('映射已更新', 'success')
    hasChanges.value = true
    await loadMapping()
  } catch (e) {
    showToast('更新失败', 'error')
  }
}

async function handleApply() {
  try {
    await applyMapping(props.courseId)
    showToast('映射已应用到脚本', 'success')
    hasChanges.value = false
    emit('applied')
  } catch (e) {
    showToast('应用失败', 'error')
  }
}

function handleClose() {
  if (hasChanges.value) {
    if (!confirm('有未应用的更改，确定关闭吗？')) return
  }
  selectedNodeId.value = null
  hasChanges.value = false
  emit('update:visible', false)
}
</script>

<style scoped>
.mapping-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.mapping-modal {
  background: white;
  border-radius: 12px;
  width: 90vw;
  max-width: 1100px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  font-family: 'Segoe UI', sans-serif;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: #1f2937;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  color: #6b7280;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}

.close-btn:hover {
  background: #f3f4f6;
}

.modal-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.toolbar-btn {
  padding: 6px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.toolbar-btn:hover:not(:disabled) {
  background: #f3f4f6;
}

.toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.toolbar-btn.primary {
  background: #4f46e5;
  color: white;
  border-color: #4f46e5;
}

.toolbar-btn.primary:hover:not(:disabled) {
  background: #4338ca;
}

.toolbar-btn.success {
  background: #059669;
  color: white;
  border-color: #059669;
}

.toolbar-btn.success:hover:not(:disabled) {
  background: #047857;
}

.change-hint {
  color: #d97706;
  font-size: 13px;
  margin-left: auto;
}

.modal-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 400px;
}

.panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel:first-child {
  border-right: 1px solid #e5e7eb;
}

.panel-title {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
}

.node-list,
.page-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.node-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 2px solid transparent;
  transition: all 0.15s;
}

.node-item:hover {
  background: #f3f4f6;
}

.node-item.active {
  border-color: #4f46e5;
  background: #eef2ff;
}

.node-item.manual {
  border-left: 3px solid #f59e0b;
}

.node-item.key-point .node-title {
  font-weight: 700;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.node-index {
  font-size: 11px;
  color: #9ca3af;
  min-width: 24px;
}

.node-title {
  font-size: 14px;
  color: #1f2937;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.manual-badge {
  background: #fef3c7;
  color: #92400e;
}

.key-badge {
  background: #fee2e2;
  color: #991b1b;
}

.node-mapping-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}

.page-range {
  color: #4f46e5;
  font-weight: 500;
}

.confidence {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 3px;
}

.confidence.high {
  background: #d1fae5;
  color: #065f46;
}

.confidence.medium {
  background: #fef3c7;
  color: #92400e;
}

.confidence.low {
  background: #fee2e2;
  color: #991b1b;
}

.node-preview {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-item {
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 6px;
  border: 2px solid transparent;
  transition: all 0.15s;
}

.page-item.highlighted {
  border-color: #4f46e5;
  background: #eef2ff;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.page-no {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.mapped-mark {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1e40af;
}

.page-text {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  max-height: 80px;
  overflow: hidden;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: #6b7280;
  gap: 12px;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #4f46e5;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.modal-footer {
  padding: 12px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f9fafb;
}

.edit-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.edit-label {
  font-size: 13px;
  color: #374151;
}

.edit-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #6b7280;
}

.page-input {
  width: 60px;
  padding: 4px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 13px;
  text-align: center;
}

.save-btn {
  padding: 4px 16px;
  background: #4f46e5;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  margin-left: 8px;
}

.save-btn:hover {
  background: #4338ca;
}
</style>
