<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Captions,
  ChevronLeft,
  ChevronRight,
  FileQuestion,
  Headphones,
  MonitorPlay,
  Pause,
  Play,
  Presentation,
  SkipBack,
  SkipForward,
  VideoOff,
  Volume2,
  VolumeX,
} from 'lucide-vue-next'

import SfxButton from '@/app/ui/SfxButton.vue'
import AvatarViewport from '@/features/student-learning/components/AvatarViewport.vue'
import { resolvePptCueAtTime } from '@/features/student-learning/adapters/mediaPlaybackAdapter.js'

/**
 * The frozen release audio is the only P0 clock.  Legacy video is retained as
 * an explicit compatibility fallback while existing courses are migrated.
 */
const props = defineProps({
  currentNode: { type: Object, default: null },
  currentTime: { type: Number, default: 0 },
  currentSlide: { type: Object, default: null },
  currentPptPage: { type: Object, default: null },
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 },
  isPlaying: { type: Boolean, default: false },
  playbackRate: { type: Number, default: 1 },
  volume: { type: Number, default: 0.85 },
  isMuted: { type: Boolean, default: false },
  captionsEnabled: { type: Boolean, default: true },
  audioUrl: { type: String, default: '' },
  duration: { type: Number, default: 0 },
  subtitleSegments: { type: Array, default: () => [] },
  pptTimeline: { type: Array, default: () => [] },
  pptManifest: { type: Object, default: null },
  avatarCues: { type: Object, default: null },
  avatarSpriteManifest: { type: Object, default: null },
  avatarAssetSource: { type: String, default: 'platform' },
  defaultPlaybackMode: { type: String, default: 'compatibility' },
  mediaStatus: { type: String, default: 'idle' },
  mediaMessage: { type: String, default: '' },
  legacyVideoUrl: { type: String, default: '' },
})

const emit = defineEmits([
  'playback',
  'page-change',
  'node-change',
  'rate-change',
  'volume-change',
  'mute-change',
  'captions-change',
])

const audioRef = ref(null)
const legacyVideoRef = ref(null)
const slideError = ref(false)
const audioError = ref('')
const legacyVideoError = ref('')
const mediaDuration = ref(0)
let applyingExternalTime = false

const hasAudio = computed(() => Boolean(props.audioUrl) && !audioError.value)
const hasLegacyVideo = computed(() => !hasAudio.value && Boolean(props.legacyVideoUrl) && !legacyVideoError.value)
const mediaElement = computed(() => hasAudio.value ? audioRef.value : legacyVideoRef.value)
const effectiveDuration = computed(() => Math.max(Number(props.duration) || 0, mediaDuration.value))
const mediaLabel = computed(() => hasAudio.value ? '讲解音频' : hasLegacyVideo.value ? '兼容讲解视频' : '讲解媒体')

const activeSubtitleIndex = computed(() => {
  const currentMs = Math.max(0, Number(props.currentTime) || 0) * 1000
  return props.subtitleSegments.findIndex(
    segment => currentMs >= segment.startMs && currentMs <= segment.endMs,
  )
})

const activeSubtitle = computed(() => props.subtitleSegments[activeSubtitleIndex.value] ?? null)

const fallbackTranscript = computed(() => {
  if (props.subtitleSegments.length || !props.currentNode?.content) return []
  return [{ index: 0, text: props.currentNode.content }]
})

const visibleTranscript = computed(() => props.subtitleSegments.length ? props.subtitleSegments : fallbackTranscript.value)

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
  const page = releasePptCue.value?.page ?? Math.max(1, Number(props.currentPage) || 1)
  const materialVersionId = releasePptCue.value?.materialVersionId
  const pages = activePptDeck.value?.pages?.length
    ? activePptDeck.value.pages
    : (!materialVersionId || materialVersionId === props.pptManifest?.primaryMaterialVersionId)
      ? props.pptManifest?.pages
      : []
  return page ? pages?.find(item => item.page === page) ?? null : null
})

const effectiveSlide = computed(() => releasePptPage.value || props.currentSlide)
const displayedPage = computed(() => releasePptCue.value?.page ?? Math.max(1, Number(props.currentPage) || 1))
const displayedTotalPages = computed(() => {
  const pages = activePptDeck.value?.pages || []
  return pages.length
    ? Math.max(...pages.map(item => Number(item.page) || 0))
    : props.totalPages
})

