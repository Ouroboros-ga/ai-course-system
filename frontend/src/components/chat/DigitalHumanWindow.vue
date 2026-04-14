<template>
  <div class="digital-human-wrapper" :style="wrapperStyle">
    <Transition name="slide-fade">
      <div
        v-if="isOpen"
        class="dh-panel"
        :class="{ 'is-dragging': isDragging, 'is-minimized': isMinimized }"
        :style="panelStyle"
      >
        <div
          class="dh-header"
          @mousedown="startDrag"
          @touchstart="startDrag"
        >
          <div class="dh-title">
            <span class="dh-avatar">🎬</span>
            <span>智课视频播放器</span>
            <span v-if="isMinimized" class="minimized-badge">最小化</span>
          </div>
          <div class="dh-actions">
            <button class="dh-btn" @click="refreshVideos" title="刷新视频列表">🔄</button>
            <button class="dh-btn" @click="clearVideo" title="清空">🗑️</button>
            <button class="dh-btn" @click="toggleMinimize" :title="isMinimized ? '还原' : '最小化'">
              {{ isMinimized ? '🔲' : '➖' }}
            </button>
            <button class="dh-btn" @click="togglePanel" title="关闭">✕</button>
          </div>
        </div>

        <div v-show="!isMinimized" class="dh-content">
          <div v-if="!videoUrl && videos.length === 0" class="dh-empty">
            <div class="dh-empty-icon">📺</div>
            <p>暂无视频</p>
            <p class="dh-empty-hint">请先上传视频或输入视频URL</p>
            <div class="quick-actions">
              <button class="quick-btn primary" @click="loadSampleVideo">📡 示例视频</button>
              <button class="quick-btn" @click="showUrlInput = true" v-if="!showUrlInput">🔗 手动输入</button>
            </div>
          </div>

          <div v-if="videos.length > 0 && !videoUrl" class="video-list">
            <div class="video-list-header">
              <span>📁 本地视频 ({{ videos.length }})</span>
            </div>
            <div
              v-for="video in videos"
              :key="video.filename"
              class="video-item"
              @click="loadLocalVideo(video)"
            >
              <span class="video-icon">🎬</span>
              <span class="video-name">{{ video.filename }}</span>
              <span class="video-size">{{ formatSize(video.size) }}</span>
            </div>
          </div>

          <div v-if="showUrlInput" class="url-input-section">
            <input
              v-model="inputUrl"
              @keyup.enter="loadVideo"
              placeholder="输入视频URL或MP4链接..."
              class="url-input"
              ref="urlInputRef"
            />
            <div class="url-actions">
              <button class="action-btn cancel" @click="showUrlInput = false; inputUrl = ''">取消</button>
              <button class="action-btn confirm" @click="loadVideo" :disabled="!inputUrl.trim()">播放</button>
            </div>
          </div>

          <div v-if="videoUrl" class="video-wrapper">
            <video
              ref="videoRef"
              class="dh-video"
              :src="videoUrl"
              @timeupdate="onTimeUpdate"
              @loadedmetadata="onLoadedMetadata"
              @ended="onEnded"
              @error="onError"
              @play="onPlay"
              @pause="onPause"
              @waiting="onWaiting"
              @canplay="onCanPlay"
              @progress="onProgress"
            ></video>

            <div class="video-controls-overlay" v-if="showControls">
              <div class="controls-top">
                <span class="video-title">{{ currentVideoName }}</span>
                <button class="close-btn" @click="clearVideo">✕</button>
              </div>
              <div class="controls-center">
                <button class="play-btn" @click="togglePlay">
                  {{ isPlaying ? '⏸️' : '▶️' }}
                </button>
              </div>
              <div class="controls-bottom">
                <div class="progress-container" @click="seekVideo" @mousedown="startProgressDrag">
                  <div class="progress-buffered" :style="{ width: bufferedPercent + '%' }"></div>
                  <div class="progress-played" :style="{ width: progressPercent + '%' }"></div>
                  <div class="progress-thumb" :style="{ left: progressPercent + '%' }" v-if="duration"></div>
                </div>
                <div class="time-display">
                  <span>{{ formatTime(currentTime) }}</span>
                  <span>/</span>
                  <span>{{ formatTime(duration) }}</span>
                </div>
                <div class="volume-control">
                  <span @click="toggleMute">{{ isMuted ? '🔇' : '🔊' }}</span>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    :value="volume"
                    @input="setVolume"
                    class="volume-slider"
                  />
                </div>
              </div>
            </div>

            <div class="loading-overlay" v-if="isLoading">
              <div class="spinner"></div>
              <span>加载中...</span>
            </div>
          </div>
        </div>

        <div v-show="!isMinimized && !videoUrl" class="dh-input-area">
          <button class="add-video-btn" @click="showUrlInput = !showUrlInput">
            {{ showUrlInput ? '取消' : '+ 添加视频链接' }}
          </button>
        </div>

        <!-- 最小化时的提示 -->
        <div v-if="isMinimized" class="minimized-hint" @click="toggleMinimize">
          <span>🎬 视频播放中 - 点击展开</span>
        </div>
      </div>
    </Transition>

    <Transition name="bounce">
      <div v-if="!isOpen" class="dh-fab" @click="togglePanel" :style="fabStyle">
        <span class="fab-icon">🎬</span>
        <span v-if="isPlaying" class="playing-indicator"></span>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, onUnmounted } from 'vue'
