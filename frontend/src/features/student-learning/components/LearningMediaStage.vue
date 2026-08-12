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
          <audio
            v-if="hasAudio"
            ref="audioRef"
            :key="activeAudioClock.generation"
            :src="activeAudioUrl"
            :data-media-generation="activeAudioClock.generation"
            preload="metadata"
            class="sl-stage-clock"
            @loadedmetadata="handleLoadedMetadata"
            @timeupdate="handleTimeUpdate"
            @play="emitPlaybackState(true, $event.currentTarget)"
            @pause="emitPlaybackState(false, $event.currentTarget)"
            @ended="handleEnded"
            @error="handleMediaError"
          />
          <video
            v-else
            ref="videoRef"
            :src="currentVideoUrl || undefined"
            :data-media-generation="mediaGeneration"
            preload="metadata"
            playsinline
            @loadedmetadata="handleLoadedMetadata"
            @timeupdate="handleTimeUpdate"
            @play="emitPlaybackState(true, $event.currentTarget)"
            @pause="emitPlaybackState(false, $event.currentTarget)"
            @ended="handleEnded"
            @error="handleMediaError"
          ></video>

          <div v-if="!currentVideoUrl || hasAudio || localMediaError" class="sl-media-fallback">
            <VideoOff :size="34" />
            <strong>{{ localMediaError ? '讲解媒体暂时无法播放' : hasAudio ? '正在播放课程讲解音频' : '当前知识点暂无数字人视频' }}</strong>
            <p>{{ hasAudio ? '音频时钟正在同步目录、进度与 PPT。' : 'PPT 与讲解文本仍可正常阅读，不影响自主研习。' }}</p>
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
          <small>第 {{ displayedPage }} / {{ totalPages }} 页</small>
        </header>

        <div class="sl-slide-frame">
          <img
            v-if="effectiveSlide && !slideError"
            :key="effectiveSlide.imageUrl || effectiveSlide.url"
            :src="effectiveSlide.imageUrl || effectiveSlide.url"
            :alt="'课程课件第 ' + displayedPage + ' 页'"
            @error="slideError = true"
          />
          <div v-else-if="effectivePptPage?.content || currentNode?.content" class="sl-slide-text">
            <span>第 {{ displayedPage }} 页</span>
            <h2>{{ effectivePptPage?.title || currentNode?.title }}</h2>
            <p>{{ effectivePptPage?.content || currentNode?.content }}</p>
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
          <span>第 {{ displayedPage }} 页</span>
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
        :disabled="!mediaElement"
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
          :max="Math.max(effectiveDuration, 1)"
          step="0.1"
          :value="currentTime"
          @input="handleSeek"
        />
      </label>
      <span class="sl-time">{{ formatTime(effectiveDuration) }}</span>

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
import { resolvePptCueAtTime } from '../adapters/mediaPlaybackAdapter.js'
import {
  isActiveAudioClockEvent,
  resolveActiveAudioClock,
  shouldSeekMediaClock,
} from '../composables/usePlaylistPlayback.js'

const props = defineProps({
  mode: { type: String, required: true },
  currentNode: { type: Object, default: null },
  currentTime: { type: Number, default: 0 },
  seekRevision: { type: Number, default: 0 },
  currentPage: { type: Number, default: 1 },
  currentSlide: { type: Object, default: null },
  currentPptPage: { type: Object, default: null },
  currentVideoUrl: { type: String, default: '' },
  totalPages: { type: Number, default: 1 },
  totalDuration: { type: Number, default: 0 },
  audioUrl: { type: String, default: '' },
  playlist: { type: Object, default: null },
  playlistIndex: { type: Number, default: 0 },
  mediaDuration: { type: Number, default: 0 },
  subtitleSegments: { type: Array, default: () => [] },
  pptTimeline: { type: Array, default: () => [] },
  pptManifest: { type: Object, default: null },
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
  'playlist-next',
])

const stageRef = ref(null)
const videoRef = ref(null)
const audioRef = ref(null)
const localMediaError = ref('')
const slideError = ref(false)
let applyingExternalTime = false

const activeAudioClock = computed(() => resolveActiveAudioClock(
  props.playlist?.items,
  props.playlistIndex,
  props.audioUrl,
))
const activeAudioUrl = computed(() => activeAudioClock.value.audioUrl)
const playlistOffset = computed(() => activeAudioClock.value.offsetSeconds)
const hasSegmentedPlaylistAudio = computed(() => activeAudioClock.value.segmented)
const hasAudio = computed(() => Boolean(activeAudioUrl.value) && !localMediaError.value)
const mediaElement = computed(() => hasAudio.value ? audioRef.value : videoRef.value)
const mediaGeneration = computed(() => hasAudio.value
  ? activeAudioClock.value.generation
  : `video:${props.currentVideoUrl || ''}`)
const effectiveDuration = computed(() => Math.max(Number(props.mediaDuration) || 0, Number(props.totalDuration) || 0))

const releasePptCue = computed(() => resolvePptCueAtTime(
  props.pptTimeline,
  Math.max(0, Number(props.currentTime) || 0) * 1000,
))
const activePptDeck = computed(() => {
  const decks = props.pptManifest?.decks || []
  const versionId = releasePptCue.value?.materialVersionId || props.pptManifest?.primaryMaterialVersionId
  return decks.find(deck => deck.materialVersionId === versionId) || null
})
const releasePptPage = computed(() => {
  const page = releasePptCue.value?.page
  const pages = activePptDeck.value?.pages?.length
    ? activePptDeck.value.pages
    : props.pptManifest?.pages || []
  return page ? pages.find(item => item.page === page) ?? null : null
})
const effectiveSlide = computed(() => releasePptPage.value || props.currentSlide)
const effectivePptPage = computed(() => releasePptPage.value || props.currentPptPage)
const displayedPage = computed(() => releasePptCue.value?.page ?? props.currentPage)

