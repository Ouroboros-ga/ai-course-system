<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpenCheck, ShieldCheck } from 'lucide-vue-next'
import { createCourseWorkspace } from '@/api/course_build.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const router = useRouter()
const phase = ref('form') // form | creating | accepted | error
const error = ref('')
const course = ref({
  title: '', description: '', subject: '', course_type: '',
  teaching_audience: '', language: 'zh-CN',
})
const record = ref(null)
const canSubmit = computed(() => Boolean(course.value.title.trim()) && phase.value !== 'creating')

async function submit() {
  if (!canSubmit.value) return
  phase.value = 'creating'
  error.value = ''
  try {
    const data = await createCourseWorkspace({ ...course.value, title: course.value.title.trim() })
    if (!data?.course_id) throw new Error('服务器没有返回课程标识。')
    record.value = data
    phase.value = 'accepted'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || '创建课程失败，请稍后重试。'
    phase.value = 'error'
  }
}

function continueBuild() {
  if (!record.value?.course_id) return
  router.push(`/app/course/${record.value.course_id}/build/materials`)
}
function goBuilding() { router.push('/app/courses/building') }
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1"><BookOpenCheck :size="25" /> 创建课程</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">先确定课程定位，再在课程资料页连续上传课件、教材和实验指导。</p></div></header>

    <section v-if="phase !== 'accepted'" class="sfx-panel create-panel">
      <div class="create-intro"><ShieldCheck :size="25" /><div><h2 class="sfx-panel-title">课程基础信息</h2><p class="sfx-t-ui sfx-t-secondary">创建的是一个草稿课程和建设工作区；此时不会上传文件，也不会向学生发布任何内容。</p></div></div>
      <div class="form-grid">
        <label class="sfx-t-ui full">课程名称 <input v-model="course.title" class="sfx-input" maxlength="200" required placeholder="例如：数据结构" /></label>
        <label class="sfx-t-ui">学科 <input v-model="course.subject" class="sfx-input" maxlength="100" placeholder="例如：计算机科学" /></label>
        <label class="sfx-t-ui">课程类型 <input v-model="course.course_type" class="sfx-input" maxlength="100" placeholder="例如：专业基础课" /></label>
        <label class="sfx-t-ui">教学对象 <input v-model="course.teaching_audience" class="sfx-input" maxlength="200" placeholder="例如：本科一年级" /></label>
        <label class="sfx-t-ui">授课语言 <select v-model="course.language" class="sfx-select"><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></label>
        <label class="sfx-t-ui full">课程简介 <textarea v-model="course.description" class="sfx-textarea" rows="4" maxlength="2000" placeholder="简述课程目标、范围或教学特点（可选）" /></label>
      </div>
      <p v-if="phase === 'creating'" class="status" role="status">正在创建课程建设工作区…</p>
      <SfxError v-if="phase === 'error'" :description="error" @retry="submit" />
      <div class="create-actions"><SfxButton variant="tertiary" :disabled="phase === 'creating'" @click="goBuilding">返回我建设的</SfxButton><SfxButton variant="primary" :disabled="!canSubmit" :loading="phase === 'creating'" @click="submit">创建并上传资料</SfxButton></div>
    </section>

    <section v-else class="sfx-panel accepted-panel" aria-live="polite"><ShieldCheck :size="31" /><div><h2 class="sfx-t-title2">草稿课程已创建</h2><p class="sfx-t-ui sfx-t-secondary">课程权限、建设步骤和基础信息已保存。下一步可连续上传多份材料，每一份都会独立进入解析队列。</p><dl class="sfx-desc"><dt>课程状态</dt><dd>草稿（不会出现在课程大厅，也不能设置加入码）</dd><dt>当前步骤</dt><dd>课程资料</dd></dl></div><div class="create-actions"><SfxButton variant="secondary" @click="goBuilding">查看我建设的</SfxButton><SfxButton variant="primary" @click="continueBuild">进入课程资料</SfxButton></div></section>
  </div>
</template>

<style scoped>
.create-panel, .accepted-panel { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-4); }
.create-intro { display:flex; align-items:flex-start; gap:var(--space-3); color:var(--ink-700); }
.create-intro p { margin-top: var(--space-2); line-height: 1.65; }
.form-grid { width:100%; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--space-3); }
.form-grid label { display:grid; gap:var(--space-1); }
.form-grid .full { grid-column:1 / -1; }
.status { margin:0; color:var(--ink-700); }
.create-actions { display:flex; justify-content:flex-end; gap:var(--space-2); width:100%; }
.accepted-panel { max-width:760px; }
.accepted-panel > svg { color:var(--green-700); }
@media (max-width: 640px) { .form-grid { grid-template-columns:1fr; }.form-grid .full { grid-column:auto; }.create-actions { align-items:stretch; flex-direction:column; } }
</style>