import api from '@/api/index.js'

const STORAGE_KEY = 'videoPlayerPosition'

const isOpen = ref(false)
const videoUrl = ref('')
const inputUrl = ref('')
const videoRef = ref(null)
const urlInputRef = ref(null)
const videos = ref([])
const currentVideoName = ref('')
const showUrlInput = ref(false)
const showControls = ref(true)
const isLoading = ref(false)
const isMinimized = ref(false)

// 拖拽相关状态
const isDragging = ref(false)
const position = ref({ x: 0, y: 0 })
const dragOffset = ref({ x: 0, y: 0 })
const fabPosition = ref({ x: 20, y: 20 }) // 悬浮按钮位置

// Video state
const currentTime = ref(0)
const duration = ref(0)
const bufferedPercent = ref(0)
const isPlaying = ref(false)
const hasError = ref(false)
const isMuted = ref(false)
const volume = ref(1)
const isProgressDragging = ref(false)

const progressPercent = computed(() => {
  if (!duration.value) return 0
  return (currentTime.value / duration.value) * 100
})

// 面板样式（支持拖拽定位）
const panelStyle = computed(() => {
  if (position.value.x === 0 && position.value.y === 0) {
    return {} // 使用默认CSS定位
  }
  return {
    position: 'fixed',
    left: `${position.value.x}px`,
    top: `${position.value.y}px`,
    right: 'auto',
    bottom: 'auto',
  }
})

// 悬浮按钮样式
const fabStyle = computed(() => {
  return {
    right: `${fabPosition.value.x}px`,
    bottom: `${fabPosition.value.y}px`,
  }
})

// 包装器样式
const wrapperStyle = computed(() => {
  if (!isOpen.value && (fabPosition.value.x !== 20 || fabPosition.value.y !== 20)) {
    return {
      right: `${fabPosition.value.x}px`,
      bottom: `${fabPosition.value.y}px`,
    }
  }
  return {}
})

// 从localStorage加载位置
function loadPosition() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const pos = JSON.parse(saved)
      position.value = { x: pos.x || 0, y: pos.y || 0 }
      fabPosition.value = { x: pos.fabX || 20, y: pos.fabY || 20 }
    }
  } catch (e) {
    console.error('加载位置失败:', e)
  }
}

// 保存位置到localStorage
function savePosition() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      x: position.value.x,
      y: position.value.y,
      fabX: fabPosition.value.x,
      fabY: fabPosition.value.y,
    }))
  } catch (e) {
    console.error('保存位置失败:', e)
  }
}

