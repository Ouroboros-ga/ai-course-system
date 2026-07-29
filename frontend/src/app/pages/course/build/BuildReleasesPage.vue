<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { confirmBuildWarnings, runBuildValidation } from '@/api/course_build.js'
import { publishCourseBuild } from '@/api/course_editor.js'
import SfxButton from '@/app/ui/SfxButton.vue'

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
  <section class="stage">
    <p>先运行质量门禁；Warning 需要教师留下确认原因，ERROR 与 BLOCKER 不可绕过。</p>
    <div class="actions"><SfxButton variant="primary" :disabled="loading" :loading="loading" @click="validate">{{ loading ? '检查中…' : '运行质量检查' }}</SfxButton></div>
    <div v-if="gate" class="gate"><p>BLOCKER {{ gate.blocker_count || 0 }} / ERROR {{ gate.error_count || 0 }} / WARNING {{ gate.warning_count || 0 }}</p><ul><li v-for="check in gate.checks || []" :key="check.check_id" :class="check.passed ? 'pass' : check.severity">{{ check.name }}：{{ check.message }}</li></ul></div>
    <div v-if="gate?.requires_warning_confirmation" class="warning"><textarea v-model="reason" rows="3" maxlength="1000" /><div class="actions"><SfxButton variant="secondary" size="sm" :disabled="loading || reason.trim().length < 3" @click="confirmWarnings">确认 Warning</SfxButton></div></div>
    <div class="actions"><SfxButton variant="primary" :disabled="loading || (gate && !gate.passed)" :loading="loading" @click="publish">发布冻结版本</SfxButton></div>
    <p v-if="message">{{ message }}</p>
  </section>
</template>
<style scoped>
.stage{padding:0;height:100%;overflow-y:auto}
.actions{display:flex;gap:var(--space-2);margin:var(--space-2) 0}
.gate,.warning{margin-top:var(--space-3);padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.gate p{margin:0;font-weight:700}
.gate ul{padding-left:var(--space-4)}
.pass{color:var(--green-700)}
.warning{background:var(--amber-100)}
.warning textarea{box-sizing:border-box;width:100%;padding:var(--space-2)}
</style>