function sourceTimeForGlobal(globalTime) {
  const timestamp = Math.max(0, Number(globalTime) || 0)
  if (hasAudio.value) return timestamp
  return Math.max(0, timestamp - Number(props.currentNode?.timestampStart || 0))
}

function globalTimeFromElement() {
  const element = mediaElement.value
  if (!element) return Math.max(0, Number(props.currentTime) || 0)
  if (hasAudio.value) return element.currentTime
  return Number(props.currentNode?.timestampStart || 0) + element.currentTime
}

function emitPlayback(isPlaying = !mediaElement.value?.paused) {
  const globalTime = globalTimeFromElement()
  const currentMs = globalTime * 1000
  const activeCue = hasAudio.value ? resolvePptCueAtTime(props.pptTimeline, currentMs) : null
  const activeSegment = hasAudio.value
    ? props.subtitleSegments.find(segment => currentMs >= segment.startMs && currentMs <= segment.endMs)
    : null
  emit('playback', {
    globalTime,
    isPlaying,
    page: activeCue?.page ?? null,
    materialVersionId: activeCue?.materialVersionId ?? null,
    nodeId: activeCue?.nodeId ?? activeSegment?.nodeId ?? null,
  })
}

function syncMediaSettings() {
  for (const element of [audioRef.value, legacyVideoRef.value]) {
    if (!element) continue
    element.playbackRate = Math.min(2, Math.max(0.5, Number(props.playbackRate) || 1))
    element.volume = Math.min(1, Math.max(0, Number(props.volume) || 0))
    element.muted = props.isMuted
  }
}

async function handleLoadedMetadata() {
  const element = mediaElement.value
  if (!element) return
  mediaDuration.value = Number.isFinite(element.duration) ? element.duration : 0
  syncMediaSettings()
  applyingExternalTime = true
  const target = sourceTimeForGlobal(props.currentTime)
  element.currentTime = Math.min(target, element.duration || target)
  applyingExternalTime = false
  if (props.isPlaying) {
    await element.play().catch(() => emitPlayback(false))
  }
}

function handleTimeUpdate() {
  if (!applyingExternalTime) emitPlayback()
}

function handleAudioError() {
  audioError.value = '发布的讲解音频无法加载'
  emitPlayback(false)
}

function handleLegacyVideoError() {
  legacyVideoError.value = '兼容讲解视频无法加载'
  emitPlayback(false)
}

async function togglePlay() {
  const element = mediaElement.value
  if (!element) return
  if (element.paused) {
    await element.play().catch(() => emitPlayback(false))
  } else {
    element.pause()
  }
}

function seekTo(value) {
  const element = mediaElement.value
  if (!element) return
  const globalTime = Math.max(0, Number(value) || 0)
  const target = sourceTimeForGlobal(globalTime)
  element.currentTime = Math.min(target, element.duration || target)
  emitPlayback(!element.paused)
}

function skipBy(seconds) {
  seekTo((Number(props.currentTime) || 0) + seconds)
}

function handleEnded() {
  emitPlayback(false)
}

function handlePageChange(page) {
  emit('page-change', page)
}

