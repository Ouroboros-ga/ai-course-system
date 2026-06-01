<template>
  <div v-if="visible" class="jump-dialog-overlay" @click.self="handleCancel">
    <div class="jump-dialog-container" :class="{ 'urgency-high': isHighUrgency }">
      <div class="dialog-header">
        <div class="header-icon">🔍</div>
        <h3 class="dialog-title">{{ title }}</h3>
        <button class="close-btn" @click="handleCancel" aria-label="关闭">×</button>
      </div>

      <div class="dialog-body">
        <div class="analysis-summary" v-if="analysisData?.analysisSummary">
          <p>{{ analysisData.analysisSummary }}</p>
        </div>

        <div class="weak-prerequisites-list">
          <div 
            v-for="(prereq, index) in weakPrerequisites" 
            :key="index"
            class="prerequisite-item"
            :class="'urgency-' + prereq.urgencyLevel"
          >
            <div class="prerequisite-header">
              <span class="prerequisite-icon">
                {{ getUrgencyIcon(prereq.urgencyLevel) }}
              </span>
              <span class="prerequisite-title">{{ prereq.title }}</span>
              <span class="confidence-badge">
                置信度: {{ (prereq.confidence * 100).toFixed(0) }}%
              </span>
            </div>

            <div class="prerequisite-reason">
              <strong>原因：</strong>{{ prereq.reason }}
            </div>

            <div class="prerequisite-evidence" v-if="prereq.evidenceFromQuestion?.length > 0">
              <strong>依据：</strong>
              <ul>
                <li v-for="(evidence, i) in prereq.evidenceFromQuestion.slice(0, 3)" :key="i">
                  "{{ evidence }}"
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div class="ai-suggestion" v-if="suggestedAction === 'jump_to_review'">
          <div class="suggestion-icon">💡</div>
          <p>建议先复习上述前置知识，有助于更好地理解当前内容</p>
        </div>
      </div>

      <div class="dialog-footer">
        <button 
          class="btn btn-secondary" 
          @click="handleCancel"
          :disabled="isLoading"
        >
          继续学习当前内容
        </button>
        
        <button 
          class="btn btn-primary" 
          @click="handleConfirm"
          :disabled="isLoading || !hasValidPrerequisites"
        >
          <span v-if="isLoading" class="loading-spinner"></span>
          {{ isLoading ? '正在跳转...' : `跳转复习 (${weakPrerequisites.length}个知识点)` }}
        </button>
      </div>

      <div class="dialog-footer-note" v-if="!isHighUrgency">
        <small>提示：您也可以稍后手动前往相关知识点复习</small>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  analysisData: {
    type: Object,
    default: () => null,
  },
  isLoading: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['confirm', 'cancel'])

const title = computed(() => {
  if (!props.analysisData) return '学习建议'
  
  const count = props.weakPrerequisites?.length || 0
  if (count === 0) return '继续学习'
  
  if (props.isHighUrgency) {
    return `检测到 ${count} 个关键前置知识薄弱点`
  }
  
  return `发现 ${count} 个可优化的前置知识点`
})

const weakPrerequisites = computed(() => {
  return props.analysisData?.weakPrerequisites || []
})

const suggestedAction = computed(() => {
  return props.analysisData?.suggestedAction || 'continue'
})

const hasValidPrerequisites = computed(() => {
  return weakPrerequisites.value.length > 0
})

const isHighUrgency = computed(() => {
  return weakPrerequisites.value.some(p => p.urgencyLevel === 'high')
})

function getUrgencyIcon(level) {
  const icons = {
    high: '🔴',
    medium: '🟡',
    low: '🟢',
  }
  return icons[level] || '⚪'
}

function handleConfirm() {
  if (weakPrerequisites.value.length === 0) return
  
  const firstPrereq = weakPrerequisites.value[0]
  emit('confirm', {
    prerequisiteId: firstPrereq.prerequisite_id || firstPrereq.id,
    title: firstPrereq.title,
    reason: firstPrereq.reason || firstPrereq.description || '',
    confidence: firstPrereq.confidence || 0.8,
    urgencyLevel: firstPrereq.urgency_level || firstPrereq.urgencyLevel || 'medium',
    targetNodeIndex: firstPrereq.target_node_index || firstPrereq.targetNodeIndex || 0,
    analysisData: props.analysisData,
  })
}

function handleCancel() {
  emit('cancel')
}
</script>

<style scoped>
.jump-dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.jump-dialog-container {
  background: white;
  border-radius: 16px;
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  animation: slideUp 0.3s ease-out;
}

@keyframes slideUp {
  from {
    transform: translateY(30px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.jump-dialog-container.urgency-high {
  border: 2px solid #ef4444;
}

.dialog-header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  font-size: 28px;
}

.dialog-title {
  flex: 1;
  font-size: 20px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: #f3f4f6;
  border-radius: 8px;
  font-size: 24px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #e5e7eb;
  transform: scale(1.05);
}

.dialog-body {
  padding: 20px 24px;
}

.analysis-summary {
  background: #fef3c7;
  border-left: 4px solid #f59e0b;
  padding: 12px 16px;
  margin-bottom: 20px;
  border-radius: 8px;
}

.analysis-summary p {
  margin: 0;
  color: #92400e;
  font-size: 14px;
  line-height: 1.5;
}

.weak-prerequisites-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.prerequisite-item {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 16px;
  transition: all 0.2s;
}

.prerequisite-item.urgency-high {
  border-color: #fecaca;
  background: #fff1f2;
}

.prerequisite-item.urgency-medium {
  border-color: #fed7aa;
  background: #fffbeb;
}

.prerequisite-item.urgency-low {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.prerequisite-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.prerequisite-icon {
  font-size: 18px;
}

.prerequisite-title {
  flex: 1;
  font-weight: 600;
  font-size: 15px;
  color: #111827;
}

.confidence-badge {
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 500;
}

.prerequisite-reason {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.5;
  margin-bottom: 6px;
}

.prerequisite-evidence {
  font-size: 12px;
  color: #6b7280;
  margin-top: 8px;
}

.prerequisite-evidence ul {
  margin: 4px 0 0 16px;
  padding: 0;
}

.prerequisite-evidence li {
  margin-bottom: 2px;
  font-style: italic;
}

.ai-suggestion {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 20px;
  padding: 14px;
  background: #eff6ff;
  border-radius: 10px;
  border: 1px solid #bfdbfe;
}

.suggestion-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.ai-suggestion p {
  margin: 0;
  font-size: 13px;
  color: #1e40af;
  line-height: 1.5;
}

.dialog-footer {
  padding: 16px 24px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn {
  padding: 11px 24px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: #f3f4f6;
  color: #374151;
}

.btn-secondary:hover:not(:disabled) {
  background: #e5e7eb;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.45);
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.dialog-footer-note {
  padding: 10px 24px 16px;
  text-align: center;
}

.dialog-footer-note small {
  color: #9ca3af;
  font-size: 12px;
}
</style>