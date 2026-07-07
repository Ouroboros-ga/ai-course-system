<template>
  <div :class="['digital-human-wrapper', { floating: isFloating }]">
    <!-- 浮窗模式 -->
    <template v-if="isFloating">
      <Transition name="slide-fade">
        <div v-if="isOpen" class="dh-panel floating-panel">
          <div class="dh-header">
            <div class="dh-title">
              <span class="dh-avatar"><Clapperboard :size="18" /></span>
              <span>智课视频播放器</span>
            </div>
            <div class="dh-actions">
              <button class="dh-btn" @click="refreshVideos" title="刷新视频列表"><RefreshCw :size="14" /></button>
              <button class="dh-btn" @click="clearVideo" title="清空"><Trash2 :size="14" /></button>
              <button class="dh-btn" @click="isOpen = false" title="最小化"><Minus :size="14" /></button>
            </div>
          </div>
          <div class="dh-content">
        <div v-if="!videoUrl && videos.length === 0" class="dh-empty">
          <div class="dh-empty-icon"><MonitorPlay :size="48" /></div>
          <p>暂无视频</p>
          <p class="dh-empty-hint">请先上传视频或输入视频URL</p>
          <div class="quick-actions">
            <button class="quick-btn primary" @click="loadSampleVideo"><Radio :size="14" /> 示例视频</button>
            <button class="quick-btn" @click="showUrlInput = true" v-if="!showUrlInput"><Link :size="14" /> 手动输入</button>
            <button class="quick-btn" @click="triggerFileSelect"><FolderOpen :size="14" /> 本地文件</button>
          </div>
        </div>

        <div v-if="videos.length > 0 && !videoUrl" class="video-list">
          <div class="video-list-header">
            <span><Folder :size="14" /> 本地视频 ({{ videos.length }})</span>
          </div>
          <div
            v-for="video in videos"
            :key="video.filename"
            class="video-item"
            @click="loadLocalVideo(video)"
          >
            <span class="video-icon"><Clapperboard :size="18" /></span>
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
              <button class="close-btn" @click="clearVideo"><X :size="12" /></button>
            </div>
            <div class="controls-center">
              <button class="play-btn" @click="togglePlay">
                <Pause v-if="isPlaying" :size="20" />
                <Play v-else :size="20" />
              </button>
            </div>
            <div class="controls-bottom">
              <div class="progress-container" @click="seekVideo" @mousedown="startDrag">
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
                <span @click="toggleMute" class="volume-icon">
                  <VolumeX v-if="isMuted" :size="16" />
                  <Volume2 v-else :size="16" />
                </span>
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

          <LoadingSpinner v-if="isLoading" text="加载中..." />
        </div>
      </div>

      <div class="dh-input-area" v-if="!videoUrl">
        <input
          type="file"
          ref="fileInputRef"
          accept="video/*"
          style="display: none"
          @change="handleFileSelect"
        />
        <button class="add-video-btn" @click="showUrlInput = !showUrlInput">
          {{ showUrlInput ? '取消' : '+ 添加视频链接' }}
        </button>
      </div>
    </div>
      </Transition>

      <Transition name="bounce">
        <div v-if="!isOpen" class="dh-fab" @click="isOpen = true">
          <span class="fab-icon"><Clapperboard :size="24" /></span>
        </div>
      </Transition>
    </template>

    <!-- 内嵌模式 -->
    <template v-else>
      <div class="dh-panel">
        <div class="dh-header">
          <div class="dh-title">
            <span class="dh-avatar"><Clapperboard :size="18" /></span>
            <span>智课视频播放器</span>
          </div>
          <div class="dh-actions">
            <button class="dh-btn" @click="refreshVideos" title="刷新视频列表"><RefreshCw :size="14" /></button>
            <button class="dh-btn" @click="clearVideo" title="清空"><Trash2 :size="14" /></button>
          </div>
        </div>

        <div class="dh-content">
          <div v-if="!videoUrl && videos.length === 0" class="dh-empty">
            <div class="dh-empty-icon"><MonitorPlay :size="48" /></div>
            <p>暂无视频</p>
            <p class="dh-empty-hint">请先上传视频或输入视频URL</p>
            <div class="quick-actions">
              <button class="quick-btn primary" @click="loadSampleVideo"><Radio :size="14" /> 示例视频</button>
              <button class="quick-btn" @click="showUrlInput = true" v-if="!showUrlInput"><Link :size="14" /> 手动输入</button>
              <button class="quick-btn" @click="triggerFileSelect"><FolderOpen :size="14" /> 本地文件</button>
            </div>
          </div>

          <div v-if="videos.length > 0 && !videoUrl" class="video-list">
            <div class="video-list-header">
              <span><Folder :size="14" /> 本地视频 ({{ videos.length }})</span>
            </div>
            <div
              v-for="video in videos"
              :key="video.filename"
              class="video-item"
              @click="loadLocalVideo(video)"
            >
              <span class="video-icon"><Clapperboard :size="18" /></span>
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
                <button class="close-btn" @click="clearVideo"><X :size="12" /></button>
              </div>
              <div class="controls-center">
                <button class="play-btn" @click="togglePlay">
                  <Pause v-if="isPlaying" :size="20" />
                  <Play v-else :size="20" />
                </button>
              </div>
              <div class="controls-bottom">
                <div class="progress-container" @click="seekVideo" @mousedown="startDrag">
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
                  <span @click="toggleMute" class="volume-icon">
                    <VolumeX v-if="isMuted" :size="16" />
                    <Volume2 v-else :size="16" />
                  </span>
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

            <LoadingSpinner v-if="isLoading" text="加载中..." />
          </div>
        </div>

        <div class="dh-input-area" v-if="!videoUrl">
          <input
            type="file"
            ref="fileInputRef"
            accept="video/*"
            style="display: none"
            @change="handleFileSelect"
          />
          <button class="add-video-btn" @click="showUrlInput = !showUrlInput">
            {{ showUrlInput ? '取消' : '+ 添加视频链接' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { Clapperboard, RefreshCw, Trash2, Minus, MonitorPlay, Radio, Link, FolderOpen, Folder, VolumeX, Volume2, X, Play, Pause } from 'lucide-vue-next'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import api from '@/api/index.js'

const props = defineProps({
  floating: {
    type: Boolean,
    default: false
  }
})

const isFloating = computed(() => props.floating)
const isOpen = ref(false)
const videoUrl = ref('')
const inputUrl = ref('')
const videoRef = ref(null)
const urlInputRef = ref(null)
const fileInputRef = ref(null)
const videos = ref([])
const currentVideoName = ref('')
const showUrlInput = ref(false)
const showControls = ref(true)
const isLoading = ref(false)

// Video state
const currentTime = ref(0)
const duration = ref(0)
const bufferedPercent = ref(0)
const isPlaying = ref(false)
const hasError = ref(false)
const isMuted = ref(false)
const volume = ref(1)
const isDragging = ref(false)

const progressPercent = computed(() => {
  if (!duration.value) return 0
  return (currentTime.value / duration.value) * 100
})

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

function triggerFileSelect() {
  if (fileInputRef.value) {
    fileInputRef.value.click()
  }
}

function handleFileSelect(event) {
  const file = event.target.files[0]
  if (!file) return

  if (!file.type.startsWith('video/')) {
    alert('请选择有效的视频文件')
    return
  }

  const url = URL.createObjectURL(file)
  currentVideoName.value = file.name
  videoUrl.value = url
  isLoading.value = true
  
  // 清空input,允许重复选择同一文件
  event.target.value = ''
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
  if (videoRef.value && !isDragging.value) {
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

function startDrag(event) {
  isDragging.value = true
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', endDrag)
}

function onDrag(event) {
  if (!isDragging.value || !videoRef.value) return

  const progressBar = document.querySelector('.progress-container')
  if (!progressBar) return

  const rect = progressBar.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const percent = Math.max(0, Math.min(1, clickX / rect.width))
  const newTime = percent * duration.value

  currentTime.value = newTime
}

function endDrag() {
  if (isDragging.value && videoRef.value) {
    videoRef.value.currentTime = currentTime.value
  }
  isDragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', endDrag)
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
  refreshVideos()
})
</script>

<style scoped>
.digital-human-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
}

.digital-human-wrapper.floating {
  position: fixed;
  right: var(--space-5);
  bottom: var(--space-5);
  z-index: var(--z-overlay);
  width: auto;
  height: auto;
}

.dh-panel {
  width: 100%;
  height: 100%;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.floating-panel {
  width: 420px;
  height: 580px;
  max-width: calc(100vw - 40px);
  max-height: calc(100vh - 40px);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-border);
}

.dh-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  flex-shrink: 0;
}

.dh-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
  font-size: var(--text-sm);
}

