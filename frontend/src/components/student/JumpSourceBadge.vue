<template>
  <div v-if="visible" class="jump-source-badge" :class="badgeClass">
    <div class="badge-content">
      <div class="badge-icon"><Bookmark :size="24" /></div>

      <div class="badge-info">
        <div class="badge-title">
          <AlertTriangle v-if="urgencyLevel === 'high'" :size="14" />
          <BookOpen v-else :size="14" />
          {{ title }}
        </div>
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
          <span v-if="!isReturning" class="btn-text"><ArrowLeft :size="14" /> 返回</span>
          <span v-else class="loading-dots">返回中...</span>
        </button>

        <button
          class="dismiss-btn"
          @click="handleDismiss"
          title="关闭提示"
        >
          <X :size="18" />
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
import { Bookmark, ArrowLeft, X, AlertTriangle, BookOpen } from 'lucide-vue-next'

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
      return '关键知识点复习'
    case 'medium':
      return '前置知识复习'
    default:
      return '知识点回顾'
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
  top: var(--space-5);
  left: 50%;
  transform: translateX(-50%);
  z-index: 998;
  animation: slideDownBadge var(--duration-slow) var(--ease);
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
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border: 2px solid transparent;
}

.jump-source-badge.urgency-high .badge-content {
  border-color: var(--color-danger-light);
  background: var(--color-danger-light);
}

.jump-source-badge.urgency-medium .badge-content {
  border-color: var(--color-warning-light);
  background: var(--color-warning-light);
}

.jump-source-badge.urgency-low .badge-content {
  border-color: var(--color-success-light);
  background: var(--color-success-light);
}

.badge-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.badge-info {
  flex: 1;
  min-width: 0;
}

.badge-title {
  font-weight: var(--font-bold);
  font-size: var(--text-sm);
  color: var(--color-text);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.badge-detail {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.4;
}

.depth-indicator {
  color: var(--color-danger);
  font-weight: var(--font-semibold);
  margin-left: var(--space-1);
}

.badge-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.return-btn {
  padding: var(--space-2) 18px;
  border: none;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
  background: var(--gradient-success);
  color: var(--color-text-inverse);
  box-shadow: var(--shadow-success);
}

.return-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.return-btn:disabled {
  opacity: 0.7;
  cursor: wait;
}

.btn-text {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
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
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-normal) var(--ease);
  color: var(--color-text-secondary);
}

.dismiss-btn:hover {
  background: var(--color-border);
  transform: translateY(-2px);
}

.progress-bar {
  margin-top: -8px;
  margin-left: var(--space-4);
  margin-right: var(--space-4);
  height: 6px;
  background: var(--color-border);
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--gradient-success);
  border-radius: 3px;
  transition: width 1s linear;
}

.progress-text {
  position: absolute;
  right: var(--space-2);
  top: 50%;
  transform: translateY(-50%);
  font-size: 9px;
  color: var(--color-text-secondary);
  font-weight: var(--font-semibold);
}
</style>
