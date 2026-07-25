<template>
  <div class="split-video-player">
    <!-- 加载状态 -->
    <LoadingSpinner v-if="loading" text="正在加载课程数据..." full-page />

    <!-- 错误状态 -->
    <div v-else-if="error" class="player-error">
      <div class="error-icon"><AlertTriangle :size="48" /></div>
      <p>{{ error }}</p>
      <button @click="initPlayer" class="retry-btn">重试</button>
    </div>

    <!-- 播放器主体 -->
    <div v-else class="player-container">
      <!-- 顶部标题栏 -->
      <div class="player-header">
        <h2 class="course-title">{{ playerData.course_title }}</h2>
        <div class="header-info">
          <span class="total-duration">总时长: {{ formatDuration(playerData.total_duration) }}</span>
          <span class="progress-text">进度: {{ completionRate }}%</span>
        </div>
      </div>

      <!-- 分屏区域 -->
      <div class="split-screen">
        <!-- 左侧：数字人视频 (40%) -->
        <div class="video-section">
          <video
            ref="videoRef"
            class="digital-human-video"
            :src="currentVideoUrl"
            @timeupdate="onTimeUpdate"
            @loadedmetadata="onLoadedMetadata"
            @ended="onVideoEnded"
            @play="onPlay"
            @pause="onPause"
            preload="auto"
          ></video>

          <!-- 视频覆盖层控制按钮 -->
          <div class="video-overlay" v-show="!isPlaying && !isLoadingVideo">
            <button @click="togglePlay" class="play-btn-large"><Play :size="32" /></button>
          </div>

          <!-- 视频加载指示器 -->
          <div v-if="isLoadingVideo" class="video-loading">
            <div class="loading-spinner-small"></div>
          </div>
          <div v-if="activeTimelineCue?.subtitle_text" class="timeline-subtitle" aria-live="polite">
            {{ activeTimelineCue.subtitle_text }}
          </div>
        </div>

        <!-- 右侧：PPT幻灯片 (60%) -->
        <div class="ppt-section">
          <div class="ppt-container">
            <!-- PPT图片展示（优先使用PDF渲染的图片） -->
            <div v-if="currentSlideImages.length > 0" class="ppt-image-viewer">
              <div class="slide-image-wrapper">
                <img
                  :src="currentSlideImages[currentSlideImageIndex]?.url"
                  :alt="'幻灯片 ' + currentSlideImages[currentSlideImageIndex]?.page"
                  class="slide-image"
                  @error="onSlideImageError"
                />
              </div>
              <!-- 多页时显示翻页控制 -->
              <div v-if="currentSlideImages.length > 1" class="slide-nav">
                <button
                  class="slide-nav-btn"
                  :disabled="currentSlideImageIndex <= 0"
                  @click="currentSlideImageIndex--"
                ><ChevronLeft :size="18" /></button>
                <span class="slide-page-info">
                  {{ currentSlideImageIndex + 1 }} / {{ currentSlideImages.length }}
                </span>
                <button
                  class="slide-nav-btn"
                  :disabled="currentSlideImageIndex >= currentSlideImages.length - 1"
                  @click="currentSlideImageIndex++"
                ><ChevronRight :size="18" /></button>
              </div>
            </div>

            <!-- 回退：PPT文本内容展示 -->
            <div v-else-if="currentPageData" class="ppt-content">
              <h3 class="ppt-title">{{ currentPageData.title || currentKnowledgePoint?.title }}</h3>
              <div class="ppt-body" v-html="formatContent(currentPageData.content)"></div>
            </div>

            <!-- 无内容占位 -->
            <div v-else class="ppt-placeholder">
              <div class="placeholder-icon"><BarChart3 :size="64" /></div>
              <p>等待视频播放...</p>
              <p class="hint">PPT将根据视频进度自动同步显示</p>
            </div>
          </div>

          <!-- PPT页码指示器 -->
          <div class="ppt-page-indicator" v-if="currentSlideImages.length > 0 || currentPageData">
            <template v-if="currentSlideImages.length > 0">
              第 {{ currentSlideImages[currentSlideImageIndex]?.page || '-' }} 页
              <span v-if="currentSlideImages.length > 1">
                (共 {{ currentSlideImages.length }} 页)
              </span>
            </template>
            <template v-else>
              第 {{ currentPage }} / {{ totalPages }} 页
            </template>
          </div>
        </div>
      </div>

      <!-- 知识点导航条 -->
      <KnowledgeNavBar
        :knowledge-points="knowledgePoints"
        :current-node-index="currentNodeIndex"
        :current-timestamp="currentTime"
        @jump-to-knowledge="jumpToKnowledgePoint"
      />

      <!-- 播放控制栏 -->
      <div class="control-bar">
        <!-- 播放/暂停 -->
        <button @click="togglePlay" class="ctrl-btn" :title="isPlaying ? '暂停' : '播放'">
          <Pause v-if="isPlaying" :size="20" />
          <Play v-else :size="20" />
        </button>

        <!-- 进度条 -->
        <div class="progress-bar-container">
          <input
            type="range"
            class="progress-bar"
            min="0"
            :max="duration"
            step="0.1"
            v-model.number="currentTime"
            @input="seekTo"
          />
          <div class="time-display">
            <span>{{ formatDuration(currentTime) }}</span>
            <span>/</span>
            <span>{{ formatDuration(duration) }}</span>
          </div>
        </div>

        <!-- 倍速控制 -->
        <div class="speed-control">
          <select v-model.number="playbackRate" @change="changeSpeed" class="speed-select">
            <option :value="0.5">0.5x</option>
            <option :value="0.75">0.75x</option>
            <option :value="1.0">1.0x</option>
            <option :value="1.25">1.25x</option>
            <option :value="1.5">1.5x</option>
            <option :value="2.0">2.0x</option>
          </select>
        </div>

        <!-- 音量控制 -->
        <div class="volume-control">
          <button @click="toggleMute" class="ctrl-btn" :title="isMuted ? '取消静音' : '静音'">
            <VolumeX v-if="isMuted" :size="20" />
            <Volume2 v-else :size="20" />
          </button>
          <input
            type="range"
            class="volume-slider"
            min="0"
            max="1"
            step="0.1"
            v-model.number="volume"
            @input="changeVolume"
          />
        </div>

        <!-- 全屏按钮 -->
        <button @click="toggleFullscreen" class="ctrl-btn" title="全屏">
          <Maximize :size="20" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { Play, Pause, VolumeX, Volume2, Maximize, AlertTriangle, BarChart3, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { getCourseMediaTimeline, getPlayerInitData, savePlayerProgress } from '@/api/player.js'
import KnowledgeNavBar from './KnowledgeNavBar.vue'

const props = defineProps({
  courseId: {
    type: Number,
    required: true,
  },
})

const emit = defineEmits(['progress-update', 'node-change', 'error'])

const route = useRoute()

// 状态变量
const loading = ref(true)
const error = ref(null)
const videoRef = ref(null)
const playerData = ref({
  course_id: 0,
  course_title: '',
  script_id: 0,
  total_duration: 0,
  total_nodes: 0,
  nodes: [],
  video_base_url: '',
  ppt_pages: [],
  slide_images: [],
  saved_progress: null,
})

// 播放状态
const isPlaying = ref(false)
const isLoadingVideo = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const playbackRate = ref(1.0)
const volume = ref(1.0)
const isMuted = ref(false)

// 当前节点和PPT状态
const currentNodeIndex = ref(0)
const currentPage = ref(1)
const totalPages = ref(1)
const completedNodes = ref([])
const currentSlideImageIndex = ref(0)
const timelineCues = ref([])

// 自动保存定时器
let autoSaveTimer = null

watch(currentNodeIndex, () => {
  if (hasAccuratePageMapping.value) {
    currentSlideImageIndex.value = 0
  } else {
    currentSlideImageIndex.value = autoSlideIndex.value
  }
})

// 计算属性
const knowledgePoints = computed(() => {
  return playerData.value.nodes.map(node => ({
    node_id: node.id,
    chapter_id: node.chapter_id,
    title: node.title,
    timestamp_start: node.timestamp_start,
    timestamp_end: node.timestamp_end,
    node_index: node.node_index,
    is_completed: completedNodes.value.includes(node.id),
  }))
})

const currentVideoUrl = computed(() => {
  if (activeTimelineCue.value?.video_url) return withAccessToken(activeTimelineCue.value.video_url)
  // 根据当前时间找到对应的节点视频URL
  const currentNode = findNodeByTime(currentTime.value)
  return currentNode?.video_url || ''
})

const activeTimelineCue = computed(() => {
  const node = findNodeByTime(currentTime.value)
  if (!node) return null
  const localTime = Math.max(0, currentTime.value - (node.timestamp_start || 0))
  return timelineCues.value.find(cue =>
    cue.node_id === node.id && localTime >= cue.start_time && localTime <= cue.end_time,
  ) || null
})

const activePptPage = computed(() => activeTimelineCue.value?.ppt_page || null)

const currentKnowledgePoint = computed(() => {
  if (currentNodeIndex.value >= 0 && currentNodeIndex.value < knowledgePoints.value.length) {
    return knowledgePoints.value[currentNodeIndex.value]
  }
  return null
})

const hasAccuratePageMapping = computed(() => {
  const nodes = playerData.value.nodes
  if (!nodes || nodes.length === 0) return false
  return nodes.some(n => (n.page_start || 1) > 1 || (n.page_end || 1) > 1 || (n.page_start || 1) !== (n.page_end || 1))
})

const currentSlideImages = computed(() => {
  const currentNode = playerData.value.nodes[currentNodeIndex.value]
  if (!currentNode || !playerData.value.slide_images || playerData.value.slide_images.length === 0) {
    return []
  }
  const addToken = (s) => ({ ...s, url: withAccessToken(s.url) })

  if (activePptPage.value) {
    return playerData.value.slide_images
      .filter(s => s.page === activePptPage.value)
      .map(addToken)
  }

  if (hasAccuratePageMapping.value) {
    const pageStart = activePptPage.value || currentNode.page_start || 1
    const pageEnd = activePptPage.value || currentNode.page_end || pageStart
    return playerData.value.slide_images
      .filter(s => s.page >= pageStart && s.page <= pageEnd)
      .map(addToken)
  }

  return playerData.value.slide_images.map(addToken)
})

const autoSlideIndex = computed(() => {
  if (hasAccuratePageMapping.value) return 0
  const nodes = playerData.value.nodes
  const totalSlides = playerData.value.slide_images?.length || 1
  if (nodes.length === 0 || totalSlides <= 1) return 0
  const ratio = currentNodeIndex.value / nodes.length
  return Math.min(Math.floor(ratio * totalSlides), totalSlides - 1)
})

const currentPageData = computed(() => {
  // 根据当前节点获取PPT内容（优先使用真实PPT页面数据）
  const currentNode = playerData.value.nodes[currentNodeIndex.value]
  if (currentNode) {
    const pageStart = currentNode.page_start || 1
    const pageEnd = currentNode.page_end || pageStart

    // 如果有真实的PPT页面数据，优先使用
    if (playerData.value.ppt_pages && playerData.value.ppt_pages.length > 0) {
      // 查找当前页码范围内的PPT页面
      const pptPage = playerData.value.ppt_pages.find(
        p => p.page_no >= pageStart && p.page_no <= pageEnd
      )
      if (pptPage) {
        return {
          title: pptPage.title || currentNode.title,
          content: pptPage.text || pptPage.content || '',
          page_start: pageStart,
          page_end: pageEnd,
          is_real_ppt: true,
        }
      }

      // 如果没找到精确匹配，尝试查找最接近的页面
      const closestPage = playerData.value.ppt_pages.find(
        p => p.page_no === pageStart
      )
      if (closestPage) {
        return {
          title: closestPage.title || currentNode.title,
          content: closestPage.text || closestPage.content || '',
          page_start: pageStart,
          page_end: pageEnd,
          is_real_ppt: true,
        }
      }
    }

    // 回退到节点内容（讲解文本）
    return {
      title: currentNode.title,
      content: currentNode.content,
      page_start: pageStart,
      page_end: pageEnd,
      is_real_ppt: false,
    }
  }
  return null
})

const completionRate = computed(() => {
  if (playerData.value.saved_progress) {
    return Math.round(playerData.value.saved_progress.completion_rate * 100)
  }
  if (playerData.value.total_nodes > 0) {
    return Math.round((completedNodes.value.length / playerData.value.total_nodes) * 100)
  }
  return 0
})

function withAccessToken(url) {
  if (!url) return ''
  const token = localStorage.getItem('token') || ''
  if (!token || url.includes('token=')) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

// 初始化播放器
async function initPlayer() {
  loading.value = true
  error.value = null

  try {
    const courseId = props.courseId || parseInt(route.params.courseId)
    if (!courseId) {
      throw new Error('缺少课程ID')
    }

    console.log('[SplitVideoPlayer] 初始化播放器, courseId:', courseId)

    // 获取播放器初始化数据
    const response = await getPlayerInitData(courseId)

    if (response && response.data) {
      playerData.value = response.data
      try {
        timelineCues.value = await getCourseMediaTimeline(courseId)
      } catch (timelineError) {
        timelineCues.value = []
        console.warn('[SplitVideoPlayer] media timeline unavailable; using node timing', timelineError)
      }

      // 计算总页数（优先使用真实PPT数据）
      if (playerData.value.ppt_pages && playerData.value.ppt_pages.length > 0) {
        totalPages.value = playerData.value.ppt_pages.length
        console.log(`[SplitVideoPlayer] 使用真实PPT数据，共 ${totalPages.value} 页`)
      } else if (playerData.value.nodes.length > 0) {
        const lastNode = playerData.value.nodes[playerData.value.nodes.length - 1]
        totalPages.value = lastNode.page_end || 1
        console.log(`[SplitVideoPlayer] 使用节点页码估算，共 ${totalPages.value} 页`)
      }

      // 恢复断点续播位置
      if (response.data.saved_progress) {
        currentTime.value = response.data.saved_progress.current_timestamp || 0
        currentPage.value = response.data.saved_progress.current_page || 1
        currentNodeIndex.value = response.data.saved_progress.current_node_index || 0

        console.log('[SplitVideoPlayer] 恢复断点:', {
          timestamp: currentTime.value,
          page: currentPage.value,
          nodeIndex: currentNodeIndex.value,
        })
      }

      // 初始化幻灯片位置
      if (playerData.value.slide_images && playerData.value.slide_images.length > 0) {
        currentSlideImageIndex.value = autoSlideIndex.value
      }

      console.log('[SplitVideoPlayer] 数据加载完成:', {
        totalNodes: playerData.value.total_nodes,
        duration: playerData.value.total_duration,
        hasProgress: !!response.data.saved_progress,
      })

      loading.value = false
    } else {
      throw new Error('无效的响应数据')
    }

  } catch (err) {
    console.error('[SplitVideoPlayer] 初始化失败:', err)
    error.value = err.message || '加载失败，请重试'
    loading.value = false
    emit('error', err)
  }
}

// 根据时间戳查找当前节点（二分查找优化）
function findNodeByTime(timestamp) {
  const nodes = playerData.value.nodes
  if (!nodes || nodes.length === 0) return null

  let left = 0
  let right = nodes.length - 1

  while (left <= right) {
    const mid = Math.floor((left + right) / 2)
    const node = nodes[mid]

    if (timestamp >= node.timestamp_start && timestamp <= node.timestamp_end) {
      return node
    } else if (timestamp < node.timestamp_start) {
      right = mid - 1
    } else {
      left = mid + 1
    }
  }

  // 如果没找到精确匹配，返回最接近的节点
  if (left < nodes.length) return nodes[left]
  if (right >= 0) return nodes[right]
  return null
}

// 视频事件处理
function onTimeUpdate(event) {
  currentTime.value = event.target.currentTime
  const newNode = findNodeByTime(currentTime.value)

  if (newNode) {
    const newIndex = newNode.node_index - 1  // node_index从1开始

    // 节点变化时更新UI
    if (newIndex !== currentNodeIndex.value) {
      const oldIndex = currentNodeIndex.value
      currentNodeIndex.value = newIndex
      currentPage.value = newNode.page_start

      // 标记旧节点为已完成
      if (oldIndex >= 0 && !completedNodes.value.includes(playerData.value.nodes[oldIndex]?.id)) {
        completedNodes.value.push(playerData.value.nodes[oldIndex].id)
      }

      emit('node-change', {
        oldIndex,
        newIndex,
        nodeId: newNode.id,
        title: newNode.title,
      })

      console.log(`[SplitVideoPlayer] 节点切换: ${oldIndex} → ${newIndex} (${newNode.title})`)
    }
    if (activePptPage.value) {
      currentPage.value = activePptPage.value
      currentSlideImageIndex.value = 0
    }
  }
}

function onLoadedMetadata(event) {
  duration.value = event.target.duration || playerData.value.total_duration
  console.log('[SplitVideoPlayer] 视频元数据加载, 时长:', duration.value)
}

function onVideoEnded() {
  isPlaying.value = false
  console.log('[SplitVideoPlayer] 视频播放结束')

  // 标记最后一个节点为完成
  const lastNode = playerData.value.nodes[playerData.value.nodes.length - 1]
  if (lastNode && !completedNodes.value.includes(lastNode.id)) {
    completedNodes.value.push(lastNode.id)
  }

  // 立即保存最终进度
  saveProgress()
}

function onPlay() {
  isPlaying.value = true
  startAutoSave()
}

function onPause() {
  isPlaying.value = false
  stopAutoSave()
  saveProgress()  // 暂停时立即保存
}

// 播放控制函数
function togglePlay() {
  if (!videoRef.value) return

  if (isPlaying.value) {
    videoRef.value.pause()
  } else {
    videoRef.value.play().catch(err => {
      console.error('播放失败:', err)
    })
  }
}

function seekTo() {
  if (!videoRef.value) return
  videoRef.value.currentTime = currentTime.value
}

function changeSpeed() {
  if (!videoRef.value) return
  videoRef.value.playbackRate = playbackRate.value
  console.log('[SplitVideoPlayer] 倍速切换:', playbackRate.value)
}

function changeVolume() {
  if (!videoRef.value) return
  videoRef.value.volume = volume.value
  isMuted.value = volume.value === 0
}

function toggleMute() {
  if (!videoRef.value) return
  isMuted.value = !isMuted.value
  videoRef.value.muted = isMuted.value
}

function toggleFullscreen() {
  const container = document.querySelector('.split-video-player')
  if (container.requestFullscreen) {
    container.requestFullscreen()
  } else if (container.webkitRequestFullscreen) {
    container.webkitRequestFullscreen()
  }
}

function onSlideImageError(e) {
  e.target.style.display = 'none'
}

// 知识点跳转
function jumpToKnowledgePoint(knowledgePoint) {
  if (!videoRef.value || !knowledgePoint) return

  console.log('[SplitVideoPlayer] 跳转到知识点:', knowledgePoint.title)

  // 跳转到对应时间戳
  currentTime.value = knowledgePoint.timestamp_start
  videoRef.value.currentTime = knowledgePoint.timestamp_start

  // 更新当前节点索引
  currentNodeIndex.value = knowledgePoint.node_index - 1
  currentPage.value = playerData.value.nodes[currentNodeIndex.value]?.page_start || 1

  // 自动播放
  if (!isPlaying.value) {
    togglePlay()
  }
}

// 进度保存
async function saveProgress() {
  try {
    await savePlayerProgress({
      courseId: playerData.value.course_id,
      currentNodeId: playerData.value.nodes[currentNodeIndex.value]?.id,
      currentTimestamp: currentTime.value,
      currentPage: currentPage.value,
      completedNodes: completedNodes.value,
    })

    emit('progress-update', {
      timestamp: currentTime.value,
      page: currentPage.value,
      nodeIndex: currentNodeIndex.value,
      completionRate: completionRate.value,
    })
  } catch (err) {
    console.error('[SplitVideoPlayer] 保存进度失败:', err)
  }
}

// 自动保存（每10秒）
function startAutoSave() {
  stopAutoSave()
  autoSaveTimer = setInterval(() => {
    saveProgress()
  }, 10000)  // 10秒保存一次
}

function stopAutoSave() {
  if (autoSaveTimer) {
    clearInterval(autoSaveTimer)
    autoSaveTimer = null
  }
}

// 工具函数
function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return '00:00'

  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)

  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function formatContent(content) {
  if (!content) return ''

  // 简单的文本格式化，支持换行
  return content
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
}

// 生命周期
onMounted(() => {
  console.log('[SplitVideoPlayer] 组件挂载, courseId:', props.courseId)
  initPlayer()
})

onUnmounted(() => {
  // 组件卸载时保存进度并清理定时器
  stopAutoSave()
  if (isPlaying.value || currentTime.value > 0) {
    saveProgress()
  }
  console.log('[SplitVideoPlayer] 组件卸载，已保存进度')
})
</script>

<style scoped>
.split-video-player {
  width: 100%;
  height: 100vh;
  background: var(--color-text);
  color: var(--color-text-inverse);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 加载状态 */
.player-loading,
.player-error {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-5);
}

.error-icon {
  color: var(--color-danger);
}

.retry-btn {
  padding: var(--space-3) var(--space-8);
  background: var(--color-success);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-base);
  transition: background var(--duration-normal) var(--ease);
}

