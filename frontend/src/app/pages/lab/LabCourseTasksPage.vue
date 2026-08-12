<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listFacadeCourses } from '@/api/facade.js'
import { listLabCourseTasks } from '@/api/labs.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter(); const courses = ref([]); const courseId = ref(''); const state = ref('loading'); const tasks = ref([]); const error = ref('')
async function loadCourses() { try { const [learning, building] = await Promise.all([listFacadeCourses('learning'), listFacadeCourses('building')]); const unique = new Map(); for (const course of [...(learning?.items || []), ...(building?.items || [])]) unique.set(String(course.course_id), course); courses.value = [...unique.values()]; courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''; if (!courseId.value) state.value = 'empty' } catch (reason) { error.value = reason?.message || ''; state.value = 'error' } }
async function loadTasks() { if (!courseId.value) return; state.value = 'loading'; try { const data = await listLabCourseTasks(courseId.value); tasks.value = data?.items || []; state.value = tasks.value.length ? 'ready' : 'empty' } catch (reason) { error.value = reason?.response?.data?.detail?.message || reason?.message || ''; state.value = 'error' } }
watch(courseId, loadTasks); onMounted(async () => { await loadCourses(); await loadTasks() })
</script>

<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">课程任务</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">查看同一课程的已发布实验投影。</p></div></header><label v-if="courses.length" class="sfx-t-ui">课程<select v-model="courseId" class="sfx-select task-select"><option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option></select></label><SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取课程任务。'" @retry="loadTasks" /><SfxEmpty v-else-if="state === 'empty'" title="没有课程实验任务" description="教师完成参考解验证并发布后，任务会显示在这里。" /><div v-else class="task-list"><article v-for="task in tasks" :key="task.lab_id" class="sfx-panel task-card"><div><h2 class="sfx-t-title3">{{ task.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ task.description || '暂无说明。' }}</p><p v-if="task.last_attempt_id" class="sfx-t-caption">最近结果：{{ task.passed ? '通过' : '未通过' }}</p></div><div class="task-actions"><SfxBadge tone="ink">{{ task.language_whitelist?.join(' / ') || '受课程策略控制' }}</SfxBadge><SfxButton size="sm" @click="router.push(`/app/course/${task.course_id}/experiments`)">进入实验</SfxButton></div></article></div></div></template>

<style scoped>.task-select{margin-left:var(--space-3);min-width:240px}.task-list{display:grid;gap:var(--space-3);margin-top:var(--space-5)}.task-card{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);margin:0}.task-actions{display:flex;align-items:flex-end;flex-direction:column;gap:var(--space-2)}</style>
