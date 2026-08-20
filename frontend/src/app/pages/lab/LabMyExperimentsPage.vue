<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listMyLabs, listExperimentCourses } from '@/api/labs.js'
import { courseExperimentPath } from '@/api/labProjectionContract.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter()
const courses = ref([]); const courseId = ref(''); const state = ref('loading'); const experiments = ref([]); const error = ref('')
async function loadCourses() { courses.value = await listExperimentCourses(); courseId.value = courses.value[0] ? String(courses.value[0].course_id) : '' }
async function load() { if (!courseId.value) { state.value = 'empty'; return }; state.value = 'loading'; try { const data = await listMyLabs(courseId.value); experiments.value = Array.isArray(data?.items) ? data.items : []; state.value = experiments.value.length ? 'ready' : 'empty' } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || 'Unable to load your experiments.'; state.value = 'error' } }
function enterExperiment() { router.push(courseExperimentPath(courseId.value)) }
watch(courseId, load)
onMounted(async () => { try { await loadCourses(); await load() } catch (caught) { error.value = caught?.message || 'Unable to load courses.'; state.value = 'error' } })
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">我的实验</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">来自教师推荐与本人尝试的课程实验。</p></div></header>
    <label v-if="courses.length" class="sfx-course-select sfx-t-ui">课程<select v-model="courseId" class="sfx-select"><option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option></select></label>
    <SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有实验" description="教师推荐或开始课程实验后，会在这里显示。" />
    <div v-else class="experiment-list"><article v-for="experiment in experiments" :key="experiment.experiment_id" class="sfx-panel experiment-card"><div><h2 class="sfx-t-title3">{{ experiment.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ experiment.description || '暂无说明。' }}</p></div><div class="experiment-actions"><SfxBadge v-if="experiment.recommended" tone="ink">已推荐</SfxBadge><SfxBadge v-if="experiment.last_attempt_status" tone="neutral">{{ experiment.last_attempt_status }}</SfxBadge><SfxButton variant="secondary" size="sm" @click="enterExperiment">继续</SfxButton></div></article></div>
  </div>
</template>

<style scoped>.sfx-course-select{display:flex;align-items:center;gap:var(--space-3)}.experiment-list{display:grid;gap:var(--space-3);margin-top:var(--space-5)}.experiment-card{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);margin:0}.experiment-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:var(--space-2)}@media(max-width:760px){.experiment-card{flex-direction:column;align-items:stretch}.experiment-actions{justify-content:flex-start}}</style>
