<script setup>
import { computed } from 'vue'
import {
  BookOpenText, Captions, Check, ChevronLeft, ChevronRight, FileText,
  Maximize2, NotebookPen, Pause, Play, SkipBack, SkipForward, UserRound, Volume2
} from 'lucide-vue-next'

const props = defineProps({
  mode: { type: String, required: true },
  playing: { type: Boolean, default: false },
  elapsed: { type: Number, required: true },
  duration: { type: Number, required: true },
  rate: { type: Number, default: 1 },
  subtitles: { type: Boolean, default: true },
  activePoint: { type: Object, required: true },
  slidePage: { type: Number, default: 18 },
  guidedSummary: { type: String, required: true },
  transcript: { type: String, required: true },
  note: { type: String, default: '' },
  evidenceLocated: { type: Boolean, default: false }
})

const emit = defineEmits([
  'update:mode', 'toggle-play', 'seek', 'change-rate', 'toggle-subtitles',
  'update:note', 'toggle-focus'
])

const progress = computed(() => Math.min(100, Math.round((props.elapsed / props.duration) * 100)))

const formatTime = (seconds) => {
  const min = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return min + ':' + String(sec).padStart(2, '0')
}

const setModeFromKey = (event) => {
  if (event.key === 'ArrowLeft') emit('update:mode', 'guided')
  if (event.key === 'ArrowRight') emit('update:mode', 'study')
}
</script>

<template>
  <main class="fd-stage" aria-label="学习主舞台">
    <header class="fd-stage__header">
      <div>
        <p class="fd-eyebrow">当前知识点</p>
        <h1>{{ activePoint.title }}</h1>
      </div>
      <div class="fd-stage__tools">
        <div class="fd-mode-switch" role="tablist" aria-label="学习模式" @keydown="setModeFromKey">
          <button
            id="guided-tab"
            type="button"
            role="tab"
            :aria-selected="mode === 'guided'"
            :tabindex="mode === 'guided' ? 0 : -1"
            :class="{ 'is-active': mode === 'guided' }"
            @click="emit('update:mode', 'guided')"
          ><Play :size="15" />跟随讲解</button>
          <button
            id="study-tab"
            type="button"
            role="tab"
            :aria-selected="mode === 'study'"
            :tabindex="mode === 'study' ? 0 : -1"
            :class="{ 'is-active': mode === 'study' }"
            @click="emit('update:mode', 'study')"
          ><NotebookPen :size="15" />课件研习</button>
        </div>
        <button class="fd-icon-button" type="button" aria-label="切换专注模式" @click="emit('toggle-focus')">
          <Maximize2 :size="18" />
        </button>
      </div>
    </header>

    <section
      v-if="mode === 'guided'"
      id="guided-panel"
      class="fd-stage__canvas fd-guided"
      role="tabpanel"
      aria-labelledby="guided-tab"
    >
      <div class="fd-video">
        <div class="fd-video__ambient" aria-hidden="true"></div>
        <div class="fd-presenter" aria-label="数字人课程讲解画面">
          <span class="fd-presenter__avatar"><UserRound :size="64" /></span>
          <strong>课程讲师数字人</strong>
          <span>演示画面 · Mock 数据</span>
        </div>
        <div class="fd-video__context">
          <span>3.4 广度优先遍历（BFS）</span>
          <small>同步到课件第 {{ slidePage }} 页</small>
        </div>
        <p v-if="subtitles" class="fd-subtitle">{{ transcript }}</p>
      </div>
      <article class="fd-guided__summary">
        <div>
          <BookOpenText :size="18" />
          <h2>当前讲解</h2>
        </div>
        <p>{{ guidedSummary }}</p>
        <button class="fd-text-button" type="button" @click="emit('update:mode', 'study')">
          打开课件并记录笔记 <ChevronRight :size="15" />
        </button>
      </article>
    </section>

    <section
      v-else
      id="study-panel"
      class="fd-stage__canvas fd-study"
      role="tabpanel"
      aria-labelledby="study-tab"
    >
      <article class="fd-slide" :class="{ 'is-evidence-located': evidenceLocated }">
        <header>
          <span><FileText :size="16" />课件第 {{ slidePage }} 页</span>
          <span v-if="evidenceLocated" class="fd-evidence-flag"><Check :size="14" />已定位引用</span>
        </header>
        <div class="fd-slide__content">
          <div class="fd-slide__copy">
            <p class="fd-eyebrow">广度优先遍历</p>
            <h2>Breadth-First Search</h2>
            <ol>
              <li>将起始顶点入队并标记为已访问。</li>
              <li>从队首取出顶点，依次检查邻接点。</li>
              <li>未访问邻接点标记后入队，直到队列为空。</li>
            </ol>
          </div>
          <div class="fd-graph" aria-label="BFS 图示：A 依次连接 B、C，再扩展至 D、E、F、G">
            <div class="node node-a">A</div>
            <div class="node node-b">B</div>
            <div class="node node-c">C</div>
            <div class="node node-d">D</div>
            <div class="node node-e">E</div>
            <div class="node node-f">F</div>
            <div class="node node-g">G</div>
            <svg viewBox="0 0 260 180" aria-hidden="true">
              <path d="M130 28 L75 82 M130 28 L185 82 M75 82 L40 145 M75 82 L98 145 M185 82 L162 145 M185 82 L220 145" />
            </svg>
          </div>
        </div>
        <footer>
          <button type="button" aria-label="上一页"><ChevronLeft :size="18" /></button>
          <span>18 / 42</span>
          <button type="button" aria-label="下一页"><ChevronRight :size="18" /></button>
        </footer>
      </article>

      <label class="fd-notes">
        <span><NotebookPen :size="17" />我的笔记 <small>Mock · 仅本页保存</small></span>
        <textarea
          :value="note"
          rows="12"
          placeholder="记录你的理解、疑问或复习要点…"
          @input="emit('update:note', $event.target.value)"
        ></textarea>
        <small><Check :size="13" />已保存在当前原型会话</small>
      </label>
    </section>

    <footer class="fd-player-controls">
      <button type="button" aria-label="后退 10 秒" @click="emit('seek', Math.max(0, elapsed - 10))"><SkipBack :size="18" /></button>
      <button class="fd-player-controls__play" type="button" :aria-label="playing ? '暂停' : '播放'" @click="emit('toggle-play')">
        <component :is="playing ? Pause : Play" :size="19" />
      </button>
      <button type="button" aria-label="前进 10 秒" @click="emit('seek', Math.min(duration, elapsed + 10))"><SkipForward :size="18" /></button>
      <Volume2 :size="17" aria-hidden="true" />
      <span class="fd-time">{{ formatTime(elapsed) }} / {{ formatTime(duration) }}</span>
      <label class="fd-progress-range">
        <span class="fd-sr-only">课程播放进度</span>
        <input
          type="range"
          min="0"
          :max="duration"
          :value="elapsed"
          :style="{ '--progress': progress + '%' }"
          @input="emit('seek', Number($event.target.value))"
        />
      </label>
      <button type="button" @click="emit('change-rate')">{{ rate }}x</button>
      <button type="button" :class="{ 'is-active': subtitles }" :aria-pressed="subtitles" @click="emit('toggle-subtitles')">
        <Captions :size="18" /><span class="fd-control-label">字幕</span>
      </button>
    </footer>
  </main>
</template>