.retry-btn:hover {
  background: var(--color-success-hover);
}

/* 顶部标题栏 */
.player-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  background: var(--color-text);
  border-bottom: 1px solid var(--color-border);
}

.course-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}

.header-info {
  display: flex;
  gap: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 分屏区域 */
.split-screen {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左侧视频区域 */
.video-section {
  width: 40%;
  position: relative;
  background: var(--color-text);
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 2px solid var(--color-border);
}

.digital-human-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.video-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.3);
  cursor: pointer;
  transition: background var(--duration-slow) var(--ease);
}

.video-overlay:hover {
  background: rgba(0, 0, 0, 0.5);
}

.play-btn-large {
  width: 80px;
  height: 80px;
  border-radius: var(--radius-full);
  background: var(--color-success);
  color: var(--color-text-inverse);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-slow) var(--ease);
}

.play-btn-large:hover {
  background: var(--color-success-hover);
}

.video-loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

.timeline-subtitle {
  position: absolute;
  right: var(--space-4);
  bottom: var(--space-4);
  left: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: rgb(0 0 0 / 72%);
  color: #fff;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  text-align: center;
}

.loading-spinner-small {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-success);
  border-radius: var(--radius-full);
  animation: spin 1s linear infinite;
}

/* 右侧PPT区域 */
.ppt-section {
  width: 60%;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-2);
  color: var(--color-text);
}

