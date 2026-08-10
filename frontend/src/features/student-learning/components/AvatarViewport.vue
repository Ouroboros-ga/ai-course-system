<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { UserRound } from 'lucide-vue-next'

import { browserAvatarCapability, resolveAvatarFrame, selectAvatarPlaybackMode } from '../adapters/avatarPlaybackAdapter.js'

const props = defineProps({
  cues: { type: Object, default: null },
  spriteManifest: { type: Object, default: null },
  currentTime: { type: Number, default: 0 },
  audioElement: { type: Object, default: null },
  defaultPlaybackMode: { type: String, default: 'auto' },
  assetSource: { type: String, default: 'platform' },
})

const emit = defineEmits(['status-change', 'metrics'])

const rendererHost = ref(null)
const renderStatus = ref('idle')
const activeMode = ref('compatibility')
let renderer = null
let RendererClass = null
let audioFrameRequest = 0
let boundAudioElement = null

const requestedMode = computed(() => selectAvatarPlaybackMode(
  props.defaultPlaybackMode,
  browserAvatarCapability(),
))
const shouldRender = computed(() => Boolean(props.cues && props.spriteManifest && requestedMode.value !== 'compatibility'))
const isPrecise = computed(() => props.cues?.timing?.precision === 'phoneme')
const statusLabel = computed(() => {
  if (renderStatus.value === 'ready') return isPrecise.value ? '音素同步' : '字级同步'
  if (renderStatus.value === 'initializing') return '正在加载'
  return '静态兼容'
})

function destroyRenderer() {
  stopAudioFrameSampling()
  bindAudioElement(null)
  renderer?.destroy()
  renderer = null
}

function updateFrame(timeSeconds = props.currentTime) {
  if (!renderer || !props.cues) return
  const timeMs = Math.max(0, Number(timeSeconds) || 0) * 1000
  renderer.setFrame({ ...resolveAvatarFrame(props.cues, timeMs), timeMs })
}

function sampleAudioFrame() {
  audioFrameRequest = 0
  const audio = props.audioElement
  if (!renderer || !audio || audio.paused || audio.ended) return
  // requestAnimationFrame is only a sampling trigger.  The HTMLAudioElement
  // remains the single timeline source, so Pixi never advances independently.
  updateFrame(audio.currentTime)
  audioFrameRequest = requestAnimationFrame(sampleAudioFrame)
}

function startAudioFrameSampling() {
  if (audioFrameRequest || !renderer || !props.audioElement || props.audioElement.paused) return
  audioFrameRequest = requestAnimationFrame(sampleAudioFrame)
}

function stopAudioFrameSampling() {
  if (audioFrameRequest) cancelAnimationFrame(audioFrameRequest)
  audioFrameRequest = 0
}

function bindAudioElement(audio) {
  if (boundAudioElement === audio) {
    startAudioFrameSampling()
    return
  }
  if (boundAudioElement) {
    boundAudioElement.removeEventListener('play', startAudioFrameSampling)
    boundAudioElement.removeEventListener('pause', stopAudioFrameSampling)
    boundAudioElement.removeEventListener('ended', stopAudioFrameSampling)
  }
  boundAudioElement = audio || null
  if (boundAudioElement) {
    boundAudioElement.addEventListener('play', startAudioFrameSampling)
    boundAudioElement.addEventListener('pause', stopAudioFrameSampling)
    boundAudioElement.addEventListener('ended', stopAudioFrameSampling)
  }
  if (boundAudioElement) startAudioFrameSampling()
}

async function initialise() {
  destroyRenderer()
  if (!props.cues) return
  activeMode.value = requestedMode.value
  if (!shouldRender.value) {
    renderStatus.value = 'compatibility'
    emit('status-change', { status: renderStatus.value, mode: activeMode.value })
    return
  }
  await nextTick()
  if (!rendererHost.value) return
  renderStatus.value = 'initializing'
  emit('status-change', { status: renderStatus.value, mode: activeMode.value })
  try {
    if (!RendererClass) ({ Sprite2DRenderer: RendererClass } = await import('../renderers/Sprite2DRenderer.js'))
    renderer = new RendererClass({
      container: rendererHost.value,
      quality: activeMode.value,
      onMetrics: metrics => emit('metrics', metrics),
    })
    await renderer.init(props.spriteManifest)
    renderStatus.value = 'ready'
    updateFrame()
    bindAudioElement(props.audioElement)
  } catch {
    destroyRenderer()
    activeMode.value = 'compatibility'
    renderStatus.value = 'compatibility'
  }
  emit('status-change', { status: renderStatus.value, mode: activeMode.value })
}

onMounted(initialise)
onBeforeUnmount(destroyRenderer)

watch(
  [() => props.cues, () => props.spriteManifest, requestedMode],
  initialise,
)
watch(() => props.currentTime, updateFrame)
watch(() => props.audioElement, bindAudioElement, { immediate: true })
</script>

<template>
  <aside class="avatar-viewport" :class="`is-${renderStatus}`" aria-label="数字人讲师">
    <div ref="rendererHost" class="avatar-viewport-canvas" :hidden="renderStatus !== 'ready'" />
    <div v-if="renderStatus !== 'ready'" class="avatar-viewport-static" aria-hidden="true">
      <span class="avatar-static-head"><UserRound :size="38" :stroke-width="1.5" /></span>
      <span class="avatar-static-body" />
    </div>
    <div class="avatar-viewport-meta">
      <span>{{ assetSource === 'none' ? '静态占位' : (assetSource === 'platform' ? '平台预制讲师' : '已发布形象') }}</span>
      <small>{{ statusLabel }}</small>
    </div>
  </aside>
</template>

<style scoped>
.avatar-viewport {
  position: absolute;
  right: var(--space-4);
  bottom: var(--space-4);
  width: min(32%, 196px);
  min-width: 128px;
  aspect-ratio: 4 / 5;
  display: flex;
  align-items: stretch;
  justify-content: center;
  overflow: hidden;
  border: 1px solid rgb(232 238 244 / 35%);
  border-radius: var(--radius-lg);
  background: rgb(16 26 49 / 88%);
}

.avatar-viewport-canvas { width: 100%; height: 100%; }
.avatar-viewport-canvas :deep(.sprite2d-canvas) { display: block; width: 100%; height: 100%; }

.avatar-viewport-static {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  overflow: hidden;
  background: var(--ink-900);
}

.avatar-static-head {
  position: absolute;
  top: 19%;
  width: 70px;
  height: 70px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--amber-100);
  color: var(--ink-900);
}

.avatar-static-body {
  width: 82%;
  height: 43%;
  border-radius: 48% 48% 0 0;
  background: var(--ink-700);
}

.avatar-viewport-meta {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  justify-content: space-between;
  gap: var(--space-1);
  padding: 5px var(--space-2);
  background: rgb(16 26 49 / 72%);
  color: var(--text-inverse);
  font-size: var(--caption-size);
}

.avatar-viewport-meta small { color: var(--ink-100); font: inherit; }

@media (max-width: 760px) {
  .avatar-viewport { right: var(--space-3); bottom: var(--space-3); width: 136px; min-width: 0; }
  .avatar-viewport-meta { font-size: 11px; }
}
</style>