.dh-avatar {
  display: flex;
  align-items: center;
}

.dh-actions {
  display: flex;
  gap: var(--space-1);
}

.dh-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: var(--color-text-inverse);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-normal) var(--ease);
}

.dh-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.dh-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-2);
}

.dh-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  padding: var(--space-5);
}

.dh-empty-icon {
  margin-bottom: var(--space-3);
  color: var(--color-text-muted);
}

.dh-empty p {
  margin: var(--space-1) 0;
  font-size: var(--text-sm);
}

.dh-empty-hint {
  font-size: var(--text-xs) !important;
  color: var(--color-text-muted) !important;
}

.quick-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.quick-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface-3);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease), border-color var(--duration-normal) var(--ease);
}

.quick-btn:hover {
  background: var(--color-border-hover);
}

.quick-btn.primary {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
}

.quick-btn.primary:hover {
  box-shadow: var(--shadow-primary);
}

.video-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.video-list-header {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-2);
}

.video-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
}

.video-item:hover {
  background: var(--color-surface-3);
}

.video-icon {
  display: flex;
  align-items: center;
  color: var(--color-text-secondary);
}

.video-name {
  flex: 1;
  color: var(--color-text);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-size {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.url-input-section {
  padding: var(--space-4);
  background: var(--color-surface-2);
}

.url-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text);
  font-size: var(--text-xs);
  outline: none;
  box-sizing: border-box;
}

