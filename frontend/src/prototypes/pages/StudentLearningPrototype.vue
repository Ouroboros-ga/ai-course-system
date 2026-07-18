<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Bot, ChevronLeft, Focus, ListTree, RotateCcw } from 'lucide-vue-next'
import CourseOutlinePanel from '../components/CourseOutlinePanel.vue'
import LearningAgentPanel from '../components/LearningAgentPanel.vue'
import LearningStage from '../components/LearningStage.vue'
import { studentCourseMock } from '../mock/frontendDesignMocks.js'
import '../styles/frontend-design.css'

const router = useRouter()
const course = ref(structuredClone(studentCourseMock))
const activePoint = ref(course.value.chapters[2].points[3])
const mode = ref('guided')
const playing = ref(false)
const elapsed = ref(course.value.currentTime)
const rate = ref(1)
const subtitles = ref(true)
const note = ref(course.value.note)
const compactInitial = window.innerWidth < 1100
const outlineOpen = ref(!compactInitial)
const agentOpen = ref(!compactInitial)
const query = ref('')
const focusMode = ref(false)
const generating = ref(false)
const evidenceLocated = ref(false)
const feedbackMessage = ref('')
const anchor = ref(null)
let playTimer
let answerTimer

const currentLabel = computed(() => anchor.value
  ? '补学中 · ' + activePoint.value.title
  : course.value.chapterLabel
)

const toggleChapter = (id) => {
  const chapter = course.value.chapters.find((item) => item.id === id)
  if (chapter) chapter.expanded = !chapter.expanded
}

const selectPoint = (point) => {
  activePoint.value = point
  elapsed.value = 0
  playing.value = false
  if (window.innerWidth < 900) outlineOpen.value = false
}

const cycleRate = () => {
  const values = [1, 1.25, 1.5, 2]
  rate.value = values[(values.indexOf(rate.value) + 1) % values.length]
}

const ask = () => {
  generating.value = true
  clearTimeout(answerTimer)
  answerTimer = window.setTimeout(() => {
    generating.value = false
  }, 900)
}

const locateCitation = () => {
  mode.value = 'study'
  evidenceLocated.value = true
  if (window.innerWidth < 1100) agentOpen.value = false
}

const startPrerequisite = () => {
  if (!anchor.value) {
    anchor.value = {
      point: activePoint.value,
      elapsed: elapsed.value,
      mode: mode.value,
      questionContext: course.value.answer.question
    }
  }
  activePoint.value = course.value.chapters[1].points[0]
  elapsed.value = 86
  mode.value = 'guided'
  playing.value = false
  if (window.innerWidth < 900) {
    outlineOpen.value = false
    agentOpen.value = false
  }
}

const returnToAnchor = () => {
  if (!anchor.value) return
  activePoint.value = anchor.value.point
  elapsed.value = anchor.value.elapsed
  mode.value = anchor.value.mode
  anchor.value = null
}

const toggleFocus = () => {
  focusMode.value = !focusMode.value
  outlineOpen.value = !focusMode.value
  agentOpen.value = !focusMode.value
}

onMounted(() => {
  playTimer = window.setInterval(() => {
    if (!playing.value) return
    elapsed.value = Math.min(course.value.duration, elapsed.value + rate.value)
    if (elapsed.value >= course.value.duration) playing.value = false
  }, 1000)
})

onBeforeUnmount(() => {
  clearInterval(playTimer)
  clearTimeout(answerTimer)
})
</script>

