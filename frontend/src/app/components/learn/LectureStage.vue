<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Captions,
  ChevronLeft,
  ChevronRight,
  FileQuestion,
  LocateFixed,
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
  playlist: { type: Object, default: null },
  playlistIndex: { type: Number, default: 0 },
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
  // 智能体面板是否打开：打开时左侧数字人区域切换为 PPT 缩略图
  agentPanelOpen: { type: Boolean, default: false },
})

const emit = defineEmits([
  'playback',
  'page-change',
  'node-change',
  'rate-change',
  'volume-change',
  'mute-change',
  'captions-change',
  'playlist-next',
  'playlist-previous',
  'media-seeked',
  'media-error',
])

const audioRef = ref(null)
const legacyVideoRef = ref(null)
const slideError = ref(false)
const audioError = ref('')
const legacyVideoError = ref('')
const mediaDuration = ref(0)
const transcriptListRef = ref(null)
// 讲解原文滚动默认跟随语音播放；用户手动滚动后暂停跟随，点"回到进度"恢复。
const followPlayback = ref(true)
let programmaticScroll = false
let applyingExternalTime = false
let switchingMediaSource = false

const activePlaylistItem = computed(() => props.playlist?.items?.[props.playlistIndex] ?? null)
const activeAudioUrl = computed(() => activePlaylistItem.value?.audioUrl || props.audioUrl)
const playlistOffset = computed(() => Number(activePlaylistItem.value?.offsetMs || 0) / 1000)
const hasPlaylist = computed(() => Boolean(activePlaylistItem.value))
const avatarPlaybackTime = computed(() => sourceTimeForGlobal(props.currentTime))
const hasAudio = computed(() => Boolean(activeAudioUrl.value) && !audioError.value)
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
  if (hasAudio.value) return hasPlaylist.value ? Math.max(0, timestamp - playlistOffset.value) : timestamp
  return Math.max(0, timestamp - Number(props.currentNode?.timestampStart || 0))
}

function globalTimeFromElement(element = mediaElement.value) {
  if (!element) return Math.max(0, Number(props.currentTime) || 0)
  if (hasAudio.value) return (hasPlaylist.value ? playlistOffset.value : 0) + element.currentTime
  return Number(props.currentNode?.timestampStart || 0) + element.currentTime
}

