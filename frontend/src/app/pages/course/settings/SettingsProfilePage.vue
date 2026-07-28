<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { getCourseSettings, updateCourseProfile } from '@/api/course_lifecycle.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const course = computed(() => courseContext.course.value ?? {})
const form = ref({ title: '', description: '' })
const version = ref(null)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
function resetFromCourse() { form.value = { title: course.value.title || '', description: course.value.description || '' } }
async function load() { resetFromCourse(); try { const settings = await getCourseSettings(courseId.value); version.value = settings?.version ?? null; if (settings?.profile) form.value = { ...form.value, ...settings.profile } } catch { /* basic course fields remain editable */ } }
async function save() { saving.value = true; error.value = ''; saved.value = false; try { await updateCourseProfile(courseId.value, form.value, version.value); saved.value = true; await load() } catch (e) { error.value = e?.message || '保存课程资料失败' } finally { saving.value = false } }
watch(course, resetFromCourse, { deep: true }); onMounted(load)
</script>
<template><div class="sfx-profile"><header class="sfx-profile-head"><div><h1 class="sfx-t-title2">基础信息</h1><p class="sfx-t-ui sfx-t-secondary">课程名称、简介与展示资料。保存采用版本校验，避免覆盖其他教师修改。</p></div><SfxBadge :tone="course.status === 'published' ? 'green' : 'amber'">{{ course.status || 'draft' }}</SfxBadge></header><form class="sfx-panel sfx-profile-form" @submit.prevent="save"><label>课程名称<input v-model.trim="form.title" class="sfx-input" maxlength="200" required /></label><label>课程简介<textarea v-model.trim="form.description" class="sfx-input" rows="6" maxlength="4000" /></label><SfxError v-if="error" :description="error"/><p v-if="saved" class="sfx-save-ok">已保存。</p><SfxButton type="submit" :loading="saving">保存基础信息</SfxButton></form></div></template>
<style scoped>.sfx-profile{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-6);max-width:860px}.sfx-profile-head{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--space-3)}.sfx-profile-form{display:grid;gap:var(--space-4)}.sfx-profile-form label{display:grid;gap:var(--space-1)}.sfx-save-ok{color:var(--green-700)}</style>
