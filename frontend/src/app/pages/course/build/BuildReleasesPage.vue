<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { confirmBuildWarnings, runBuildValidation } from '@/api/course_build.js'
import { publishCourseBuild } from '@/api/course_editor.js'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const gate = ref(null)
const message = ref('')
const loading = ref(false)
const reason = ref('教师已审阅 Warning，并接受当前发布风险。')

async function validate () {
  loading.value = true; message.value = ''
  try { gate.value = await runBuildValidation(courseId.value) } catch (error) { message.value = error?.message || '质量检查失败' } finally { loading.value = false }
}
async function confirmWarnings () {
  if (!gate.value?.gate_run_id || reason.value.trim().length < 3) return
  loading.value = true; message.value = ''
  try { gate.value = await confirmBuildWarnings(courseId.value, gate.value.gate_run_id, reason.value.trim()) } catch (error) { message.value = error?.message || 'Warning 确认失败' } finally { loading.value = false }
}
async function publish () {
  loading.value = true; message.value = ''
  try {
    const data = await publishCourseBuild(courseId.value, gate.value?.gate_run_id ? { quality_gate_run_id: gate.value.gate_run_id } : {})
    message.value = data?.message || '课程已发布'
  } catch (error) { message.value = error?.response?.data?.detail?.message || error?.message || '发布失败' } finally { loading.value = false }
}
</script>
<template>
  <section class="stage"><p class="eyebrow">Step 10</p><h1>课程发布</h1><p>先运行质量门禁；Warning 需要教师留下确认原因，ERROR 与 BLOCKER 不可绕过。</p>
    <button :disabled="loading" @click="validate">{{ loading ? '检查中…' : '运行质量检查' }}</button>
    <div v-if="gate" class="gate"><p>BLOCKER {{ gate.blocker_count || 0 }} / ERROR {{ gate.error_count || 0 }} / WARNING {{ gate.warning_count || 0 }}</p><ul><li v-for="check in gate.checks || []" :key="check.check_id" :class="check.passed ? 'pass' : check.severity">{{ check.name }}：{{ check.message }}</li></ul></div>
    <div v-if="gate?.requires_warning_confirmation" class="warning"><textarea v-model="reason" rows="3" maxlength="1000" /><button :disabled="loading || reason.trim().length < 3" @click="confirmWarnings">确认 Warning</button></div>
    <button class="publish" :disabled="loading || (gate && !gate.passed)" @click="publish">发布冻结版本</button><p v-if="message">{{ message }}</p>
  </section>
</template>
<style scoped>.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}.eyebrow{color:#64748b;margin:0}h1{margin:4px 0 12px}button{margin:8px 8px 8px 0;padding:9px 16px;border:0;border-radius:7px;background:#1769aa;color:#fff;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}.publish{background:#15803d}.gate,.warning{margin-top:14px;padding:12px;border:1px solid #dbe2ea;border-radius:8px}.gate p{margin:0;font-weight:700}.gate ul{padding-left:20px}.pass{color:#15803d}.warning{background:#fffbeb}.warning textarea{box-sizing:border-box;width:100%;padding:8px}</style>
