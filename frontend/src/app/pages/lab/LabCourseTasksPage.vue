<script setup>
import { onMounted, ref, watch } from 'vue'
import { listFacadeCourses } from '@/api/facade.js'
import { listLabCourseTasks } from '@/api/labs.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const tasks = ref([])
const error = ref('')
async function loadCourses() {
  try {
    const [learning, building] = await Promise.all([listFacadeCourses('learning'), listFacadeCourses('building')])
    const unique = new Map()
    for (const course of [...(learning?.items || []), ...(building?.items || [])]) unique.set(String(course.course_id), course)
    courses.value = [...unique.values()]
    courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
    if (!courseId.value) state.value = 'empty'
  } catch (caught) { error.value = caught?.message || ''; state.value = 'error' }
}
async function loadTasks() {
  if (!courseId.value) return
  state.value = 'loading'
  try { const data = await listLabCourseTasks(courseId.value); tasks.value = Array.isArray(data?.items) ? data.items : []; state.value = tasks.value.length ? 'ready' : 'empty' } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || ''; state.value = 'error' }
}
watch(courseId, loadTasks)
onMounted(async () => { await loadCourses(); await loadTasks() })
</script>

<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">课程任务</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">按课程查看已经发布的实验任务。</p></div></header><label v-if="courses.length" class="sfx-t-ui">课程<select v-model="courseId" class="sfx-select task-select"><option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option></select></label><SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取课程任务。'" @retry="loadTasks" /><SfxEmpty v-else-if="state === 'empty'" title="没有课程实验任务" description="选择其他课程，或由有权限的教师先在课程中创建并发布实验。" /><div v-else class="task-list"><article v-for="task in tasks" :key="task.lab_id" class="sfx-panel task-card"><div><h2 class="sfx-t-title3">{{ task.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ task.description || '暂无说明。' }}</p></div><SfxBadge tone="ink">{{ task.language_whitelist?.join(' / ') || '受课程策略控制' }}</SfxBadge></article></div></div></template>

<style scoped>.task-select{margin-left:var(--space-3);min-width:240px}.task-list{display:grid;gap:var(--space-3);margin-top:var(--space-5)}.task-card{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);margin:0}</style>
