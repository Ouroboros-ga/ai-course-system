<template>
  <main
    ref="stageRef"
    class="sl-stage"
    :class="'is-' + mode"
    tabindex="-1"
  >
    <section class="sl-learning-canvas" aria-label="课程学习内容">
      <article class="sl-video-pane" :class="{ 'has-error': localMediaError }">
        <header class="sl-pane-label">
          <span><MonitorPlay :size="16" /> 数字人讲解</span>
          <small v-if="currentNode?.mediaStatus !== 'ready'">当前节点无可用视频</small>
        </header>

        <div class="sl-video-frame">
          <video
            ref="videoRef"
            :src="currentVideoUrl || undefined"
            preload="metadata"
            playsinline
            @loadedmetadata="handleLoadedMetadata"
            @timeupdate="handleTimeUpdate"
            @play="emitPlaybackState(true)"
            @pause="emitPlaybackState(false)"
            @ended="handleEnded"
            @error="handleMediaError"
          ></video>

          <div v-if="!currentVideoUrl || localMediaError" class="sl-media-fallback">
            <VideoOff :size="34" />
            <strong>{{ localMediaError ? '讲解视频暂时无法播放' : '当前知识点暂无数字人视频' }}</strong>
            <p>PPT 与讲解文本仍可正常阅读，不影响自主研习。</p>
            <button v-if="localMediaError" type="button" @click="retryMedia">重新加载视频</button>
          </div>

          <button
            v-else-if="!isPlaying"
            type="button"
            class="sl-large-play"
            aria-label="播放讲解"
            @click="togglePlay"
          >
            <Play :size="28" fill="currentColor" />
          </button>

          <p v-if="captionsEnabled && currentNode?.content" class="sl-caption" aria-live="off">
            {{ captionText }}
          </p>
        </div>
      </article>

      <article class="sl-ppt-pane">
        <header class="sl-pane-label">
          <span><Presentation :size="16" /> 同步课件</span>
          <small>第 {{ currentPage }} / {{ totalPages }} 页</small>
        </header>

        <div class="sl-slide-frame">
          <img
            v-if="currentSlide && !slideError"
            :key="currentSlide.url"
            :src="currentSlide.url"
            :alt="'课程课件第 ' + currentPage + ' 页'"
            @error="slideError = true"
          />
          <div v-else-if="currentPptPage?.content || currentNode?.content" class="sl-slide-text">
            <span>第 {{ currentPage }} 页</span>
            <h2>{{ currentPptPage?.title || currentNode?.title }}</h2>
            <p>{{ currentPptPage?.content || currentNode?.content }}</p>
          </div>
          <div v-else class="sl-media-fallback sl-media-fallback--light">
            <FileQuestion :size="34" />
            <strong>当前页暂无可显示的课件</strong>
            <p>可从左侧目录切换其他知识点。</p>
          </div>
        </div>

        <nav class="sl-slide-nav" aria-label="课件翻页">
          <button
            type="button"
            class="sl-icon-button"
            :disabled="currentPage <= 1"
            aria-label="上一页课件"
            @click="$emit('page-change', currentPage - 1)"
          >
            <ChevronLeft :size="19" />
          </button>
          <span>第 {{ currentPage }} 页</span>
          <button
            type="button"
            class="sl-icon-button"
            :disabled="currentPage >= totalPages"
            aria-label="下一页课件"
            @click="$emit('page-change', currentPage + 1)"
          >
            <ChevronRight :size="19" />
          </button>
        </nav>
      </article>
    </section>

    <footer class="sl-playback-controls" aria-label="播放控制">
      <button
        type="button"
        class="sl-icon-button sl-control-primary"
        :disabled="!currentVideoUrl"
        :aria-label="isPlaying ? '暂停讲解' : '播放讲解'"
        @click="togglePlay"
      >
        <Pause v-if="isPlaying" :size="19" fill="currentColor" />
        <Play v-else :size="19" fill="currentColor" />
      </button>

      <span class="sl-time">{{ formatTime(currentTime) }}</span>
      <label class="sl-seek">
        <span class="sl-visually-hidden">课程播放进度</span>
        <input
          type="range"
          min="0"
          :max="Math.max(totalDuration, 1)"
          step="0.1"
          :value="currentTime"
          @input="handleSeek"
        />
      </label>
      <span class="sl-time">{{ formatTime(totalDuration) }}</span>

      <select
        :value="playbackRate"
        aria-label="播放速度"
        @change="$emit('rate-change', Number($event.target.value))"
      >
        <option :value="0.75">0.75×</option>
        <option :value="1">1.0×</option>
        <option :value="1.25">1.25×</option>
        <option :value="1.5">1.5×</option>
        <option :value="2">2.0×</option>
      </select>

      <button
        type="button"
        class="sl-icon-button"
        :aria-pressed="captionsEnabled"
        aria-label="切换字幕"
        @click="$emit('captions-change', !captionsEnabled)"
      >
        <Captions :size="19" />
      </button>

      <button
        type="button"
        class="sl-icon-button sl-volume-button"
        :aria-label="isMuted ? '取消静音' : '静音'"
        @click="$emit('mute-change', !isMuted)"
      >
        <VolumeX v-if="isMuted || volume === 0" :size="19" />
        <Volume2 v-else :size="19" />
      </button>
      <label class="sl-volume">
        <span class="sl-visually-hidden">音量</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          :value="isMuted ? 0 : volume"
          @input="$emit('volume-change', Number($event.target.value))"
        />
      </label>

      <button type="button" class="sl-icon-button" aria-label="全屏学习" @click="toggleFullscreen">
        <Maximize2 :size="19" />
      </button>
    </footer>
  </main>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Captions,
  ChevronLeft,
  ChevronRight,
  FileQuestion,
  Maximize2,
  MonitorPlay,
  Pause,
  Play,
  Presentation,
  VideoOff,
  Volume2,
  VolumeX,
} from 'lucide-vue-next'