const captionText = computed(() => {
  return String(props.currentNode?.content || '')
    .replace(/[#*_>]/g, '')
    .replace(/s+/g, ' ')
    .trim()
    .slice(0, 220)
})

function localTimeForGlobal(globalTime) {
  if (hasAudio.value) {
    return hasSegmentedPlaylistAudio.value
      ? Math.max(0, Number(globalTime) - playlistOffset.value)
      : Math.max(0, Number(globalTime) || 0)
  }
  return Math.max(0, Number(globalTime) - Number(props.currentNode?.timestampStart || 0))
}

function globalTimeFromElement(element = mediaElement.value) {
  if (!element) return Math.max(0, Number(props.currentTime) || 0)
  if (hasAudio.value) return (hasSegmentedPlaylistAudio.value ? playlistOffset.value : 0) + element.currentTime
  return Number(props.currentNode?.timestampStart || 0) + element.currentTime
}

function isActiveMediaElement(element) {
  if (!element || element !== mediaElement.value) return false
  if (!isActiveAudioClockEvent(element.dataset?.mediaGeneration, mediaGeneration.value)) return false
  const expected = hasAudio.value ? activeAudioUrl.value : props.currentVideoUrl
  const actual = element.currentSrc || element.src
  if (!expected || !actual || typeof document === 'undefined') return true
  try {
    return new URL(expected, document.baseURI).href === new URL(actual, document.baseURI).href
  } catch {
    return expected === actual
  }
}

function isTerminalMediaTime(element) {
  const duration = Number(element?.duration)
  const current = Number(element?.currentTime)
  return Number.isFinite(duration) && duration > 0
    && Number.isFinite(current) && current >= duration - 0.05
}

function syncVideoSettings() {
  const element = mediaElement.value
  if (!element) return
  element.playbackRate = props.playbackRate
  element.volume = props.volume
  element.muted = props.isMuted
}

function syncMediaClock(globalTime, force = false) {
  const element = mediaElement.value
  if (!element || element.readyState < 1) return
  const target = localTimeForGlobal(globalTime)
  if (!shouldSeekMediaClock(element.currentTime, target, force)) return
  applyingExternalTime = true
  element.currentTime = Math.min(target, element.duration || target)
  applyingExternalTime = false
}

async function handleLoadedMetadata(event) {
  const element = event?.currentTarget || mediaElement.value
  if (!isActiveMediaElement(element)) return
  syncVideoSettings()
  syncMediaClock(props.currentTime, true)
  localMediaError.value = ''
  if (props.isPlaying) {
    await element.play().catch(() => emitPlaybackState(false, element))
  }
}

function handleTimeUpdate(event) {
  const element = event?.currentTarget || mediaElement.value
  if (!isActiveMediaElement(element) || applyingExternalTime || element.ended || isTerminalMediaTime(element)) return
  const globalTime = globalTimeFromElement(element)
  const cue = hasAudio.value
    ? resolvePptCueAtTime(props.pptTimeline, globalTime * 1000)
    : null
  emit('update-playback', {
    globalTime,
    isPlaying: !element.paused,
    page: cue?.page ?? null,
    materialVersionId: cue?.materialVersionId ?? null,
  })
}

function emitPlaybackState(value, element = mediaElement.value) {
  if (!isActiveMediaElement(element)) return
  emit('update-playback', {
    globalTime: globalTimeFromElement(element),
    isPlaying: value,
  })
}

function togglePlay() {
  const element = mediaElement.value
  if (!element) return
  if (element.paused) {
    element.play().catch(handleMediaError)
  } else {
    element.pause()
  }
}

function handleSeek(event) {
  const nextTime = Number(event.target.value)
  emit('seek', nextTime)
}

function handleEnded(event) {
  if (event?.currentTarget && !isActiveMediaElement(event.currentTarget)) return
  if (hasSegmentedPlaylistAudio.value && props.playlistIndex < (props.playlist?.items?.length || 0) - 1) {
    emit('playlist-next')
    return
  }
  emit('update-playback', {
    globalTime: globalTimeFromElement(),
    isPlaying: false,
  })
}

function handleMediaError(event) {
  if (event?.currentTarget && !isActiveMediaElement(event.currentTarget)) return
  localMediaError.value = '媒体资源加载失败'
  emit('media-error', localMediaError.value)
}

async function retryMedia() {
  localMediaError.value = ''
  await nextTick()
  mediaElement.value?.load()
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
    if (hasAudio.value) return
    localMediaError.value = ''
    await nextTick()
    videoRef.value?.load()
  }
)

watch(() => activeAudioClock.value.generation, async () => {
  localMediaError.value = ''
  await nextTick()
  audioRef.value?.load()
})

watch(
  () => props.currentSlide?.url,
  () => {
    slideError.value = false
  }
)

watch(
  () => props.currentTime,
  value => syncMediaClock(value)
)

watch(() => props.seekRevision, () => syncMediaClock(props.currentTime, true))

watch(() => props.playbackRate, syncVideoSettings)
watch(() => props.volume, syncVideoSettings)
watch(() => props.isMuted, syncVideoSettings)
</script>
