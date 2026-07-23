<script setup>
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, FileQuestion, MonitorPlay, Presentation, VideoOff } from 'lucide-vue-next'

/**
 * LEARN 中央课程舞台（page-design §12.4）。
 * 数据全部来自 useLearningWorkspace（真实 player 端点）：
 *  - 有视频 → 原生播放器，时间同步回写全局进度；
 *  - 无视频 → 显式提示（不伪装有数字人），课件/讲稿照常可读；
 *  - 课件：slide 图 → ppt 文本页 → 显式空态，逐级真实回退。
 */
const props = defineProps({
  currentNode: { type: Object, default: null },
  currentVideoUrl: { type: String, default: '' },
  currentSlide: { type: Object, default: null },
  currentPptPage: { type: Object, default: null },
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 },
  isPlaying: { type: Boolean, default: false },
})

const emit = defineEmits(['playback', 'page-change'])

const videoRef = ref(null)
const slideError = ref(false)
const videoFailed = ref(false)

const hasVideo = computed(() => Boolean(props.currentVideoUrl) && !videoFailed.value)

watch(() => props.currentNode?.id, () => {
  slideError.value = false
  videoFailed.value = false
})

watch(() => props.currentSlide?.url, () => {
  slideError.value = false
})

function handleTimeUpdate() {
  const video = videoRef.value
  if (!video || !props.currentNode) return
  emit('playback', {
    globalTime: props.currentNode.timestampStart + video.currentTime,
    isPlaying: !video.paused,
  })
}

function handlePlayState(playing) {
  const video = videoRef.value
  emit('playback', {
    globalTime: props.currentNode
      ? props.currentNode.timestampStart + (video?.currentTime || 0)
      : 0,
    isPlaying: playing,
  })
}

// A5 修复：视频结束时不把 globalTime 推到 nodeEnd（避免 seekTo 自动跳到下一节点）。
// 只发 isPlaying:false 触发暂停保存，节点停留当前末尾，用户可重看或手动切换。
function handleEnded() {
  emit('playback', { isPlaying: false })
}

function handleMediaError() {
  // 媒体失败本地显式呈现（不伪装可播放），课件/讲稿不受影响
  videoFailed.value = true
}
</script>

<template>
  <div class="sfx-stage">
    <section class="sfx-stage-pane sfx-stage-video" aria-label="讲解视频">
      <header class="sfx-stage-pane-label">
        <span><MonitorPlay :size="15" /> 讲解</span>
        <small v-if="currentNode?.mediaStatus !== 'ready'" class="sfx-t-caption">当前节点无可用视频</small>
      </header>

      <div class="sfx-stage-video-frame">
        <video
          v-if="hasVideo"
          ref="videoRef"
          :key="currentVideoUrl"
          :src="currentVideoUrl"
          controls
          playsinline
          preload="metadata"
          @timeupdate="handleTimeUpdate"
          @play="handlePlayState(true)"
          @pause="handlePlayState(false)"
          @ended="handleEnded"
          @error="handleMediaError"
        />
        <div v-else class="sfx-stage-fallback">
          <VideoOff :size="32" :stroke-width="1.6" />
          <strong>{{ videoFailed ? '讲解视频暂时无法播放' : '当前知识点暂无讲解视频' }}</strong>
          <p class="sfx-t-caption">课件与讲解文本仍可正常阅读，不影响学习。</p>
        </div>
      </div>

      <p v-if="currentNode?.content" class="sfx-stage-caption sfx-t-body">
        {{ currentNode.content }}
      </p>
    </section>

    <section class="sfx-stage-pane" aria-label="同步课件">
      <header class="sfx-stage-pane-label">
        <span><Presentation :size="15" /> 同步课件</span>
        <small class="sfx-t-caption">第 {{ currentPage }} / {{ totalPages }} 页</small>
      </header>

      <div class="sfx-stage-slide-frame">
        <img
          v-if="currentSlide && !slideError"
          :key="currentSlide.url"
          :src="currentSlide.url"
          :alt="`课程课件第 ${currentPage} 页`"
          @error="slideError = true"
        />
        <div v-else-if="currentPptPage?.content || currentPptPage?.title" class="sfx-stage-slide-text">
          <span class="sfx-t-caption">第 {{ currentPage }} 页</span>
          <h2 class="sfx-t-title2">{{ currentPptPage.title || currentNode?.title }}</h2>
          <p class="sfx-t-body">{{ currentPptPage.content }}</p>
        </div>
        <div v-else class="sfx-stage-fallback is-light">
          <FileQuestion :size="32" :stroke-width="1.6" />
          <strong>当前页暂无可显示的课件</strong>
          <p class="sfx-t-caption">可从学习轨道切换其他知识点。</p>
        </div>
      </div>

      <nav class="sfx-stage-slide-nav" aria-label="课件翻页">
        <button type="button" class="sfx-stage-nav-btn" :disabled="currentPage <= 1"
                aria-label="上一页课件" @click="emit('page-change', currentPage - 1)">
          <ChevronLeft :size="18" />
        </button>
        <span class="sfx-t-caption">第 {{ currentPage }} 页</span>
        <button type="button" class="sfx-stage-nav-btn" :disabled="currentPage >= totalPages"
                aria-label="下一页课件" @click="emit('page-change', currentPage + 1)">
          <ChevronRight :size="18" />
        </button>
      </nav>
    </section>
  </div>
</template>

<style scoped>
.sfx-stage {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--surface-canvas);
  overflow: auto;
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

.sfx-stage-pane-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.sfx-stage-video-frame {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--code-bg);
  display: flex;
  align-items: center;
  justify-content: center;
}

.sfx-stage-video-frame video {
  width: 100%;
  height: 100%;
  object-fit: contain;
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

.sfx-stage-caption {
  padding: var(--space-4);
  color: var(--text-primary);
  border-top: 1px solid var(--border-subtle);
  overflow-y: auto;
  max-height: 180px;
}

.sfx-stage-slide-frame {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-cool);
  overflow: hidden;
}

.sfx-stage-slide-frame img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.sfx-stage-slide-text {
  padding: var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow-y: auto;
  max-height: 100%;
}

.sfx-stage-slide-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.sfx-stage-nav-btn {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--ink-700);
}

.sfx-stage-nav-btn:hover:not(:disabled) { background: var(--ink-100); }
.sfx-stage-nav-btn:disabled { color: var(--text-disabled); cursor: not-allowed; }

@media (max-width: 1100px) {
  .sfx-stage { grid-template-columns: 1fr; overflow-y: auto; }
}
</style>