.url-input:focus {
  border-color: var(--color-primary);
}

.url-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
  justify-content: flex-end;
}

.action-btn {
  padding: var(--space-1) var(--space-4);
  border: none;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
}

.action-btn.cancel {
  background: var(--color-surface-3);
  color: var(--color-text-secondary);
}

.action-btn.cancel:hover {
  background: var(--color-border-hover);
}

.action-btn.confirm {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.video-wrapper {
  flex: 1;
  position: relative;
  background: var(--color-text);
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
  transition: opacity var(--duration-slow) var(--ease);
}

.video-wrapper:hover .video-controls-overlay {
  opacity: 1;
}

.controls-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-3);
}

.video-title {
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.close-btn {
  background: rgba(255,255,255,0.2);
  border: none;
  color: var(--color-text-inverse);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.controls-center {
  display: flex;
  justify-content: center;
  align-items: center;
}

.play-btn {
  background: rgba(255,255,255,0.2);
  border: none;
  color: var(--color-text-inverse);
  width: 48px;
  height: 48px;
  border-radius: var(--radius-full);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-normal) var(--ease);
}

.play-btn:hover {
  background: rgba(255,255,255,0.3);
}

.controls-bottom {
  padding: var(--space-2) var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.progress-container {
  flex: 1;
  height: 4px;
  background: rgba(255,255,255,0.2);
  border-radius: var(--radius-full);
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
  border-radius: var(--radius-full);
}

.progress-played {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-full);
}

.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: var(--color-text-inverse);
  border-radius: var(--radius-full);
  transform: translate(-50%, -50%);
  box-shadow: var(--shadow-sm);
}

.time-display {
  display: flex;
  gap: var(--space-1);
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  white-space: nowrap;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-text-inverse);
}

.volume-icon {
  display: flex;
  align-items: center;
  cursor: pointer;
}

.volume-slider {
  width: 60px;
  height: 4px;
  -webkit-appearance: none;
  background: rgba(255,255,255,0.3);
  border-radius: var(--radius-full);
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 10px;
  height: 10px;
  background: var(--color-text-inverse);
  border-radius: var(--radius-full);
}

.loading-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
}

.dh-input-area {
  padding: var(--space-3);
  background: var(--color-surface-2);
  flex-shrink: 0;
}

.add-video-btn {
  width: 100%;
  padding: var(--space-2);
  background: var(--color-surface-3);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
}

.add-video-btn:hover {
  background: var(--color-border-hover);
}

.dh-fab {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-full);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow-primary);
  transition: box-shadow var(--duration-slow) var(--ease);
}

.dh-fab:hover {
  box-shadow: var(--shadow-lg);
}

.fab-icon {
  display: flex;
  align-items: center;
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
</style>