// 开始拖拽
function startDrag(event) {
  // 只有点击头部才能拖拽
  if (event.target.closest('.dh-btn')) return

  isDragging.value = true
  const clientX = event.type.includes('touch') ? event.touches[0].clientX : event.clientX
  const clientY = event.type.includes('touch') ? event.touches[0].clientY : event.clientY

  // 如果还没有设置位置，先获取当前位置
  if (position.value.x === 0 && position.value.y === 0) {
    const panel = event.currentTarget.closest('.dh-panel')
    const rect = panel.getBoundingClientRect()
    position.value = { x: rect.left, y: rect.top }
  }

  dragOffset.value = {
    x: clientX - position.value.x,
    y: clientY - position.value.y,
  }

  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', endDrag)
  document.addEventListener('touchmove', onDrag)
  document.addEventListener('touchend', endDrag)
}

// 拖拽中
function onDrag(event) {
  if (!isDragging.value) return

  event.preventDefault()
  const clientX = event.type.includes('touch') ? event.touches[0].clientX : event.clientX
  const clientY = event.type.includes('touch') ? event.touches[0].clientY : event.clientY

  let newX = clientX - dragOffset.value.x
  let newY = clientY - dragOffset.value.y

  // 限制在视口内
  const panelWidth = 420
  const panelHeight = isMinimized.value ? 60 : 580
  const maxX = window.innerWidth - panelWidth
  const maxY = window.innerHeight - panelHeight

  newX = Math.max(0, Math.min(newX, maxX))
  newY = Math.max(0, Math.min(newY, maxY))

  position.value = { x: newX, y: newY }
}

// 结束拖拽
function endDrag() {
  if (isDragging.value) {
    isDragging.value = false
    savePosition()
  }
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', endDrag)
  document.removeEventListener('touchmove', onDrag)
  document.removeEventListener('touchend', endDrag)
}

function togglePanel() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    isMinimized.value = false
    nextTick(() => {
      refreshVideos()
    })
  }
}

function toggleMinimize() {
  isMinimized.value = !isMinimized.value
  // 最小化时保存状态
  if (isMinimized.value) {
    savePosition()
  }
}

async function refreshVideos() {
  try {
    const res = await api.video.list()
    videos.value = res.videos || []
  } catch (error) {
    console.error('获取视频列表失败:', error)
    videos.value = []
  }
}

function clearVideo() {
  videoUrl.value = ''
  inputUrl.value = ''
  currentVideoName.value = ''
  currentTime.value = 0
  duration.value = 0
  bufferedPercent.value = 0
  hasError.value = false
  isPlaying.value = false
  isLoading.value = false
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
}

function loadVideo() {
  const url = inputUrl.value.trim()
  if (!url) return

  hasError.value = false
  isLoading.value = true
  currentVideoName.value = url.split('/').pop() || '远程视频'
  videoUrl.value = url
  showUrlInput.value = false
}

function loadLocalVideo(video) {
  currentVideoName.value = video.filename
  videoUrl.value = video.url
  isLoading.value = true
}

function loadSampleVideo() {
  inputUrl.value = 'https://www.w3schools.com/html/mov_bbb.mp4'
  currentVideoName.value = '示例视频 - Big Buck Bunny'
  videoUrl.value = inputUrl.value
  isLoading.value = true
}

function togglePlay() {
  if (!videoRef.value) return

  if (isPlaying.value) {
    videoRef.value.pause()
  } else {
    videoRef.value.play()
  }
}

function toggleMute() {
  if (!videoRef.value) return
  isMuted.value = !isMuted.value
  videoRef.value.muted = isMuted.value
}

function setVolume(event) {
  const val = parseFloat(event.target.value)
  volume.value = val
  if (videoRef.value) {
    videoRef.value.volume = val
    isMuted.value = val === 0
  }
}

function onTimeUpdate() {
  if (videoRef.value && !isProgressDragging.value) {
    currentTime.value = videoRef.value.currentTime
  }
}

function onLoadedMetadata() {
  if (videoRef.value) {
    duration.value = videoRef.value.duration
    isLoading.value = false
  }
}

