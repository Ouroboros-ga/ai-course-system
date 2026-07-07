<template>
  <div class="ppt-slide-player">
    <div class="slide-viewport">
      <LoadingSpinner v-if="isLoading" text="加载幻灯片..." />

      <div v-else-if="slides.length === 0" class="slide-empty">
        <span class="empty-icon"><FileText :size="48" /></span>
        <span>暂无课件幻灯片</span>
      </div>

      <img
        v-else
        :src="currentSlideUrl"
        :key="currentPage"
        class="slide-image"
        @error="onSlideError"
        alt="PPT幻灯片"
      />
    </div>

    <div class="slide-controls">
      <div class="page-nav">
        <button class="nav-btn" @click="prevPage" :disabled="currentPage <= 1">
          <ChevronLeft :size="16" />
        </button>
        <span class="page-indicator">
          {{ currentPage }} / {{ totalPages }}
        </span>
        <button class="nav-btn" @click="nextPage" :disabled="currentPage >= totalPages">
          <ChevronRight :size="16" />
        </button>
      </div>

      <div class="audio-player" v-if="audioUrl">
        <audio
          ref="audioRef"
          :src="audioUrlWithToken"
          @timeupdate="onTimeUpdate"
          @loadedmetadata="onLoadedMetadata"
          @ended="onAudioEnded"
          @error="onAudioError"
          preload="metadata"
        ></audio>

        <button class="audio-btn" @click="togglePlay">
          <Pause v-if="isPlaying" :size="12" />
          <Play v-else :size="12" />
        </button>

        <div class="audio-progress-wrap" @click="seekAudio" ref="progressBarRef">
          <div class="audio-progress-bg">
            <div
              class="audio-progress-fill"
              :style="{ width: audioProgress + '%' }"
            ></div>
          </div>
        </div>

        <span class="audio-time">
          {{ formatAudioTime(currentTime) }} / {{ formatAudioTime(audioDuration) }}
        </span>

        <div class="volume-wrap">
          <button class="volume-btn" @click="toggleMute">
            <VolumeX v-if="isMuted || volume === 0" :size="14" />
            <Volume1 v-else-if="volume < 0.5" :size="14" />
            <Volume2 v-else :size="14" />
          </button>
          <input
            type="range"
            class="volume-slider"
            min="0"
            max="1"
            step="0.1"
            :value="isMuted ? 0 : volume"
            @input="changeVolume"
          />
        </div>
      </div>

      <div class="audio-player audio-unavailable" v-else>
        <span class="no-audio-hint"><VolumeX :size="14" /> 当前节点暂无音频</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { FileText, Play, Pause, VolumeX, Volume1, Volume2, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const props = defineProps({
  slides: { type: Array, default: () => [] },
  totalPages: { type: Number, default: 0 },
  currentPage: { type: Number, default: 1 },
  audioUrl: { type: String, default: '' },
  audioDuration: { type: Number, default: 0 },
  autoPlay: { type: Boolean, default: false },
})

const emit = defineEmits(['page-change', 'audio-ended', 'auto-play-blocked'])

const isLoading = ref(false)
const audioRef = ref(null)
const progressBarRef = ref(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const audioDuration = ref(0)
const volume = ref(0.8)
const isMuted = ref(false)

const currentSlideUrl = computed(() => {
  if (props.slides.length === 0) return ''
  const slide = props.slides.find(s => s.page === props.currentPage)
  const baseUrl = slide ? slide.url : props.slides[0]?.url || ''
  if (!baseUrl) return ''
  const token = localStorage.getItem('token')
  const separator = baseUrl.includes('?') ? '&' : '?'
  return token ? `${baseUrl}${separator}token=${token}` : baseUrl
})

const audioUrlWithToken = computed(() => {
  if (!props.audioUrl) return ''
  const token = localStorage.getItem('token')
  const separator = props.audioUrl.includes('?') ? '&' : '?'
  return token ? `${props.audioUrl}${separator}token=${token}` : props.audioUrl
})

const audioProgress = computed(() => {
  if (audioDuration.value <= 0) return 0
  return (currentTime.value / audioDuration.value) * 100
})

function prevPage() {
  if (props.currentPage > 1) {
    emit('page-change', props.currentPage - 1)
  }
}

function nextPage() {
  if (props.currentPage < props.totalPages) {
    emit('page-change', props.currentPage + 1)
  }
}

function togglePlay() {
  if (!audioRef.value) return
  if (isPlaying.value) {
    audioRef.value.pause()
    isPlaying.value = false
  } else {
    audioRef.value.play().catch(() => {})
    isPlaying.value = true
  }
}

function onTimeUpdate() {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
  }
}

function onLoadedMetadata() {
  if (audioRef.value) {
    audioDuration.value = audioRef.value.duration
    audioRef.value.volume = volume.value
  }
}

function onAudioEnded() {
  isPlaying.value = false
  currentTime.value = 0
  emit('audio-ended')
}

function onAudioError() {
  isPlaying.value = false
}

function seekAudio(e) {
  if (!audioRef.value || audioDuration.value <= 0) return
  const rect = progressBarRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const pct = Math.max(0, Math.min(1, x / rect.width))
  audioRef.value.currentTime = pct * audioDuration.value
}

function toggleMute() {
  isMuted.value = !isMuted.value
  if (audioRef.value) {
    audioRef.value.muted = isMuted.value
  }
}

function changeVolume(e) {
  volume.value = parseFloat(e.target.value)
  if (audioRef.value) {
    audioRef.value.volume = volume.value
    if (volume.value > 0) isMuted.value = false
  }
}

function formatAudioTime(seconds) {
  if (!seconds || isNaN(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function onSlideError() {
  console.warn('幻灯片图片加载失败:', currentSlideUrl.value)
}

watch(() => props.audioUrl, (newUrl, oldUrl) => {
  if (newUrl !== oldUrl) {
    isPlaying.value = false
    currentTime.value = 0
    audioDuration.value = 0
    if (audioRef.value) {
      audioRef.value.pause()
      audioRef.value.load()
    }
    if (props.autoPlay && newUrl) {
      tryAutoPlay()
    }
  }
})

let pendingCanPlayHandler = null

function tryAutoPlay() {
  if (!audioRef.value) return
  if (pendingCanPlayHandler) {
    audioRef.value.removeEventListener('canplaythrough', pendingCanPlayHandler)
    pendingCanPlayHandler = null
  }
  const attemptPlay = () => {
    if (!audioRef.value || !props.audioUrl) return
    audioRef.value.play().then(() => {
      isPlaying.value = true
    }).catch(() => {
      isPlaying.value = false
      emit('auto-play-blocked')
    })
  }
  if (audioRef.value.readyState >= 3) {
    attemptPlay()
  } else {
    pendingCanPlayHandler = () => {
      attemptPlay()
      pendingCanPlayHandler = null
    }
    audioRef.value.addEventListener('canplaythrough', pendingCanPlayHandler)
  }
}

watch(() => props.audioDuration, (val) => {
  if (val > 0 && audioDuration.value === 0) {
    audioDuration.value = val
  }
})

onBeforeUnmount(() => {
  if (pendingCanPlayHandler && audioRef.value) {
    audioRef.value.removeEventListener('canplaythrough', pendingCanPlayHandler)
    pendingCanPlayHandler = null
  }
  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.src = ''
  }
})

defineExpose({
  playAudio: tryAutoPlay,
})
</script>

<style scoped>
.ppt-slide-player {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-text);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.slide-viewport {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-text);
  overflow: hidden;
  position: relative;
  min-height: 0;
}

.slide-loading,
.slide-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.empty-icon { color: var(--color-text-muted); }

.slide-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  user-select: none;
}

.slide-controls {
  background: var(--color-text);
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  border-top: 1px solid var(--color-border);
}

.page-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
}

