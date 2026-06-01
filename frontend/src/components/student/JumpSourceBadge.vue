<template>
  <div v-if="visible" class="jump-source-badge" :class="badgeClass">
    <div class="badge-content">
      <div class="badge-icon">🔖</div>
      
      <div class="badge-info">
        <div class="badge-title">{{ title }}</div>
        <div class="badge-detail" v-if="fromNodeTitle">
          从「{{ fromNodeTitle }}」跳转而来
          <span class="depth-indicator" v-if="depth > 1">
            (第 {{ depth }} 层嵌套)
          </span>
        </div>
      </div>

      <div class="badge-actions">
        <button 
          class="return-btn"
          @click="handleReturn"
          :disabled="isReturning"
          title="返回原位置继续学习"
        >
          <span v-if="!isReturning" class="btn-text">← 返回</span>
          <span v-else class="loading-dots">返回中...</span>
        </button>

        <button 
          class="dismiss-btn"
          @click="handleDismiss"
          title="关闭提示"
        >
          ×
        </button>
      </div>
    </div>

    <div class="progress-bar" v-if="showProgress && reviewStartTime">
      <div 
        class="progress-fill"
        :style="{ width: progressPercent + '%' }"
      ></div>
      <span class="progress-text">{{ elapsedText }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  fromNodeTitle: {
    type: String,
    default: '',
  },
  fromNodeIndex: {
    type: Number,
    default: 0,
  },
  jumpId: {
    type: Number,
    default: null,
  },
  depth: {
    type: Number,
    default: 1,
  },
  urgencyLevel: {
    type: String,
    default: 'medium',
  },
  showProgress: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['return', 'dismiss'])

const isReturning = ref(false)
const reviewStartTime = ref(null)
const elapsedSeconds = ref(0)
let timerInterval = null

const title = computed(() => {
  if (props.depth > 1) return `复习中（嵌套跳转）`
  
  switch (props.urgencyLevel) {
    case 'high':
      return '⚠️ 关键知识点复习'
    case 'medium':
      return '📚 前置知识复习'
    default:
      return '📖 知识点回顾'
  }
})

const badgeClass = computed(() => `urgency-${props.urgencyLevel}`)

const progressPercent = computed(() => {
  const maxTime = 600
  return Math.min((elapsedSeconds.value / maxTime) * 100, 100)
})

const elapsedText = computed(() => {
  const mins = Math.floor(elapsedSeconds.value / 60)
  const secs = elapsedSeconds.value % 60
  return `${mins}分${secs.toString().padStart(2, '0')}秒`
})

onMounted(() => {
  if (props.visible) {
    reviewStartTime.value = Date.now()
    startTimer()
  }
})

onUnmounted(() => {
  stopTimer()
})

function startTimer() {
  stopTimer()
  timerInterval = setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - reviewStartTime.value) / 1000)
  }, 1000)
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
}

async function handleReturn() {
  isReturning.value = true
  
  try {
    const duration = elapsedSeconds.value
    
    emit('return', {
      jumpId: props.jumpId,
      reviewDurationSeconds: duration,
      fromNodeIndex: props.fromNodeIndex,
    })
    
    stopTimer()
    
  } catch (error) {
    console.error('[返回操作失败]', error)
    isReturning.value = false
  }
}

function handleDismiss() {
  emit('dismiss')
}
</script>

<style scoped>
.jump-source-badge {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 998;
  animation: slideDownBadge 0.3s ease-out;
  max-width: 90vw;
  width: 500px;
}

@keyframes slideDownBadge {
  from {
    transform: translateX(-50%) translateY(-20px);
    opacity: 0;
  }
  to {
    transform: translateX(-50%) translateY(0);
    opacity: 1;
  }
}

.badge-content {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  border: 2px solid transparent;
}

.jump-source-badge.urgency-high .badge-content {
  border-color: #fecaca;
  background: linear-gradient(135deg, #fff1f2 0%, white 100%);
}

.jump-source-badge.urgency-medium .badge-content {
  border-color: #fed7aa;
  background: linear-gradient(135deg, #fffbeb 0%, white 100%);
}

.jump-source-badge.urgency-low .badge-content {
  border-color: #bbf7d0;
  background: linear-gradient(135deg, #f0fdf4 0%, white 100%);
}

.badge-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.badge-info {
  flex: 1;
  min-width: 0;
}

.badge-title {
  font-weight: 700;
  font-size: 14px;
  color: #111827;
  margin-bottom: 2px;
}

.badge-detail {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.4;
}

.depth-indicator {
  color: #dc2626;
  font-weight: 600;
  margin-left: 4px;
}

.badge-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.return-btn {
  padding: 8px 18px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.return-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
}

.return-btn:disabled {
  opacity: 0.7;
  cursor: wait;
}

.btn-text {
  white-space: nowrap;
}

.loading-dots::after {
  content: '';
  animation: dots 1.5s infinite;
}

@keyframes dots {
  0%, 20% { content: '.'; }
  40% { content: '..'; }
  60%, 100% { content: '...'; }
}

.dismiss-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: #f3f4f6;
  border-radius: 6px;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  color: #6b7280;
}

.dismiss-btn:hover {
  background: #e5e7eb;
  transform: scale(1.05);
}

.progress-bar {
  margin-top: -8px;
  margin-left: 16px;
  margin-right: 16px;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #34d399);
  border-radius: 3px;
  transition: width 1s linear;
}

.progress-text {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 9px;
  color: #6b7280;
  font-weight: 600;
}
</style>