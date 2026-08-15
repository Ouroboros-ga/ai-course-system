<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listLabCourseTasks, listExperimentCourses } from '@/api/labs.js'
import { courseExperimentPath } from '@/api/labProjectionContract.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter()
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const tasks = ref([])
const error = ref('')

async function loadCourses() {
  courses.value = await listExperimentCourses()
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
}

async function loadTasks() {
  if (!courseId.value) { state.value = 'empty'; return }
  state.value = 'loading'
  try {
    const data = await listLabCourseTasks(courseId.value)
    tasks.value = Array.isArray(data?.items) ? data.items : []
    state.value = tasks.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || 'Unable to load course experiments.'
    state.value = 'error'
  }
}

function enterExperiment() { router.push(courseExperimentPath(courseId.value)) }

watch(courseId, loadTasks)
onMounted(async () => {
  try { await loadCourses(); await loadTasks() } catch (caught) { error.value = caught?.message || 'Unable to load courses.'; state.value = 'error' }
})
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">课程任务</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">查看已发布实验及你的推荐、尝试和可信结果。</p></div></header>
    <label v-if="courses.length" class="sfx-course-select sfx-t-ui">课程<select v-model="courseId" class="sfx-select"><option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option></select></label>
    <SfxSkeleton v-if="state === 'loading'" :lines="4" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="loadTasks" />
    <SfxEmpty v-else-if="state === 'empty'" title="没有课程实验任务" description="有权限的教师发布实验后会显示在这里。" />
    <div v-else class="task-list">
      <article v-for="task in tasks" :key="task.experiment_id" class="sfx-panel task-card">
        <div><h2 class="sfx-t-title3">{{ task.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ task.description || '暂无说明。' }}</p><p v-if="task.last_attempt_status" class="sfx-t-caption sfx-t-secondary">最近尝试：{{ task.last_attempt_status }}</p></div>
        <div class="task-actions"><SfxBadge v-if="task.recommended" tone="ink">已推荐</SfxBadge><SfxBadge v-else-if="task.passed" tone="green">已通过</SfxBadge><SfxButton variant="secondary" size="sm" @click="enterExperiment">进入</SfxButton></div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.sfx-course-select { display: flex; align-items: center; gap: var(--space-3); }.task-list { display: grid; gap: var(--space-3); margin-top: var(--space-5); }.task-card { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin: 0; }.task-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
</style>
