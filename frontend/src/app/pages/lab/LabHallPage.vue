<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { FlaskConical } from 'lucide-vue-next'
import { listLabCatalog, listExperimentCourses } from '@/api/labs.js'
import { courseExperimentPath } from '@/api/labProjectionContract.js'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter()
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const experiments = ref([])
const sandbox = ref(null)
const languages = ref([])
const error = ref('')

async function loadCourses() {
  courses.value = await listExperimentCourses()
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
}

async function load() {
  if (!courseId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const [catalog, health, supported] = await Promise.all([
      listLabCatalog(courseId.value),
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
    ])
    experiments.value = Array.isArray(catalog?.items) ? catalog.items : []
    sandbox.value = health
    languages.value = Array.isArray(supported?.languages) ? supported.languages : []
    state.value = experiments.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || 'Unable to load course experiment projections.'
    state.value = 'error'
  }
}

function enterExperiment() {
  router.push(courseExperimentPath(courseId.value))
}

watch(courseId, load)
onMounted(async () => {
  try {
    await loadCourses()
    await load()
  } catch (caught) {
    error.value = caught?.message || 'Unable to load available courses.'
    state.value = 'error'
  }
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">实验室大厅</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">浏览课程中已发布的编程实验投影。</p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="sfx-course-select sfx-t-ui">
      课程
      <select v-model="courseId" class="sfx-select">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option>
      </select>
    </label>

    <section class="sfx-panel environment">
      <div>
        <h2 class="sfx-panel-title"><FlaskConical :size="18" /> 代码运行环境</h2>
        <p class="sfx-t-ui sfx-t-secondary">正式结果只由课程实验的服务端终结流程生成。</p>
      </div>
      <SfxBadge :tone="sandbox?.available ? 'green' : 'amber'">{{ sandbox?.available ? '沙箱可用' : '沙箱暂不可用' }}</SfxBadge>
      <p v-if="languages.length" class="sfx-t-caption sfx-t-secondary">支持 {{ languages.length }} 种语言</p>
    </section>

    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="暂无课程实验" description="只有已发布的课程实验会在这里出现。" />
    <div v-else class="lab-grid">
      <article v-for="experiment in experiments" :key="experiment.experiment_id" class="sfx-panel lab-card">
        <div class="lab-card-head">
          <h2 class="sfx-t-title3">{{ experiment.title }}</h2>
          <SfxBadge tone="ink">课程实验</SfxBadge>
        </div>
        <p class="sfx-t-ui sfx-t-secondary">{{ experiment.description || '暂无实验说明。' }}</p>
        <p class="sfx-t-caption sfx-t-secondary">{{ experiment.language_whitelist?.join(' / ') || '语言由课程策略控制' }}</p>
        <SfxButton variant="primary" size="sm" @click="enterExperiment">进入课程实验</SfxButton>
      </article>
    </div>
  </div>
</template>

<style scoped>
.sfx-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.environment { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-6); }
.environment > div { flex: 1; }
.lab-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-4); }
.lab-card { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-3); margin: 0; }
.lab-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); width: 100%; }
</style>
