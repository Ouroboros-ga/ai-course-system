<template>
  <div v-if="visible" class="jump-dialog-overlay" @click.self="handleCancel">
    <div class="jump-dialog-container" :class="{ 'urgency-high': isHighUrgency }">
      <div class="dialog-header">
        <div class="header-icon"><Search :size="28" /></div>
        <h3 class="dialog-title">{{ title }}</h3>
        <button class="close-btn" @click="handleCancel" aria-label="关闭"><X :size="18" /></button>
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
                <Circle :size="14" :class="'urgency-dot-' + getUrgencyIcon(prereq.urgencyLevel)" />
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
          <div class="suggestion-icon"><Lightbulb :size="20" /></div>
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
import { Search, Lightbulb, Circle, X } from 'lucide-vue-next'

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
  const levels = {
    high: 'high',
    medium: 'medium',
    low: 'low',
  }
  return levels[level] || 'none'
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
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: var(--shadow-xl);
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
  border: 2px solid var(--color-danger);
}

.dialog-header {
  padding: var(--space-5) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.header-icon {
  color: var(--color-primary);
  display: flex;
  align-items: center;
}

.dialog-title {
  flex: 1;
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0;
}

.close-btn {
  width: var(--space-6);
  height: var(--space-6);
  border: none;
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-all);
  color: var(--color-text-secondary);
}

.close-btn:hover {
  background: var(--color-border);
  transform: translateY(-2px);
}

.dialog-body {
  padding: var(--space-5) var(--space-5);
}

.analysis-summary {
  background: var(--color-warning-light);
  border-left: 4px solid var(--color-warning);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
  border-radius: var(--radius-md);
}

.analysis-summary p {
  margin: 0;
  color: var(--color-warning-hover);
  font-size: var(--text-base);
  line-height: 1.5;
}

.weak-prerequisites-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.prerequisite-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-4);
  transition: var(--transition-all);
}

.prerequisite-item.urgency-high {
  border-color: var(--color-danger-light);
  background: var(--color-danger-light);
}

.prerequisite-item.urgency-medium {
  border-color: var(--color-warning-light);
  background: var(--color-warning-light);
}

.prerequisite-item.urgency-low {
  border-color: var(--color-success-light);
  background: var(--color-success-light);
}

.prerequisite-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.prerequisite-icon {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.urgency-dot-high { color: var(--color-danger); }
.urgency-dot-medium { color: var(--color-warning); }
.urgency-dot-low { color: var(--color-success); }
.urgency-dot-none { color: var(--color-text-muted); }

.prerequisite-title {
  flex: 1;
  font-weight: var(--font-semibold);
  font-size: 15px;
  color: var(--color-text);
}

.confidence-badge {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-surface-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-weight: var(--font-medium);
}

.prerequisite-reason {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin-bottom: var(--space-2);
}

.prerequisite-evidence {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin-top: var(--space-2);
}

.prerequisite-evidence ul {
  margin: var(--space-1) 0 0 var(--space-4);
  padding: 0;
}

.prerequisite-evidence li {
  margin-bottom: 2px;
  font-style: italic;
}

.ai-suggestion {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-5);
  padding: var(--space-4);
  background: var(--color-info-light);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-info-light);
}

.suggestion-icon {
  color: var(--color-info);
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.ai-suggestion p {
  margin: 0;
  font-size: 13px;
  color: var(--color-info);
  line-height: 1.5;
}

.dialog-footer {
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}

.btn {
  padding: var(--space-3) var(--space-5);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: var(--transition-all);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--color-surface-2);
  color: var(--color-text-secondary);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--color-border);
}

.btn-primary {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  box-shadow: var(--shadow-primary);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary);
}

.dialog-footer-note {
  padding: var(--space-3) var(--space-5) var(--space-4);
  text-align: center;
}

.dialog-footer-note small {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
</style>
