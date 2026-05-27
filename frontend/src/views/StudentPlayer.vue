<template>
  <div class="player-page">
    <!-- 顶部导航栏 -->
    <div class="page-header">
      <button class="back-btn" @click="goBack">← 返回课程</button>
      <h1 class="page-title">{{ courseTitle || '分屏视频播放器' }}</h1>
      <div class="header-actions">
        <button
          v-if="showChatToggle"
          @click="toggleMode"
          class="mode-toggle-btn"
        >
          {{ isPlayerMode ? '💬 切换到聊天模式' : '🎬 切换到播放器模式' }}
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
        <span class="icon">💬</span>
        <p>聊天学习模式</p>
        <button @click="toggleMode" class="switch-btn">切换到播放器模式</button>
      </div>
    </div>

    <!-- 底部状态栏 -->
    <div v-if="isPlayerMode && lastProgress" class="status-bar">
      <div class="status-item">
        <span class="label">⏱️ 当前时间:</span>
        <span class="value">{{ formatTime(lastProgress.timestamp) }}</span>
      </div>
      <div class="status-item">
        <span class="label">📄 PPT页面:</span>
        <span class="value">第 {{ lastProgress.page }} 页</span>
      </div>
      <div class="status-item">
        <span class="label">📊 完成度:</span>
        <span class="value highlight">{{ lastProgress.completionRate }}%</span>
      </div>
      <div class="status-item">
        <span class="label">📍 知识点:</span>
        <span class="value">{{ lastProgress.nodeIndex + 1 }} / {{ totalNodes }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SplitVideoPlayer from '@/components/chat/player/SplitVideoPlayer.vue'

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
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #000;
  overflow: hidden;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #1a1a1a;
  border-bottom: 2px solid #333;
  z-index: 100;
}

.back-btn,
.mode-toggle-btn {
  padding: 8px 16px;
  background: #333;
  color: #fff;
  border: 1px solid #555;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.back-btn:hover,
.mode-toggle-btn:hover {
  background: #4CAF50;
  border-color: #4CAF50;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}

.header-actions {
  display: flex;
  gap: 10px;
}

/* 聊天模式占位 */
.chat-mode-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
}

.placeholder-content {
  text-align: center;
  color: #666;
}

.placeholder-content .icon {
  font-size: 64px;
  display: block;
  margin-bottom: 20px;
}

.switch-btn {
  margin-top: 20px;
  padding: 12px 24px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 16px;
}

.switch-btn:hover {
  background: #45a049;
}

/* 底部状态栏 */
.status-bar {
  display: flex;
  gap: 30px;
  padding: 10px 20px;
  background: #252525;
  border-top: 1px solid #444;
  font-size: 13px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #aaa;
}

.status-item .label {
  color: #888;
}

.status-item .value {
  color: #fff;
  font-weight: 500;
}

.status-item .value.highlight {
  color: #4CAF50;
  font-weight: 600;
}
</style>
