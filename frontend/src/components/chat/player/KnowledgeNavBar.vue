<template>
  <div class="knowledge-nav-bar">
    <div class="nav-header">
      <span class="nav-title"><BookOpen :size="14" /> 知识点导航</span>
      <span class="nav-count">({{ currentPointIndex + 1 }}/{{ knowledgePoints.length }})</span>
    </div>

    <div class="nav-content" ref="navContentRef">
      <div
        v-for="(point, index) in knowledgePoints"
        :key="point.node_id"
        :class="['knowledge-point', {
          'active': index === currentPointIndex,
          'completed': point.is_completed,
          'current-range': isCurrentRange(point),
        }]"
        @click="$emit('jump-to-knowledge', point)"
        :title="`${point.title}\n${formatDuration(point.timestamp_start)} - ${formatDuration(point.timestamp_end)}`"
      >
        <div class="point-status">
          <span v-if="point.is_completed" class="status-icon completed"><Check :size="12" /></span>
          <span v-else-if="index === currentPointIndex" class="status-icon active"><Play :size="10" /></span>
          <span v-else class="number">{{ index + 1 }}</span>
        </div>

        <div class="point-info">
          <div class="point-title">{{ truncateTitle(point.title, 20) }}</div>
          <div class="point-time" v-if="index === currentPointIndex">
            {{ formatDuration(currentTimestamp - point.timestamp_start) }} / {{ formatDuration(point.timestamp_end - point.timestamp_start) }}
          </div>
        </div>

        <!-- 进度条（当前正在播放的知识点） -->
        <div
          v-if="index === currentPointIndex && currentTimestamp >= point.timestamp_start"
          class="point-progress"
        >
          <div
            class="progress-fill"
            :style="{ width: calculateProgress(point) + '%' }"
          ></div>
        </div>
      </div>
    </div>

    <!-- 左右滚动按钮 -->
    <button
      v-if="showScrollLeft"
      @click="scrollLeft"
      class="scroll-btn scroll-left"
    ><ChevronLeft :size="16" /></button>
    <button
      v-if="showScrollRight"
      @click="scrollRight"
      class="scroll-btn scroll-right"
    ><ChevronRight :size="16" /></button>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { BookOpen, Check, Play, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = defineProps({
  knowledgePoints: {
    type: Array,
    required: true,
    default: () => [],
  },
  currentNodeIndex: {
    type: Number,
    default: 0,
  },
  currentTimestamp: {
    type: Number,
    default: 0,
  },
})

defineEmits(['jump-to-knowledge'])

const navContentRef = ref(null)
const showScrollLeft = ref(false)
const showScrollRight = ref(false)

// 当前激活的知识点索引（基于时间戳匹配）
const currentPointIndex = computed(() => {
  return props.currentNodeIndex
})

// 监听当前节点变化，自动滚动到可见区域
watch(currentPointIndex, async (newIndex) => {
  await nextTick()
  scrollToCurrentPoint(newIndex)
})

// 检查是否在当前知识点的范围内
function isCurrentRange(point) {
  const timestamp = props.currentTimestamp
  return timestamp >= point.timestamp_start && timestamp <= point.timestamp_end
}

// 计算当前知识点的播放进度百分比
function calculateProgress(point) {
  if (!isCurrentRange(point)) return 0

  const total = point.timestamp_end - point.timestamp_start
  if (total <= 0) return 0

  const current = props.currentTimestamp - point.timestamp_start
  return Math.min(100, Math.max(0, (current / total) * 100))
}

// 滚动到当前知识点
async function scrollToCurrentPoint(index) {
  if (!navContentRef.value) return

  await nextTick()

  const points = navContentRef.value.querySelectorAll('.knowledge-point')
  if (points[index]) {
    points[index].scrollIntoView({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'center',
    })
  }
}

// 手动滚动控制
function scrollLeft() {
  if (navContentRef.value) {
    navContentRef.value.scrollBy({ left: -200, behavior: 'smooth' })
  }
}

function scrollRight() {
  if (navContentRef.value) {
    navContentRef.value.scrollBy({ left: 200, behavior: 'smooth' })
  }
}

// 更新滚动按钮显示状态
function updateScrollButtons() {
  if (!navContentRef.value) return

  const { scrollLeft, scrollWidth, clientWidth } = navContentRef.value
  showScrollLeft.value = scrollLeft > 10
  showScrollRight.value = scrollLeft < scrollWidth - clientWidth - 10
}

// 工具函数：格式化时长
function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return '00:00'

  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)

  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