.nav-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: var(--color-text);
  color: var(--color-border);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-normal) var(--ease), border-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}

.nav-btn:hover:not(:disabled) {
  background: var(--color-border);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.page-indicator {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: 500;
  min-width: 60px;
  text-align: center;
}

.audio-player {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.audio-unavailable {
  justify-content: center;
  padding: var(--space-1) 0;
}

.no-audio-hint {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.audio-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--color-primary);
  color: var(--color-text-inverse);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background var(--duration-normal) var(--ease);
}

.audio-btn:hover {
  background: var(--color-secondary);
}

.audio-progress-wrap {
  flex: 1;
  height: 20px;
  display: flex;
  align-items: center;
  cursor: pointer;
}

.audio-progress-bg {
  width: 100%;
  height: 4px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.audio-progress-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-full);
  transition: width 0.1s linear;
}

.audio-time {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  min-width: 72px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  font-family: var(--font-mono);
}

.volume-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}

.volume-btn {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  transition: color var(--duration-normal) var(--ease);
}

.volume-btn:hover {
  color: var(--color-primary);
}

.volume-slider {
  width: 48px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--color-border);
  border-radius: var(--radius-full);
  outline: none;
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 10px;
  height: 10px;
  border-radius: var(--radius-full);
  background: var(--color-secondary);
  cursor: pointer;
}

.volume-slider::-moz-range-thumb {
  width: 10px;
  height: 10px;
  border-radius: var(--radius-full);
  background: var(--color-secondary);
  cursor: pointer;
  border: none;
}
</style>
