<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { confirmBuildReview, runBuildValidation } from '@/api/course_build.js'
import { publishCourseBuild } from '@/api/course_editor.js'
import SfxButton from '@/app/ui/SfxButton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const gate = ref(null)
const message = ref('')
const loading = ref(false)
const reason = ref('教师已查看本次检查结果，并承担在当前状态下正式发布的责任。')

const hasUnresolvedFindings = computed(() => Boolean(
  gate.value && (gate.value.error_count || gate.value.warning_count) && gate.value.requires_teacher_confirmation,
))
const hasBlockers = computed(() => Boolean(gate.value?.blocker_count))
const canPublish = computed(() => Boolean(
  gate.value && gate.value.passed && !hasBlockers.value && !gate.value.requires_teacher_confirmation,
))

async function validate () {
  loading.value = true; message.value = ''
  try { gate.value = await runBuildValidation(courseId.value) } catch (error) { message.value = error?.message || '发布前检查失败' } finally { loading.value = false }
}
async function confirmFindings () {
  if (!gate.value?.gate_run_id || reason.value.trim().length < 3) return
  loading.value = true; message.value = ''
  try {
    const confirmed = await confirmBuildReview(courseId.value, gate.value.gate_run_id, reason.value.trim())
    gate.value = { ...gate.value, ...confirmed, requires_teacher_confirmation: false }
  } catch (error) { message.value = error?.message || '确认检查结果失败' } finally { loading.value = false }
}
async function publish () {
  loading.value = true; message.value = ''
  try {
    const data = await publishCourseBuild(courseId.value, gate.value?.gate_run_id ? { quality_gate_run_id: gate.value.gate_run_id } : {})
    message.value = data?.draft?.editable
      ? '课程已发布，已自动创建下一版可编辑草稿。'
      : (data?.message || '课程已正式发布')
  } catch (error) { message.value = error?.response?.data?.detail?.message || error?.message || '正式发布失败' } finally { loading.value = false }
}
</script>
<template>
  <section class="stage">
    <p>先运行发布前检查。发现的问题会列出；标记为“必须先处理”的问题仍需修复，其他问题可由教师确认后正式发布。</p>
    <div class="actions"><SfxButton variant="primary" :disabled="loading" :loading="loading" @click="validate">{{ loading ? '检查中…' : '运行发布前检查' }}</SfxButton></div>
    <div v-if="gate" class="gate">
      <p>必须先处理 {{ gate.blocker_count || 0 }} 项 · 需教师确认 {{ (gate.error_count || 0) + (gate.warning_count || 0) }} 项</p>
      <ul><li v-for="check in gate.checks || []" :key="check.check_id" :class="check.passed ? 'pass' : check.severity">{{ check.name }}：{{ check.message }}</li></ul>
    </div>
    <div v-if="hasUnresolvedFindings" class="warning">
      <p>请确认你已查看这些问题，并说明为什么仍要正式发布。</p>
      <textarea v-model="reason" rows="3" maxlength="1000" />
      <div class="actions"><SfxButton variant="secondary" size="sm" :disabled="loading || reason.trim().length < 3" @click="confirmFindings">确认检查结果并继续发布</SfxButton></div>
    </div>
    <p v-if="hasBlockers" class="blocked">存在必须先处理的问题，处理完成后才能正式发布。</p>
    <div class="actions"><SfxButton variant="primary" :disabled="loading || !canPublish" :loading="loading" @click="publish">正式发布</SfxButton></div>
    <p v-if="!gate" class="hint">请先运行发布前检查。</p>
    <p v-if="message">{{ message }}</p>
  </section>
</template>
<style scoped>
.stage{padding:0;height:100%;overflow-y:auto}
.actions{display:flex;gap:var(--space-2);margin:var(--space-2) 0}
.gate,.warning,.blocked{margin-top:var(--space-3);padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.gate p{margin:0;font-weight:700}
.gate ul{padding-left:var(--space-4)}
.pass{color:var(--green-700)}
.warning{background:var(--amber-100)}
.warning textarea{box-sizing:border-box;width:100%;padding:var(--space-2)}
.blocked{background:var(--red-100);color:var(--red-700)}
</style>