.ppt-container {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
}

.ppt-image-viewer {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.slide-image-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  width: 100%;
}

.slide-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
}

.slide-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.slide-nav-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  transition: background var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}

.slide-nav-btn:hover:not(:disabled) {
  background: var(--color-success);
  color: var(--color-text-inverse);
  border-color: var(--color-success);
}

.slide-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.slide-page-info {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  min-width: 60px;
  text-align: center;
}

.ppt-content {
  height: 100%;
}

.ppt-title {
  font-size: var(--text-xl);
  font-weight: bold;
  margin-bottom: var(--space-5);
  color: var(--color-text);
  border-bottom: 2px solid var(--color-success);
  padding-bottom: var(--space-2);
}

.ppt-body {
  font-size: var(--text-base);
  line-height: 1.8;
  color: var(--color-text-secondary);
}

.ppt-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  color: var(--color-text-muted);
}

.placeholder-icon {
  color: var(--color-text-muted);
}

.hint {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.ppt-page-indicator {
  padding: var(--space-2) var(--space-5);
  background: var(--color-surface-3);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  border-top: 1px solid var(--color-border);
}

/* 控制栏 */
.control-bar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: var(--color-text);
  border-top: 1px solid var(--color-border);
}

.ctrl-btn {
  background: transparent;
  color: var(--color-text-inverse);
  border: none;
  cursor: pointer;
  padding: var(--space-2);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--duration-normal) var(--ease);
}

.ctrl-btn:hover {
  color: var(--color-success);
}

.progress-bar-container {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.progress-bar {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--color-border);
  outline: none;
  border-radius: var(--radius-full);
  cursor: pointer;
}

.progress-bar::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  background: var(--color-success);
  cursor: pointer;
  border-radius: var(--radius-full);
}

.progress-bar::-moz-range-thumb {
  width: 16px;
  height: 16px;
  background: var(--color-success);
  cursor: pointer;
  border-radius: var(--radius-full);
  border: none;
}

.time-display {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  min-width: 90px;
  font-family: var(--font-mono);
}

.speed-control select {
  background: var(--color-border);
  color: var(--color-text-inverse);
  border: 1px solid var(--color-border-hover);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-sm);
}

.volume-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.volume-slider {
  width: 80px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--color-border);
  outline: none;
  border-radius: var(--radius-full);
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  background: var(--color-success);
  cursor: pointer;
  border-radius: var(--radius-full);
}

.volume-slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  background: var(--color-success);
  cursor: pointer;
  border-radius: var(--radius-full);
  border: none;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