<template>
  <div class="fd-workspace fd-student-workspace" :class="{ 'is-focus': focusMode }">
    <header class="fd-workspace-topbar">
      <div class="fd-topbar__context">
        <button class="fd-icon-button" type="button" aria-label="返回我的课程" @click="router.push('/student')">
          <ChevronLeft :size="19" />
        </button>
        <span class="fd-course-icon"><BookOpen :size="18" /></span>
        <div>
          <strong>{{ course.name }}</strong>
          <span>{{ currentLabel }}</span>
        </div>
        <span class="fd-prototype-mark">设计原型 · Mock 数据</span>
      </div>

      <div class="fd-topbar__progress" aria-label="学习进度 42%">
        <span>学习进度</span>
        <div><i :style="{ width: course.progress + '%' }"></i></div>
        <strong>{{ course.progress }}%</strong>
      </div>

      <div class="fd-topbar__actions">
        <span class="fd-saved-state">● {{ course.savedAt }}</span>
        <button class="fd-topbar-button" type="button" :aria-expanded="outlineOpen" @click="outlineOpen = !outlineOpen">
          <ListTree :size="17" /><span>目录</span>
        </button>
        <button class="fd-topbar-button" type="button" :aria-expanded="agentOpen" @click="agentOpen = !agentOpen">
          <Bot :size="17" /><span>智能体</span>
        </button>
        <button class="fd-topbar-button" type="button" :aria-pressed="focusMode" @click="toggleFocus">
          <Focus :size="17" /><span>{{ focusMode ? '退出专注' : '专注' }}</span>
        </button>
      </div>
    </header>

    <div class="fd-workspace-body" :class="{ 'is-left-collapsed': !outlineOpen, 'is-right-collapsed': !agentOpen }">
      <div v-if="outlineOpen || agentOpen" class="fd-drawer-mask" @click="outlineOpen = false; agentOpen = false"></div>

      <CourseOutlinePanel
        v-if="outlineOpen"
        :chapters="course.chapters"
        :active-id="activePoint.id"
        :query="query"
        :prerequisite="course.prerequisite"
        :mobile="true"
        @update:query="query = $event"
        @select="selectPoint"
        @toggle-chapter="toggleChapter"
        @start-prerequisite="startPrerequisite"
        @close="outlineOpen = false"
      />

      <div v-else class="fd-collapsed-rail fd-collapsed-rail--left">
        <button type="button" aria-label="展开课程目录" @click="outlineOpen = true"><ListTree :size="18" /></button>
      </div>

      <LearningStage
        v-model:mode="mode"
        :playing="playing"
        :elapsed="elapsed"
        :duration="course.duration"
        :rate="rate"
        :subtitles="subtitles"
        :active-point="activePoint"
        :slide-page="course.slidePage"
        :guided-summary="course.guidedSummary"
        :transcript="course.transcript"
        :note="note"
        :evidence-located="evidenceLocated"
        @toggle-play="playing = !playing"
        @seek="elapsed = $event"
        @change-rate="cycleRate"
        @toggle-subtitles="subtitles = !subtitles"
        @update:note="note = $event"
        @toggle-focus="toggleFocus"
      />

      <LearningAgentPanel
        v-if="agentOpen"
        :answer="course.answer"
        :suggestions="course.suggestedQuestions"
        :generating="generating"
        :mobile="true"
        :anchor-active="Boolean(anchor)"
        @ask="ask"
        @locate="locateCitation"
        @feedback="feedbackMessage = '感谢反馈，原型已记录'"
        @start-prerequisite="startPrerequisite"
        @return-anchor="returnToAnchor"
        @close="agentOpen = false"
      />

      <div v-else class="fd-collapsed-rail fd-collapsed-rail--right">
        <button type="button" aria-label="展开课程智能体" @click="agentOpen = true"><Bot :size="18" /></button>
      </div>
    </div>

    <div v-if="anchor" class="fd-learning-anchor">
      <div>
        <RotateCcw :size="17" />
        <span>补学锚点</span>
        <strong>{{ anchor.point.title }} · {{ Math.floor(anchor.elapsed / 60) }}:{{ String(Math.floor(anchor.elapsed % 60)).padStart(2, '0') }}</strong>
      </div>
      <button type="button" @click="returnToAnchor">返回原讲解位置</button>
    </div>

    <p v-if="feedbackMessage" class="fd-toast" role="status">{{ feedbackMessage }}</p>
  </div>
</template>