const props = defineProps({
  mode: { type: String, required: true },
  currentNode: { type: Object, default: null },
  currentTime: { type: Number, default: 0 },
  currentPage: { type: Number, default: 1 },
  currentSlide: { type: Object, default: null },
  currentPptPage: { type: Object, default: null },
  currentVideoUrl: { type: String, default: '' },
  totalPages: { type: Number, default: 1 },
  totalDuration: { type: Number, default: 0 },
  isPlaying: { type: Boolean, default: false },
  playbackRate: { type: Number, default: 1 },
  volume: { type: Number, default: 0.85 },
  isMuted: { type: Boolean, default: false },
  captionsEnabled: { type: Boolean, default: true },
})

const emit = defineEmits([
  'update-playback',
  'seek',
  'page-change',
  'rate-change',
  'volume-change',
  'mute-change',
  'captions-change',
  'media-error',
])

const stageRef = ref(null)
const videoRef = ref(null)
const localMediaError = ref('')
const slideError = ref(false)
let applyingExternalTime = false

const captionText = computed(() => {
  return String(props.currentNode?.content || '')
    .replace(/[#*_>]/g, '')
    .replace(/s+/g, ' ')
    .trim()
    .slice(0, 220)
})

function localTimeForGlobal(globalTime) {
  return Math.max(0, Number(globalTime) - Number(props.currentNode?.timestampStart || 0))
}

function syncVideoSettings() {
  if (!videoRef.value) return
  videoRef.value.playbackRate = props.playbackRate
  videoRef.value.volume = props.volume
  videoRef.value.muted = props.isMuted
}

async function handleLoadedMetadata() {
  if (!videoRef.value) return
  syncVideoSettings()
  applyingExternalTime = true
  const target = localTimeForGlobal(props.currentTime)
  videoRef.value.currentTime = Math.min(target, videoRef.value.duration || target)
  applyingExternalTime = false
  localMediaError.value = ''
  if (props.isPlaying) {
    await videoRef.value.play().catch(() => emitPlaybackState(false))
  }
}

function handleTimeUpdate() {
  if (!videoRef.value || applyingExternalTime) return
  emit('update-playback', {
    globalTime: Number(props.currentNode?.timestampStart || 0) + videoRef.value.currentTime,
    isPlaying: !videoRef.value.paused,
  })
}

function emitPlaybackState(value) {
  emit('update-playback', {
    globalTime: props.currentTime,
    isPlaying: value,
  })
}

function togglePlay() {
  if (!videoRef.value || !props.currentVideoUrl) return
  if (videoRef.value.paused) {
    videoRef.value.play().catch(handleMediaError)
  } else {
    videoRef.value.pause()
  }
}

function handleSeek(event) {
  const nextTime = Number(event.target.value)
  emit('seek', nextTime)
}

function handleEnded() {
  emit('update-playback', {
    globalTime: props.currentNode?.timestampEnd ?? props.currentTime,
    isPlaying: false,
  })
}

function handleMediaError() {
  localMediaError.value = '媒体资源加载失败'
  emit('media-error', localMediaError.value)
}

function retryMedia() {
  localMediaError.value = ''
  if (!videoRef.value) return
  videoRef.value.load()
}

async function toggleFullscreen() {
  const target = stageRef.value
  if (!target) return
  if (document.fullscreenElement) {
    await document.exitFullscreen?.()
  } else {
    await target.requestFullscreen?.()
  }
}

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const remain = Math.floor(value % 60)
  if (hours > 0) {
    return hours + ':' + String(minutes).padStart(2, '0') + ':' + String(remain).padStart(2, '0')
  }
  return minutes + ':' + String(remain).padStart(2, '0')
}

watch(
  () => props.currentVideoUrl,
  async () => {
    localMediaError.value = ''
    await nextTick()
    videoRef.value?.load()
  }
)

watch(
  () => props.currentSlide?.url,
  () => {
    slideError.value = false
  }
)

watch(
  () => props.currentTime,
  value => {
    if (!videoRef.value || !props.currentVideoUrl || videoRef.value.readyState < 1) return
    const target = localTimeForGlobal(value)
    if (Math.abs(videoRef.value.currentTime - target) > 1.25) {
      applyingExternalTime = true
      videoRef.value.currentTime = Math.min(target, videoRef.value.duration || target)
      applyingExternalTime = false
    }
  }
)

watch(() => props.playbackRate, syncVideoSettings)
watch(() => props.volume, syncVideoSettings)
watch(() => props.isMuted, syncVideoSettings)
</script>