function isActiveMediaElement(element) {
  if (!element || element !== mediaElement.value) return false
  const expected = hasAudio.value ? activeAudioUrl.value : props.legacyVideoUrl
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

function emitPlayback(isPlaying, element = mediaElement.value) {
  // Vue may deliver a final media event after a keyed element has already
  // been replaced.  Never project an obsolete audio clock into the new item.
  if (!isActiveMediaElement(element)) return
  // Replacing a keyed <audio> element can fire final timeupdate/play/pause
  // events on the old source.  None of them describe the newly selected
  // playlist item, so ignore the old clock until new metadata is ready.
  if (switchingMediaSource) return
  const playing = isPlaying ?? !element.paused
  const globalTime = globalTimeFromElement(element)
  const currentMs = globalTime * 1000
  const activeCue = hasAudio.value ? resolvePptCueAtTime(props.pptTimeline, currentMs) : null
  const activeSegment = hasAudio.value
    ? props.subtitleSegments.find(segment => currentMs >= segment.startMs && currentMs <= segment.endMs)
    : null
  emit('playback', {
    globalTime,
    isPlaying: playing,
    page: activeCue?.page ?? null,
    materialVersionId: activeCue?.materialVersionId ?? null,
    nodeId: activeCue?.nodeId ?? activeSegment?.nodeId ?? null,
    outlineNodeId: activeCue?.outlineNodeId ?? activeSegment?.outlineNodeId ?? null,
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

async function handleLoadedMetadata(event) {
  const element = event?.currentTarget || mediaElement.value
  if (!isActiveMediaElement(element)) return
  mediaDuration.value = Number.isFinite(element.duration) ? element.duration : 0
  syncMediaSettings()
  applyingExternalTime = true
  const target = sourceTimeForGlobal(props.currentTime)
  element.currentTime = Math.min(target, element.duration || target)
  applyingExternalTime = false
  let playFailed = false
  if (props.isPlaying) await element.play().catch(() => { playFailed = true })
  if (!isActiveMediaElement(element)) return
  switchingMediaSource = false
  emitPlayback(playFailed ? false : !element.paused, element)
}

function handleTimeUpdate(event) {
  const element = event?.currentTarget || mediaElement.value
  if (!isActiveMediaElement(element)) return
  // Browsers emit a final timeupdate after the element is already ended and
  // paused.  Let handleEnded own the item transition; treating that final
  // sample as a pause can preselect the next item and then skip it.
  if (element.ended || isTerminalMediaTime(element)) return
  if (!applyingExternalTime) emitPlayback(undefined, element)
}

function emitMediaSeeked(element = mediaElement.value) {
  if (!isActiveMediaElement(element) || switchingMediaSource) return
  const item = activePlaylistItem.value
  emit('media-seeked', {
    mediaReleaseItemId: item?.itemId ?? null,
    localTimeMs: Math.round(Math.max(0, Number(element.currentTime) || 0) * 1_000),
    globalTimeMs: Math.round(globalTimeFromElement(element) * 1_000),
  })
}

function handleSeeked(event) {
  emitMediaSeeked(event?.currentTarget || mediaElement.value)
}

function handlePause(event) {
  const element = event?.currentTarget || mediaElement.value
  // Natural media completion emits pause before ended in some browsers.
  // Keep the play intent so handleEnded can advance and resume the next item.
  if (!isActiveMediaElement(element) || isTerminalMediaTime(element)) return
  emitPlayback(false, element)
}

function handleAudioError(event) {
  if (event?.currentTarget && !isActiveMediaElement(event.currentTarget)) return
  switchingMediaSource = false
  audioError.value = '发布的讲解音频无法加载'
  emit('media-error', {
    code: 'MEDIA_SOURCE_UNAVAILABLE',
    mediaReleaseItemId: activePlaylistItem.value?.itemId ?? null,
  })
  emitPlayback(false)
}

function handleLegacyVideoError(event) {
  if (event?.currentTarget && !isActiveMediaElement(event.currentTarget)) return
  legacyVideoError.value = '兼容讲解视频无法加载'
  emit('media-error', {
    code: 'MEDIA_SOURCE_UNAVAILABLE',
    mediaReleaseItemId: null,
  })
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
  if (hasPlaylist.value) {
    const targetMs = globalTime * 1000
    const targetIndex = props.playlist?.items?.findIndex(item => {
      const start = Math.max(0, Number(item?.offsetMs) || 0)
      const end = start + Math.max(0, Number(item?.durationMs) || 0)
      return end > start && targetMs >= start && targetMs < end
    }) ?? -1
    if (targetIndex >= 0 && targetIndex !== props.playlistIndex) {
      const targetItem = props.playlist.items[targetIndex]
      const localTime = sourceTimeForGlobal(globalTime)
      applyingExternalTime = true
      element.currentTime = Math.min(localTime, element.duration || localTime)
      applyingExternalTime = false
      const targetCue = hasAudio.value ? resolvePptCueAtTime(props.pptTimeline, targetMs) : null
      emit('playback', {
        globalTime,
        isPlaying: !element.paused,
        nodeId: targetItem?.nodeId ?? null,
        outlineNodeId: targetItem?.outlineNodeId ?? null,
        page: targetCue?.page ?? null,
        materialVersionId: targetCue?.materialVersionId ?? null,
      })
      return
    }
  }
  const target = sourceTimeForGlobal(globalTime)
  applyingExternalTime = true
  element.currentTime = Math.min(target, element.duration || target)
  applyingExternalTime = false
  emitPlayback(!element.paused)
}

function skipBy(seconds) {
  seekTo((Number(props.currentTime) || 0) + seconds)
}

// 把当前高亮句滚动到原文容器可视区中部（仅改容器自身的 scrollTop，不触发祖先滚动）。
function scrollTranscriptToActive(index) {
  const list = transcriptListRef.value
  if (!list) return
  const item = list.children[index]
  if (!item) return
  programmaticScroll = true
  const listRect = list.getBoundingClientRect()
  const itemRect = item.getBoundingClientRect()
  const top = list.scrollTop + (itemRect.top - listRect.top)
  list.scrollTop = Math.max(0, top - (list.clientHeight - itemRect.height) / 2)
  requestAnimationFrame(() => { programmaticScroll = false })
}

function handleTranscriptScroll() {
  if (programmaticScroll) return
  // 用户手动滚动：暂停自动跟随，露出"回到进度"按钮。
  followPlayback.value = false
}

function resumeFollow() {
  followPlayback.value = true
  const index = activeSubtitleIndex.value
  if (index >= 0) scrollTranscriptToActive(index)
}

function handleEnded(event) {
  if (event?.currentTarget && !isActiveMediaElement(event.currentTarget)) return
  // An old keyed element may report ended again while Vue removes it.  The
  // source switch already has an authoritative target, so ignore that stale
  // event instead of advancing twice.
  if (switchingMediaSource) return
  if (hasPlaylist.value && props.playlistIndex < (props.playlist?.items?.length || 0) - 1) {
    emit('playlist-next')
    return
  }
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

watch([() => props.audioUrl, () => props.playlistIndex], async () => {
  switchingMediaSource = true
  audioError.value = ''
  mediaDuration.value = 0
  // 切换到新知识点后默认重新跟随语音播放进度
  followPlayback.value = true
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

// 语音播到对应语句时高亮更新，跟随滚动原文容器；用户手动滚动后会暂停跟随。
watch(activeSubtitleIndex, index => {
  if (!followPlayback.value || index < 0) return
  scrollTranscriptToActive(index)
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
  <div class="sfx-stage" :class="{ 'is-agent-open': agentPanelOpen }">
    <section class="sfx-stage-pane sfx-stage-lecture" aria-label="讲解与字幕">
      <header class="sfx-stage-pane-label">
        <span><MonitorPlay :size="15" /> {{ mediaLabel }}</span>
        <small v-if="hasAudio" class="sfx-t-caption">音频同步</small>
        <small v-else-if="hasLegacyVideo" class="sfx-t-caption">兼容模式</small>
      </header>

      <audio
        v-if="hasAudio"
        ref="audioRef"
        :key="`${playlistIndex}:${activeAudioUrl}`"
        :src="activeAudioUrl"
        preload="metadata"
        class="sfx-stage-clock"
        @loadedmetadata="handleLoadedMetadata"
        @timeupdate="handleTimeUpdate"
        @seeked="handleSeeked"
        @play="emitPlayback(true, $event.currentTarget)"
        @pause="handlePause"
        @ended="handleEnded"
        @error="handleAudioError"
      />

      <!-- 智能体面板打开时：优先显示 PPT 缩略图，而非数字人 -->
      <div
        v-if="agentPanelOpen && (effectiveSlide || currentPptPage)"
        class="sfx-stage-slide-frame sfx-stage-lecture-ppt"
      >
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
          <FileQuestion :size="28" :stroke-width="1.6" />
          <strong>当前页暂无可显示的课件</strong>
        </div>
      </div>
      <!-- 默认（非智能体）状态：显示数字人或兼容视频 -->
      <template v-else>
        <AvatarViewport
          v-if="hasAudio && avatarCues"
          :cues="avatarCues"
          :sprite-manifest="avatarSpriteManifest"
          :current-time="avatarPlaybackTime"
          :audio-element="audioRef"
          :default-playback-mode="defaultPlaybackMode"
          :asset-source="avatarAssetSource"
        />
        <video
          v-if="!hasAudio && hasLegacyVideo"
          ref="legacyVideoRef"
          class="sfx-stage-video"
          :key="legacyVideoUrl"
          :src="legacyVideoUrl"
          playsinline
          preload="metadata"
          @loadedmetadata="handleLoadedMetadata"
          @timeupdate="handleTimeUpdate"
          @seeked="handleSeeked"
          @play="emitPlayback(true, $event.currentTarget)"
          @pause="handlePause"
          @ended="handleEnded"
          @error="handleLegacyVideoError"
        />
      </template>

      <div v-if="!agentPanelOpen && !hasAudio && !hasLegacyVideo" class="sfx-stage-fallback">
        <VideoOff :size="32" :stroke-width="1.6" />
        <strong>{{ audioError || legacyVideoError || '当前课程尚未发布讲解媒体' }}</strong>
        <p class="sfx-t-caption">{{ mediaMessage || '课件与讲解原文仍可正常阅读。' }}</p>
      </div>
      <div v-else-if="agentPanelOpen && !effectiveSlide && !currentPptPage?.content && !currentPptPage?.title && !hasAudio && !hasLegacyVideo" class="sfx-stage-fallback is-light">
        <VideoOff :size="32" :stroke-width="1.6" />
        <strong>{{ audioError || legacyVideoError || '当前课程尚未发布讲解媒体' }}</strong>
        <p class="sfx-t-caption">{{ mediaMessage || '课件与讲解原文仍可正常阅读。' }}</p>
      </div>

      <section class="sfx-stage-transcript" aria-label="讲解原文">
        <header>
          <div class="sfx-stage-transcript-tools">
            <span class="sfx-t-caption">讲解原文</span>
            <SfxButton
              v-if="!followPlayback"
              variant="tertiary"
              size="sm"
              class="sfx-transcript-follow"
              aria-label="回到播放进度"
              @click="resumeFollow"
            >
              <template #icon><LocateFixed :size="14" /></template>
              回到进度
            </SfxButton>
          </div>
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
        <ol
          v-if="visibleTranscript.length"
          ref="transcriptListRef"
          class="sfx-stage-transcript-list"
          @scroll="handleTranscriptScroll"
        >
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
        </div>
      </section>
    </slot>

    <footer class="sfx-stage-controls" :class="{ 'is-agent-input': agentPanelOpen }" aria-label="播放控制">
      <slot name="footer">
      <SfxButton variant="primary" size="sm" :disabled="!mediaElement" :aria-label="isPlaying ? '暂停讲解' : '播放讲解'" @click="togglePlay">
        <template #icon><Pause v-if="isPlaying" :size="16" /><Play v-else :size="16" /></template>
        {{ isPlaying ? '暂停' : '播放' }}
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="!mediaElement" @click="skipBy(-10)">
        <template #icon><SkipBack :size="16" /></template>
        后退 10 秒
      </SfxButton>
      <SfxButton variant="tertiary" size="sm" :disabled="hasPlaylist ? playlistIndex <= 0 : !currentNode || currentNode.index <= 0" @click="hasPlaylist ? emit('playlist-previous') : emit('node-change', -1)">
        上一知识点
      </SfxButton>

      <span class="sfx-stage-time">{{ formatTime(currentTime) }}</span>
      <label class="sfx-stage-seek">
        <span class="sfx-visually-hidden">课程播放进度</span>
        <input type="range" min="0" :max="Math.max(effectiveDuration, 1)" step="0.1" :value="currentTime" :disabled="!mediaElement" @input="seekTo($event.target.value)" />
      </label>
      <span class="sfx-stage-time">{{ formatTime(effectiveDuration) }}</span>

      <SfxButton variant="tertiary" size="sm" :disabled="hasPlaylist ? playlistIndex >= (playlist?.items?.length || 0) - 1 : !currentNode" @click="hasPlaylist ? emit('playlist-next') : emit('node-change', 1)">
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
      </slot>
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
  transition: grid-template-columns var(--duration-normal) var(--ease-out);
}
/* 智能体面板打开时：左侧压缩给 PPT 缩略图，右侧对话获得更多阅读空间 */
.sfx-stage.is-agent-open {
  grid-template-columns: minmax(240px, 0.75fr) minmax(0, 3.25fr);
  gap: var(--space-3);
  padding: var(--space-3);
}

/* 智能体模式下的 PPT 缩略图区域样式 */
.sfx-stage-lecture-ppt {
  min-height: 160px;
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-subtle);
  flex: 1;
  min-height: 0;
}
.sfx-stage-lecture-ppt img {
  width: 100%;
  height: 100%;
  object-fit: contain;
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

.sfx-stage-clock { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); opacity: 0; pointer-events: none; }

.sfx-stage-lecture :deep(.avatar-viewport) {
  position: relative;
  right: auto;
  bottom: auto;
  width: 100%;
  min-width: 0;
  aspect-ratio: auto;
  flex: 1;
  min-height: 180px;
  border-radius: 0;
  border: 0;
}

.sfx-stage-video { flex: 1; min-height: 0; width: 100%; height: 100%; object-fit: contain; background: var(--code-bg); }

.sfx-stage-fallback {
  flex: 1;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-8);
  text-align: center;
  color: var(--code-muted);
  background: var(--code-bg);
}

.sfx-stage-fallback.is-light { color: var(--text-muted); }
.sfx-stage-fallback strong { font-size: var(--ui-md-size); }

.sfx-stage-transcript { min-height: 128px; max-height: 178px; display: flex; flex-direction: column; }
.sfx-stage-transcript-tools { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.sfx-stage-transcript header { padding-block: var(--space-2); }
.sfx-stage-transcript-list { min-height: 0; overflow-y: auto; margin: 0; padding: var(--space-2) var(--space-4); list-style: none; }
.sfx-stage-transcript-list li { padding: var(--space-2) var(--space-3); border-left: 2px solid transparent; color: var(--text-secondary); font-size: var(--ui-sm-size); line-height: 1.65; }
.sfx-stage-transcript-list li.is-active { border-left-color: var(--amber-500); background: var(--amber-100); color: var(--text-primary); }
.sfx-stage-transcript > .sfx-t-caption { padding: var(--space-4); }

.sfx-stage-slide-frame { position:relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; background: var(--surface-cool); overflow: hidden; }
.sfx-stage-slide-frame img { width:100%; height:100%; max-width:100%; max-height:100%; object-fit:contain; }
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
.sfx-stage-controls.is-agent-input {
  padding: 0;
  overflow: hidden;
}
.sfx-stage-controls.is-agent-input :deep(.sfx-agent-input-form) {
  width: 100%;
  border: none;
  border-radius: 0;
}
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