// 工具函数：截断标题
function truncateTitle(title, maxLength) {
  if (!title) return ''
  if (title.length <= maxLength) return title
  return title.substring(0, maxLength) + '...'
}

// 生命周期
onMounted(() => {
  // 监听滚动事件更新按钮状态
  if (navContentRef.value) {
    navContentRef.value.addEventListener('scroll', updateScrollButtons)
    updateScrollButtons()

    // 初始延迟后检查一次
    setTimeout(updateScrollButtons, 500)
  }
})
</script>

<style scoped>
.knowledge-nav-bar {
  position: relative;
  background: var(--color-text);
  border-top: 2px solid var(--color-border);
  border-bottom: 2px solid var(--color-border);
  padding: var(--space-3) 0;
}

.nav-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 var(--space-5) var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.nav-title {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: 600;
  color: var(--color-success);
}

.nav-count {
  color: var(--color-text-muted);
}

.nav-content {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 var(--space-5) var(--space-2);
  scroll-behavior: smooth;

  /* 隐藏滚动条但保持可滚动 */
  scrollbar-width: thin;
  scrollbar-color: var(--color-success) var(--color-border);
}

.nav-content::-webkit-scrollbar {
  height: 6px;
}

.nav-content::-webkit-scrollbar-track {
  background: var(--color-border);
  border-radius: var(--radius-full);
}

.nav-content::-webkit-scrollbar-thumb {
  background: var(--color-success);
  border-radius: var(--radius-full);
}

.knowledge-point {
  position: relative;
  flex-shrink: 0;
  min-width: 140px;
  max-width: 180px;
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.05);
  border: 2px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--duration-slow) var(--ease), border-color var(--duration-slow) var(--ease), transform var(--duration-slow) var(--ease);
  overflow: hidden;
}

.knowledge-point:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--color-border-hover);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.knowledge-point.active {
  background: var(--gradient-success);
  border-color: var(--color-success-hover);
  box-shadow: var(--shadow-primary);
}

.knowledge-point.completed:not(.active) {
  background: rgba(16, 185, 129, 0.15);
  border-color: var(--color-success);
}

.knowledge-point.completed:not(.active):hover {
  background: rgba(16, 185, 129, 0.25);
}

.point-status {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-1);
}

.status-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
}

.status-icon.completed {
  background: var(--color-success);
  color: var(--color-text-inverse);
}

.status-icon.active {
  background: rgba(255, 255, 255, 0.9);
  color: var(--color-success);
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.7; transform: scale(1.1); }
}

.number {
  background: var(--color-border);
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
}

.point-info {
  position: relative;
  z-index: 1;
}

.point-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-inverse);
  line-height: 1.3;
  margin-bottom: var(--space-1);
  word-break: break-word;
}

.active .point-title {
  color: var(--color-text-inverse);
}

.completed .point-title {
  color: var(--color-success-light);
}

.point-time {
  font-size: var(--text-xs);
  color: rgba(255, 255, 255, 0.9);
  font-family: var(--font-mono);
}

/* 进度条 */
.point-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: rgba(255, 255, 255, 0.2);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-text-inverse);
  transition: width var(--duration-slow) var(--ease);
}

/* 滚动按钮 */
.scroll-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: var(--z-overlay);
  background: var(--color-success);
  color: var(--color-text-inverse);
  border: none;
  width: 28px;
  height: 32px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-normal) var(--ease);
}

.scroll-btn:hover {
  background: var(--color-success-hover);
}

.scroll-left {
  left: var(--space-1);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.scroll-right {
  right: var(--space-1);
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}
</style>
