<template>
  <Teleport to="body">
    <div v-if="visible" class="mapping-overlay" @click="handleClose">
      <div class="mapping-modal" @click.stop>
        <div class="modal-header">
          <h3>智课PPT展示管理</h3>
          <button class="close-btn" @click="handleClose"><X :size="20" /></button>
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
                  <span class="page-range" :class="{ invalid: node.page_start > node.page_end }">
                    PPT 第 {{ Math.min(node.page_start, node.page_end) }}-{{ Math.max(node.page_start, node.page_end) }} 页
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
            <div class="panel-title">
              PPT页面内容 ({{ mappingData.total_pages }} 页)
              <span v-if="selectedNode" class="click-hint">点击页面设置映射范围</span>
            </div>
            <div class="page-list">
              <div
                v-for="page in mappingData.pages"
                :key="page.page_no"
                class="page-item"
                :class="{
                  highlighted: isPageInSelectedRange(page.page_no),
                  clickable: selectedNode,
                }"
                @click="handlePageClick(page.page_no)"
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

        <LoadingSpinner v-else text="加载映射数据中..." />

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
                :min="1"
                :max="mappingData.total_pages"
                class="page-input"
                :class="{ 'input-error': editPageEnd < editPageStart }"
              />
              <button class="save-btn" @click="handleSaveNodeMapping" :disabled="!isValidEdit">
                保存
              </button>
            </div>
            <span v-if="editPageEnd < editPageStart" class="error-hint">
              结束页不能小于起始页
            </span>
            <span v-else-if="editPageEnd > mappingData.total_pages" class="error-hint">
              超出总页数
            </span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { X } from 'lucide-vue-next'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
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
    type: [Number, String],
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

// 同步编辑值到当前选中节点
watch(selectedNode, (node) => {
  if (node) {
    editPageStart.value = node.page_start
    editPageEnd.value = node.page_end
  }
})

// 编辑值校验
const isValidEdit = computed(() => {
  const s = editPageStart.value
  const e = editPageEnd.value
  const total = mappingData.value.total_pages
  return s >= 1 && e >= s && e <= total && s <= total
})

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
  const prevSelectedId = selectedNodeId.value
  try {
    const data = await getMappingDetail(props.courseId)
    mappingData.value = data || mappingData.value
    // 恢复选中状态
    if (prevSelectedId) {
      const stillExists = mappingData.value.nodes.find(n => n.node_id === prevSelectedId)
      if (stillExists) {
        selectedNodeId.value = prevSelectedId
      }
    }
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

function handlePageClick(pageNo) {
  if (!selectedNode.value) return
  const s = editPageStart.value
  const e = editPageEnd.value
  const total = mappingData.value.total_pages

  if (pageNo < s) {
    // 点击的页码在当前范围之前，设为新的起始页
    editPageStart.value = pageNo
  } else if (pageNo > e) {
    // 点击的页码在当前范围之后，设为新的结束页
    editPageEnd.value = pageNo
  } else if (pageNo === s && pageNo === e) {
    // 只有一页且点击的就是它，取消选中（重置为1-total）
    editPageStart.value = 1
    editPageEnd.value = total
  } else if (pageNo === s) {
    // 点击的是起始页，起始页后移
    editPageStart.value = pageNo + 1
  } else if (pageNo === e) {
    // 点击的是结束页，结束页前移
    editPageEnd.value = pageNo - 1
  } else {
    // 点击范围中间的页，缩小到点击页
    editPageStart.value = pageNo
    editPageEnd.value = pageNo
  }
}

function isPageInSelectedRange(pageNo) {
  if (!selectedNode.value) return false
  const start = Math.min(editPageStart.value, editPageEnd.value)
  const end = Math.max(editPageStart.value, editPageEnd.value)
  return pageNo >= start && pageNo <= end
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
  if (!selectedNodeId.value || !isValidEdit.value) return
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
    showToast('更新失败: ' + (e.message || '未知错误'), 'error')
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
  z-index: var(--z-modal);
}

.mapping-modal {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  width: 90vw;
  max-width: 1100px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  font-family: var(--font-sans);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  color: var(--color-text);
}

.close-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: var(--color-surface-2);
}

