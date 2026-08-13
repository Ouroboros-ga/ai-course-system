<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listFacadeCourses } from '@/api/facade.js'
import { listLabRecords } from '@/api/labs.js'
import { courseExperimentPath } from '@/api/labProjectionContract.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter()
const courses = ref([]); const courseId = ref(''); const state = ref('loading'); const records = ref([]); const error = ref('')
function score(record) { return record.final_score == null ? '未评分' : `${Math.round(record.final_score * 100)}%` }
async function loadCourses() { const [learning, building] = await Promise.all([listFacadeCourses('learning'), listFacadeCourses('building')]); const unique = new Map(); for (const course of [...(learning?.items || []), ...(building?.items || [])]) unique.set(String(course.course_id), course); courses.value = [...unique.values()]; courseId.value = courses.value[0] ? String(courses.value[0].course_id) : '' }
async function load() { if (!courseId.value) { state.value = 'empty'; return }; state.value = 'loading'; try { const data = await listLabRecords(courseId.value); records.value = Array.isArray(data?.items) ? data.items : []; state.value = records.value.length ? 'ready' : 'empty' } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || 'Unable to load trusted experiment records.'; state.value = 'error' } }
function enterExperiment() { router.push(courseExperimentPath(courseId.value)) }
watch(courseId, load)
onMounted(async () => { try { await loadCourses(); await load() } catch (caught) { error.value = caught?.message || 'Unable to load courses.'; state.value = 'error' } })
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">实验记录</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">仅展示服务端终结评测生成的可信记录。</p></div><SfxButton variant="secondary" size="sm" @click="enterExperiment">进入课程实验</SfxButton></header>
    <label v-if="courses.length" class="sfx-course-select sfx-t-ui">课程<select v-model="courseId" class="sfx-select"><option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">{{ course.title }}</option></select></label>
    <SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有可信实验记录" description="取消、自由运行和历史实验室记录不会作为正式记录展示。" />
    <section v-else class="sfx-panel records"><table><thead><tr><th>实验</th><th>结果</th><th>得分</th><th>终结时间</th></tr></thead><tbody><tr v-for="record in records" :key="record.record_id"><td>{{ record.lab_title }}</td><td><SfxBadge :tone="record.passed ? 'green' : 'amber'">{{ record.passed ? '通过' : '未通过' }}</SfxBadge></td><td>{{ score(record) }}</td><td>{{ record.created_at ? new Date(record.created_at).toLocaleString('zh-CN') : '-' }}</td></tr></tbody></table></section>
  </div>
</template>

<style scoped>.sfx-course-select{display:flex;align-items:center;gap:var(--space-3)}.records{overflow-x:auto;margin-top:var(--space-5)}table{width:100%;border-collapse:collapse;font-size:var(--ui-sm-size)}th,td{padding:var(--space-3);border-bottom:1px solid var(--border-subtle);text-align:left;white-space:nowrap}th{color:var(--text-secondary);font-weight:var(--ui-md-weight)}</style>