function onProgress() {
  if (videoRef.value && videoRef.value.buffered.length > 0) {
    bufferedPercent.value = (videoRef.value.buffered.end(0) / duration.value) * 100
  }
}

function onEnded() {
  isPlaying.value = false
}

function onError() {
  hasError.value = true
  isLoading.value = false
  console.error('视频加载失败')
}

function onPlay() {
  isPlaying.value = true
}

function onPause() {
  isPlaying.value = false
}

function onWaiting() {
  isLoading.value = true
}

function onCanPlay() {
  isLoading.value = false
}

function seekVideo(event) {
  if (!videoRef.value || !duration.value) return

  const progressBar = event.currentTarget
  const rect = progressBar.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const percent = Math.max(0, Math.min(1, clickX / rect.width))
  const newTime = percent * duration.value

  videoRef.value.currentTime = newTime
  currentTime.value = newTime
}

function startProgressDrag(event) {
  isProgressDragging.value = true
  document.addEventListener('mousemove', onProgressDrag)
  document.addEventListener('mouseup', endProgressDrag)
}

function onProgressDrag(event) {
  if (!isProgressDragging.value || !videoRef.value) return

  const progressBar = document.querySelector('.progress-container')
  if (!progressBar) return

  const rect = progressBar.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const percent = Math.max(0, Math.min(1, clickX / rect.width))
  const newTime = percent * duration.value

  currentTime.value = newTime
}

function endProgressDrag() {
  if (isProgressDragging.value && videoRef.value) {
    videoRef.value.currentTime = currentTime.value
  }
  isProgressDragging.value = false
  document.removeEventListener('mousemove', onProgressDrag)
  document.removeEventListener('mouseup', endProgressDrag)
}

