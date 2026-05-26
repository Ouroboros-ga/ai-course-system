<template>
  <div class="knowledge-nav-bar">
    <div class="nav-header">
      <span class="nav-title">📚 知识点导航</span>
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
          <span v-if="point.is_completed" class="status-icon completed">✓</span>
          <span v-else-if="index === currentPointIndex" class="status-icon active">▶</span>
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
    >◀</button>
    <button
      v-if="showScrollRight"
      @click="scrollRight"
      class="scroll-btn scroll-right"
    >▶</button>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'

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
  background: #252525;
  border-top: 2px solid #3a3a3a;
  border-bottom: 2px solid #3a3a3a;
  padding: 12px 0;
}

.nav-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px 8px;
  font-size: 13px;
  color: #aaa;
}

.nav-title {
  font-weight: 600;
  color: #4CAF50;
}

.nav-count {
  color: #888;
}

.nav-content {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 20px 8px;
  scroll-behavior: smooth;

  /* 隐藏滚动条但保持可滚动 */
  scrollbar-width: thin;
  scrollbar-color: #4CAF50 #333;
}

.nav-content::-webkit-scrollbar {
  height: 6px;
}

.nav-content::-webkit-scrollbar-track {
  background: #333;
  border-radius: 3px;
}

.nav-content::-webkit-scrollbar-thumb {
  background: #4CAF50;
  border-radius: 3px;
}

.knowledge-point {
  position: relative;
  flex-shrink: 0;
  min-width: 140px;
  max-width: 180px;
  padding: 10px 14px;
  background: #333;
  border: 2px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s ease;
  overflow: hidden;
}

.knowledge-point:hover {
  background: #3a3a3a;
  border-color: #555;
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
}

.knowledge-point.active {
  background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
  border-color: #66BB6A;
  box-shadow: 0 0 15px rgba(76, 175, 80, 0.4);
}

.knowledge-point.completed:not(.active) {
  background: #2d4a2e;
  border-color: #4a7c4e;
}

.knowledge-point.completed:not(.active):hover {
  background: #365a38;
}

.point-status {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
}

.status-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: bold;
}

.status-icon.completed {
  background: #4CAF50;
  color: white;
}

.status-icon.active {
  background: rgba(255, 255, 255, 0.9);
  color: #4CAF50;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.7; transform: scale(1.1); }
}

.number {
  background: #555;
  color: #ccc;
  font-size: 11px;
}

.point-info {
  position: relative;
  z-index: 1;
}

.point-title {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  margin-bottom: 4px;
  word-break: break-word;
}

.active .point-title {
  color: #fff;
}

.completed .point-title {
  color: #a5d6a7;
}

.point-time {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  font-family: monospace;
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
  background: #fff;
  transition: width 0.3s ease;
}

/* 滚动按钮 */
.scroll-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 10;
  background: rgba(76, 175, 80, 0.9);
  color: white;
  border: none;
  width: 28px;
  height: 32px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.scroll-btn:hover {
  background: rgba(76, 175, 80, 1);
  transform: translateY(-50%) scale(1.05);
}

.scroll-left {
  left: 4px;
  border-radius: 0 4px 4px 0;
}

.scroll-right {
  right: 4px;
  border-radius: 4px 0 0 4px;
}
</style>
