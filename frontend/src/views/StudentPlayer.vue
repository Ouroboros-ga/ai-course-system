<template>
  <div class="player-page">
    <!-- 顶部导航栏 -->
    <div class="page-header">
      <button class="back-btn" @click="goBack"><ArrowLeft :size="16" /> 返回课程</button>
      <h1 class="page-title">{{ courseTitle || '分屏视频播放器' }}</h1>
      <div class="header-actions">
        <button
          v-if="showChatToggle"
          @click="toggleMode"
          class="mode-toggle-btn"
        >
          <MessageCircle v-if="isPlayerMode" :size="16" />
          <Clapperboard v-else :size="16" />
          {{ isPlayerMode ? '切换到聊天模式' : '切换到播放器模式' }}
        </button>
      </div>
    </div>

    <!-- 分屏播放器主体 -->
    <SplitVideoPlayer
      v-if="isPlayerMode"
      :course-id="courseId"
      @progress-update="onProgressUpdate"
      @node-change="onNodeChange"
      @error="onPlayerError"
    />

    <!-- 聊天学习模式（可选） -->
    <div v-else class="chat-mode-placeholder">
      <div class="placeholder-content">
        <span class="icon"><MessageCircle :size="64" :stroke-width="1.5" /></span>
        <p>聊天学习模式</p>
        <button @click="toggleMode" class="switch-btn">切换到播放器模式</button>
      </div>
    </div>

    <!-- 底部状态栏 -->
    <div v-if="isPlayerMode && lastProgress" class="status-bar">
      <div class="status-item">
        <span class="label"><Clock :size="14" /> 当前时间:</span>
        <span class="value">{{ formatTime(lastProgress.timestamp) }}</span>
      </div>
      <div class="status-item">
        <span class="label"><FileText :size="14" /> PPT页面:</span>
        <span class="value">第 {{ lastProgress.page }} 页</span>
      </div>
      <div class="status-item">
        <span class="label"><BarChart3 :size="14" /> 完成度:</span>
        <span class="value highlight">{{ lastProgress.completionRate }}%</span>
      </div>
      <div class="status-item">
        <span class="label"><MapPin :size="14" /> 知识点:</span>
        <span class="value">{{ lastProgress.nodeIndex + 1 }} / {{ totalNodes }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SplitVideoPlayer from '@/components/chat/player/SplitVideoPlayer.vue'
import {
  ArrowLeft,
  MessageCircle,
  Clapperboard,
  Clock,
  FileText,
  BarChart3,
  MapPin,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

// 状态
const courseId = ref(parseInt(route.params.courseId) || 0)
const courseTitle = ref('')
const isPlayerMode = ref(true)
const showChatToggle = ref(false)
const lastProgress = ref(null)
const totalNodes = ref(0)

// 事件处理
function onProgressUpdate(progress) {
  console.log('[PlayerPage] 进度更新:', progress)
  lastProgress.value = progress
}

function onNodeChange(data) {
  console.log('[PlayerPage] 节点变化:', data)
}

function onPlayerError(error) {
  console.error('[PlayerPage] 播放器错误:', error)
}

function goBack() {
  router.push('/student')
}

function toggleMode() {
  isPlayerMode.value = !isPlayerMode.value
}

// 工具函数
function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '00:00'

  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)

  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

// 生命周期
onMounted(() => {
  if (route.query.title) {
    courseTitle.value = route.query.title
  }
})
</script>

<style scoped>
.player-page {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  display: flex;
  flex-direction: column;
  background: var(--color-text);
  overflow: hidden;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  background: var(--color-surface-2);
  border-bottom: 2px solid var(--color-surface-3);
  z-index: 100;
}

.back-btn,
.mode-toggle-btn {
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface-3);
  color: var(--color-text-inverse);
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-base);
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.back-btn:hover,
.mode-toggle-btn:hover {
  background: var(--color-success);
  border-color: var(--color-success);
}

.page-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text-inverse);
}

.header-actions {
  display: flex;
  gap: var(--space-3);
}

/* 聊天模式占位 */
.chat-mode-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-2);
}

.placeholder-content {
  text-align: center;
  color: var(--color-text-secondary);
}

.placeholder-content .icon {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-5);
  color: var(--color-text-muted);
}

.switch-btn {
  margin-top: var(--space-5);
  padding: var(--space-3) var(--space-5);
  background: var(--color-success);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-base);
  transition: var(--transition-all);
}

.switch-btn:hover {
  background: var(--color-success-hover);
}

/* 底部状态栏 */
.status-bar {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-3) var(--space-5);
  background: var(--color-surface-3);
  border-top: 1px solid var(--color-border);
  font-size: 13px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
}

.status-item .label {
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.status-item .value {
  color: var(--color-text-inverse);
  font-weight: var(--font-medium);
}

.status-item .value.highlight {
  color: var(--color-success);
  font-weight: var(--font-semibold);
}
</style>