function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`
}

onMounted(() => {
  loadPosition()
  refreshVideos()
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', endDrag)
  document.removeEventListener('touchmove', onDrag)
  document.removeEventListener('touchend', endDrag)
  document.removeEventListener('mousemove', onProgressDrag)
  document.removeEventListener('mouseup', endProgressDrag)
})
</script>

<style scoped>
.digital-human-wrapper {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 999;
}

.dh-panel {
  width: 420px;
  height: 580px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15), 0 2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  transition: transform 0.1s ease, box-shadow 0.2s ease, height 0.3s ease;
}

.dh-panel.is-dragging {
  cursor: grabbing;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
  transform: scale(1.02);
}

.dh-panel.is-minimized {
  height: 60px;
  min-height: 60px;
}

.dh-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  flex-shrink: 0;
  cursor: grab;
  user-select: none;
}

.dh-header:active {
  cursor: grabbing;
}

.dh-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}

.dh-avatar {
  font-size: 18px;
}

.minimized-badge {
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 10px;
  margin-left: 4px;
}

.dh-actions {
  display: flex;
  gap: 4px;
}

.dh-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;
}

.dh-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.minimized-hint {
  padding: 12px 16px;
  background: #1a1a1a;
  color: #9ca3af;
  text-align: center;
  cursor: pointer;
  font-size: 13px;
  border-top: 1px solid #333;
}

.minimized-hint:hover {
  background: #2a2a2a;
  color: #e5e7eb;
}

.dh-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #1a1a1a;
}

.dh-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  padding: 20px;
}

.dh-empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.dh-empty p {
  margin: 4px 0;
  font-size: 14px;
}

.dh-empty-hint {
  font-size: 12px !important;
  color: #6b7280 !important;
}

.quick-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.quick-btn {
  padding: 8px 16px;
  background: #374151;
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.quick-btn:hover {
  background: #4b5563;
}

.quick-btn.primary {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
}

.quick-btn.primary:hover {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.video-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.video-list-header {
  padding: 8px 12px;
  color: #9ca3af;
  font-size: 12px;
  border-bottom: 1px solid #374151;
  margin-bottom: 8px;
}

.video-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.video-item:hover {
  background: #2a2a2a;
}

.video-icon {
  font-size: 18px;
}

.video-name {
  flex: 1;
  color: #e5e7eb;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-size {
  color: #6b7280;
  font-size: 11px;
}

.url-input-section {
  padding: 16px;
  background: #2a2a2a;
}

.url-input {
  width: 100%;
  padding: 10px 14px;
  background: #1a1a1a;
  border: 1px solid #4b5563;
  border-radius: 8px;
  color: white;
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}

.url-input:focus {
  border-color: #6366f1;
}

.url-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  justify-content: flex-end;
}

.action-btn {
  padding: 6px 16px;
  border: none;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.cancel {
  background: #4b5563;
  color: #e5e7eb;
}

.action-btn.confirm {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.video-wrapper {
  flex: 1;
  position: relative;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dh-video {
  max-width: 100%;
  max-height: 100%;
  width: 100%;
  height: auto;
  display: block;
}

.video-controls-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: linear-gradient(
    to bottom,
    rgba(0,0,0,0.5) 0%,
    transparent 20%,
    transparent 80%,
    rgba(0,0,0,0.7) 100%
  );
  opacity: 0;
  transition: opacity 0.3s ease;
}

.video-wrapper:hover .video-controls-overlay {
  opacity: 1;
}

.controls-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
}

.video-title {
  color: white;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.close-btn {
  background: rgba(255,255,255,0.2);
  border: none;
  color: white;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 12px;
}

.controls-center {
  display: flex;
  justify-content: center;
  align-items: center;
}

.play-btn {
  background: rgba(255,255,255,0.2);
  border: none;
  color: white;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 20px;
  transition: transform 0.2s ease;
}

.play-btn:hover {
  transform: scale(1.1);
  background: rgba(255,255,255,0.3);
}

.controls-bottom {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-container {
  flex: 1;
  height: 4px;
  background: rgba(255,255,255,0.2);
  border-radius: 2px;
  cursor: pointer;
  position: relative;
}

.progress-container:hover {
  height: 6px;
}

.progress-buffered {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: rgba(255,255,255,0.3);
  border-radius: 2px;
}

.progress-played {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 2px;
}

.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.time-display {
  display: flex;
  gap: 4px;
  color: white;
  font-size: 11px;
  font-family: monospace;
  white-space: nowrap;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 4px;
  color: white;
  font-size: 12px;
}

.volume-slider {
  width: 60px;
  height: 4px;
  -webkit-appearance: none;
  background: rgba(255,255,255,0.3);
  border-radius: 2px;
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 10px;
  height: 10px;
  background: white;
  border-radius: 50%;
}

.loading-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: white;
  font-size: 12px;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.dh-input-area {
  padding: 12px;
  background: #2a2a2a;
  flex-shrink: 0;
}

.add-video-btn {
  width: 100%;
  padding: 10px;
  background: #374151;
  color: #e5e7eb;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.add-video-btn:hover {
  background: #4b5563;
}

.dh-fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
  transition: all 0.3s ease;
  position: relative;
}

.dh-fab:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 24px rgba(99, 102, 241, 0.5);
}

.fab-icon {
  font-size: 24px;
}

.playing-indicator {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 12px;
  height: 12px;
  background: #22c55e;
  border-radius: 50%;
  border: 2px solid white;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.2); opacity: 0.8; }
}

.slide-fade-enter-active {
  transition: all 0.3s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.2s ease-in;
}

.slide-fade-enter-from {
  transform: translateY(20px);
  opacity: 0;
}

.slide-fade-leave-to {
  transform: translateY(20px);
  opacity: 0;
}

.bounce-enter-active {
  animation: bounce-in 0.4s ease;
}

.bounce-leave-active {
  animation: bounce-in 0.2s ease reverse;
}

@keyframes bounce-in {
  0% { transform: scale(0); }
  50% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

@media (max-width: 768px) {
  .dh-panel {
    width: calc(100vw - 40px);
    max-width: 420px;
    height: 60vh;
    max-height: 580px;
  }

  .dh-panel.is-minimized {
    height: 60px;
    min-height: 60px;
  }

  .digital-human-wrapper {
    right: 10px;
    bottom: 10px;
  }
}
</style>