function formatTime(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remain = seconds % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remain).padStart(2, '0')}`
    : `${minutes}:${String(remain).padStart(2, '0')}`
}

watch(() => props.audioUrl, async () => {
  audioError.value = ''
  mediaDuration.value = 0
  await nextTick()
  audioRef.value?.load()
})

watch(() => props.legacyVideoUrl, async () => {
  legacyVideoError.value = ''
  await nextTick()
  legacyVideoRef.value?.load()
})

watch(() => effectiveSlide.value?.imageUrl ?? effectiveSlide.value?.url, () => {
  slideError.value = false
})

watch(() => props.currentTime, value => {
  const element = mediaElement.value
  if (!element || element.readyState < 1) return
  const target = sourceTimeForGlobal(value)
  if (Math.abs(element.currentTime - target) > 1.25) {
    applyingExternalTime = true
    element.currentTime = Math.min(target, element.duration || target)
    applyingExternalTime = false
  }
})

watch(() => props.isPlaying, async shouldPlay => {
  const element = mediaElement.value
  if (!element || Boolean(!element.paused) === shouldPlay) return
  if (shouldPlay) await element.play().catch(() => emitPlayback(false))
  else element.pause()
})

watch([() => props.playbackRate, () => props.volume, () => props.isMuted], syncMediaSettings)
</script>

<template>
  <div class="sfx-stage">
    <section class="sfx-stage-pane sfx-stage-lecture" aria-label="讲解与字幕">
      <header class="sfx-stage-pane-label">
        <span><MonitorPlay :size="15" /> {{ mediaLabel }}</span>
        <small v-if="hasAudio" class="sfx-t-caption">音频同步</small>
        <small v-else-if="hasLegacyVideo" class="sfx-t-caption">兼容模式</small>
      </header>

      <div class="sfx-stage-media-frame">
        <audio
          v-if="hasAudio"
          ref="audioRef"
          :key="audioUrl"
          :src="audioUrl"
          preload="metadata"
          @loadedmetadata="handleLoadedMetadata"
          @timeupdate="handleTimeUpdate"
          @play="emitPlayback(true)"
          @pause="emitPlayback(false)"
          @ended="handleEnded"
          @error="handleAudioError"
        />

        <div v-if="hasAudio" class="sfx-stage-audio-identity">
          <span class="sfx-stage-audio-orbit" aria-hidden="true"><Headphones :size="30" /></span>
          <strong>{{ currentNode?.title || '课程讲解' }}</strong>
          <p class="sfx-t-caption">PPT 与讲解原文跟随音频时间轴同步。</p>
          <p v-if="captionsEnabled && activeSubtitle" class="sfx-stage-live-caption" aria-live="polite">
            {{ activeSubtitle.text }}
          </p>
        </div>
        <video
          v-else-if="hasLegacyVideo"
          ref="legacyVideoRef"
          :key="legacyVideoUrl"
          :src="legacyVideoUrl"
          playsinline
          preload="metadata"
          @loadedmetadata="handleLoadedMetadata"
          @timeupdate="handleTimeUpdate"
          @play="emitPlayback(true)"
          @pause="emitPlayback(false)"
          @ended="handleEnded"
          @error="handleLegacyVideoError"
        />

        <div v-else class="sfx-stage-fallback">
          <VideoOff :size="32" :stroke-width="1.6" />
          <strong>{{ audioError || legacyVideoError || '当前课程尚未发布讲解媒体' }}</strong>
          <p class="sfx-t-caption">{{ mediaMessage || '课件与讲解原文仍可正常阅读。' }}</p>
        </div>
      </div>

      <section class="sfx-stage-transcript" aria-label="讲解原文">
        <header>
          <span class="sfx-t-caption">讲解原文</span>
          <nav class="sfx-stage-slide-nav" aria-label="课件翻页">
            <SfxButton variant="tertiary" size="sm" :disabled="currentPage <= 1" aria-label="上一页课件" @click="handlePageChange(currentPage - 1)">
              <template #icon><ChevronLeft :size="16" /></template>
            </SfxButton>
            <span class="sfx-t-caption">{{ displayedPage }} / {{ displayedTotalPages }}</span>
            <SfxButton variant="tertiary" size="sm" :disabled="currentPage >= totalPages" aria-label="下一页课件" @click="handlePageChange(currentPage + 1)">
              <template #icon><ChevronRight :size="16" /></template>
            </SfxButton>
          </nav>
        </header>
        <ol v-if="visibleTranscript.length" class="sfx-stage-transcript-list">
          <li
            v-for="(segment, index) in visibleTranscript"
            :key="segment.index ?? index"
            :class="{ 'is-active': subtitleSegments.length && index === activeSubtitleIndex }"
          >
            {{ segment.text }}
          </li>
        </ol>
        <p v-else class="sfx-t-caption">当前知识点暂无讲解原文。</p>
      </section>
    </section>

    <slot name="secondary">
      <section class="sfx-stage-pane" aria-label="同步课件">
        <header class="sfx-stage-pane-label">
          <span><Presentation :size="15" /> 同步课件</span>
          <small class="sfx-t-caption">第 {{ displayedPage }} / {{ displayedTotalPages }} 页</small>
        </header>

        <div class="sfx-stage-slide-frame">
          <img
            v-if="effectiveSlide && !slideError"
            :key="effectiveSlide.imageUrl ?? effectiveSlide.url"
            :src="effectiveSlide.imageUrl ?? effectiveSlide.url"
            :alt="`课程课件第 ${displayedPage} 页`"
            @error="slideError = true"
          />
          <div v-else-if="currentPptPage?.content || currentPptPage?.title" class="sfx-stage-slide-text">
            <span class="sfx-t-caption">第 {{ displayedPage }} 页</span>
            <h2 class="sfx-t-title2">{{ currentPptPage.title || currentNode?.title }}</h2>
            <p class="sfx-t-body">{{ currentPptPage.content }}</p>
          </div>
          <div v-else class="sfx-stage-fallback is-light">
            <FileQuestion :size="32" :stroke-width="1.6" />
            <strong>当前页暂无可显示的课件</strong>
            <p class="sfx-t-caption">可从学习轨道切换其他知识点。</p>
          </div>
          <AvatarViewport
            v-if="hasAudio && avatarCues && avatarSpriteManifest"
            :cues="avatarCues"
            :sprite-manifest="avatarSpriteManifest"
            :current-time="currentTime"
            :default-playback-mode="defaultPlaybackMode"
            :asset-source="avatarAssetSource"
          />
        </div>
      </section>
    </slot>

    <footer class="sfx-stage-controls" aria-label="播放控制">
      <SfxButton variant="primary" size="sm" :disabled="!mediaElement" :aria-label="isPlaying ? '暂停讲解' : '播放讲解'" @click="togglePlay">
        <template #icon><Pause v-if="isPlaying" :size="16" /><Play v-else :size="16" /></template>
        {{ isPlaying ? '暂停' : '播放' }}
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="!mediaElement" @click="skipBy(-10)">
        <template #icon><SkipBack :size="16" /></template>
        后退 10 秒
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="!currentNode || currentNode.index <= 0" @click="emit('node-change', -1)">
        上一知识点
      </SfxButton>

      <span class="sfx-stage-time">{{ formatTime(currentTime) }}</span>
      <label class="sfx-stage-seek">
        <span class="sfx-visually-hidden">课程播放进度</span>
        <input type="range" min="0" :max="Math.max(effectiveDuration, 1)" step="0.1" :value="currentTime" :disabled="!mediaElement" @input="seekTo($event.target.value)" />
      </label>
      <span class="sfx-stage-time">{{ formatTime(effectiveDuration) }}</span>

      <SfxButton variant="tertiary" size="sm" :disabled="!currentNode" @click="emit('node-change', 1)">
        下一知识点
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="!mediaElement" @click="skipBy(10)">
        前进 10 秒
        <template #icon><SkipForward :size="16" /></template>
      </SfxButton>
      <label class="sfx-stage-rate">
        <span class="sfx-visually-hidden">播放速度</span>
        <select :value="playbackRate" :disabled="!mediaElement" aria-label="播放速度" @change="emit('rate-change', Number($event.target.value))">
          <option :value="0.75">0.75×</option>
          <option :value="1">1.0×</option>
          <option :value="1.25">1.25×</option>
          <option :value="1.5">1.5×</option>
          <option :value="2">2.0×</option>
        </select>
      </label>
      <SfxButton variant="tertiary" size="sm" :aria-pressed="captionsEnabled" @click="emit('captions-change', !captionsEnabled)">
        <template #icon><Captions :size="16" /></template>
        字幕
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="!mediaElement" :aria-label="isMuted ? '取消静音' : '静音'" @click="emit('mute-change', !isMuted)">
        <template #icon><VolumeX v-if="isMuted || volume === 0" :size="16" /><Volume2 v-else :size="16" /></template>
        {{ isMuted ? '静音' : '声音' }}
      </SfxButton>
      <label class="sfx-stage-volume">
        <span class="sfx-visually-hidden">音量</span>
        <input type="range" min="0" max="1" step="0.05" :value="isMuted ? 0 : volume" :disabled="!mediaElement" @input="emit('volume-change', Number($event.target.value))" />
      </label>
    </footer>
  </div>
</template>

<style scoped>
.sfx-stage {
  flex: 1;
  min-height: 0;
  display: grid;
  /* The teacher's original slide is the primary learning surface.  Audio,
     transcript and the avatar remain supporting layers rather than competing
     content panes. */
  grid-template-columns: minmax(220px, 1fr) minmax(0, 3fr);
  grid-template-rows: minmax(0, 1fr) auto;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--surface-canvas);
  overflow: hidden;
}

.sfx-stage-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.sfx-stage-pane-label,
.sfx-stage-transcript header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}

.sfx-stage-pane-label span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  font-weight: 500;
}

.sfx-stage-media-frame {
  position: relative;
  min-height: 210px;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--code-bg);
  overflow: hidden;
}

.sfx-stage-media-frame video { width: 100%; height: 100%; object-fit: contain; }

.sfx-stage-audio-identity {
  width: min(78%, 420px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--text-inverse);
  text-align: center;
}

.sfx-stage-audio-orbit {
  width: 64px;
  height: 64px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(232 238 244 / 38%);
  border-radius: var(--radius-full);
  color: var(--ink-100);
  box-shadow: 0 0 0 12px rgb(232 238 244 / 6%);
}

.sfx-stage-live-caption {
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  border-left: 2px solid var(--amber-300);
  background: rgb(255 255 255 / 9%);
  color: var(--text-inverse);
  line-height: 1.65;
}

.sfx-stage-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-8);
  text-align: center;
  color: var(--code-muted);
}

.sfx-stage-fallback.is-light { color: var(--text-muted); }
.sfx-stage-fallback strong { font-size: var(--ui-md-size); }

.sfx-stage-transcript { min-height: 128px; max-height: 178px; display: flex; flex-direction: column; }
.sfx-stage-transcript header { padding-block: var(--space-2); }
.sfx-stage-transcript-list { min-height: 0; overflow-y: auto; margin: 0; padding: var(--space-2) var(--space-4); list-style: none; }
.sfx-stage-transcript-list li { padding: var(--space-2) var(--space-3); border-left: 2px solid transparent; color: var(--text-secondary); font-size: var(--ui-sm-size); line-height: 1.65; }
.sfx-stage-transcript-list li.is-active { border-left-color: var(--amber-500); background: var(--amber-100); color: var(--text-primary); }
.sfx-stage-transcript > .sfx-t-caption { padding: var(--space-4); }

.sfx-stage-slide-frame { position:relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; background: var(--surface-cool); overflow: hidden; }
.sfx-stage-slide-frame img { width:100%; height:100%; max-width:100%; max-height:100%; object-fit:contain; }
.sfx-stage-slide-frame :deep(.avatar-viewport) { z-index:2; }
.sfx-stage-slide-text { padding: var(--space-8); display: flex; flex-direction: column; gap: var(--space-3); overflow-y: auto; max-height: 100%; }
.sfx-stage-slide-nav { display: flex; align-items: center; gap: var(--space-2); }

.sfx-stage-controls {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.sfx-stage-controls :deep(.sfx-btn.is-sm) { min-width: 0; }
.sfx-stage-time { min-width: 38px; color: var(--text-secondary); font-size: var(--caption-size); font-variant-numeric: tabular-nums; text-align: center; }
.sfx-stage-seek { flex: 1 1 140px; min-width: 100px; }
.sfx-stage-seek input, .sfx-stage-volume input { width: 100%; accent-color: var(--ink-700); }
.sfx-stage-rate select { height: 32px; padding: 0 var(--space-2); border: 1px solid var(--border-default); border-radius: var(--radius-sm); background: var(--surface-panel); color: var(--text-secondary); font: inherit; font-size: var(--ui-sm-size); }
.sfx-stage-volume { width: 72px; }

@media (max-width: 1200px) {
  .sfx-stage { grid-template-columns: 1fr; grid-template-rows: minmax(320px, 1fr) minmax(260px, 0.8fr) auto; overflow-y: auto; }
  .sfx-stage-controls { grid-row: 3; }
}

@media (max-width: 760px) {
  .sfx-stage { padding: var(--space-3); }
  .sfx-stage-controls { align-items: stretch; }
  .sfx-stage-controls :deep(.sfx-btn.is-sm) { flex: 1 1 auto; }
  .sfx-stage-seek { order: 3; flex-basis: 100%; }
}
</style>