.modal-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-2);
}

.toolbar-btn {
  padding: var(--space-1) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease);
}

.toolbar-btn:hover:not(:disabled) {
  background: var(--color-surface-2);
}

.toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.toolbar-btn.primary {
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border-color: var(--color-primary);
}

.toolbar-btn.primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.toolbar-btn.success {
  background: var(--color-success);
  color: var(--color-text-inverse);
  border-color: var(--color-success);
}

.toolbar-btn.success:hover:not(:disabled) {
  background: var(--color-success-hover);
}

.change-hint {
  color: var(--color-warning);
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
  border-right: 1px solid var(--color-border);
}

.panel-title {
  padding: 10px var(--space-4);
  font-size: 13px;
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  background: var(--color-surface-2);
  border-bottom: 1px solid var(--color-border);
}

.node-list,
.page-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.node-item {
  padding: 10px var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  margin-bottom: var(--space-1);
  border: 2px solid transparent;
  transition: all var(--duration-fast) var(--ease);
}

.node-item:hover {
  background: var(--color-surface-2);
}

.node-item.active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.node-item.manual {
  border-left: 3px solid var(--color-warning);
}

.node-item.key-point .node-title {
  font-weight: var(--font-bold);
}

.node-header {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: var(--space-1);
}

.node-index {
  font-size: 11px;
  color: var(--color-text-muted);
  min-width: var(--space-4);
}

.node-title {
  font-size: var(--text-sm);
  color: var(--color-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge {
  font-size: 11px;
  padding: 1px var(--space-1);
  border-radius: var(--radius-sm);
}

.manual-badge {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.key-badge {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.node-mapping-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.page-range {
  color: var(--color-primary);
  font-weight: var(--font-medium);
}

.page-range.invalid {
  color: var(--color-danger);
  font-weight: var(--font-semibold);
}

.confidence {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.confidence.high {
  background: var(--color-success-light);
  color: var(--color-success);
}

.confidence.medium {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.confidence.low {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.node-preview {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-item {
  padding: 10px var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-1);
  border: 2px solid transparent;
  transition: all var(--duration-fast) var(--ease);
}

.page-item.highlighted {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.page-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.page-no {
  font-size: 13px;
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
}

.mapped-mark {
  font-size: 11px;
  padding: 1px var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-info-light);
  color: var(--color-info);
}

.page-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
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
  color: var(--color-text-secondary);
  gap: var(--space-3);
}

.modal-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
}

.edit-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.edit-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.edit-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.page-input {
  width: 60px;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  text-align: center;
}

.save-btn {
  padding: var(--space-1) var(--space-4);
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-sm);
  font-size: 13px;
  cursor: pointer;
  margin-left: var(--space-2);
  transition: background var(--duration-normal) var(--ease);
}

.save-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-error {
  border-color: var(--color-danger) !important;
  background: var(--color-danger-light);
}

.error-hint {
  color: var(--color-danger);
  font-size: var(--text-xs);
  margin-left: var(--space-2);
}

.click-hint {
  font-size: 11px;
  color: var(--color-warning);
  font-weight: var(--font-normal);
  margin-left: var(--space-2);
}

.page-item.clickable {
  cursor: pointer;
}

.page-item.clickable:hover {
  background: var(--color-warning-light);
  border-color: var(--color-warning);
}

@media (max-width: 768px) {
  .mapping-modal {
    width: 95vw;
    max-height: 90vh;
  }

  .modal-body {
    flex-direction: column;
  }

  .panel:first-child {
    border-right: none;
    border-bottom: 1px solid var(--color-border);
    max-height: 40vh;
  }

  .edit-row {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
}
</style>
