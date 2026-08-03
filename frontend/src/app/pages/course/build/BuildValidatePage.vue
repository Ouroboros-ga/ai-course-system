<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, CircleAlert, Info, ShieldAlert, ShieldCheck } from 'lucide-vue-next'
import { runBuildValidation } from '@/api/course_build.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const status = ref('idle')
const result = ref(null)
const error = ref('')
const summary = computed(() => ({
  blocker: result.value?.blocker_count ?? 0,
  error: result.value?.error_count ?? 0,
  warning: result.value?.warning_count ?? 0,
}))
function severityLabel(check) {
  if (check.passed || check.severity === 'info' || check.severity === 'INFO') return '已通过'
  if (check.severity === 'blocker' || check.severity === 'BLOCKER') return '必须先处理'
  if (check.severity === 'error' || check.severity === 'ERROR') return '教师确认后可发布'
  if (check.severity === 'warning' || check.severity === 'WARNING') return '提醒'
  return '需要关注'
}
function tone(check) { if (check.passed || check.severity === 'info' || check.severity === 'INFO') return 'green'; if (check.severity === 'warning' || check.severity === 'WARNING') return 'amber'; return 'red' }
function icon(check) { if (check.passed) return CheckCircle2; if (check.severity === 'info' || check.severity === 'INFO') return Info; return check.severity === 'warning' || check.severity === 'WARNING' ? CircleAlert : ShieldAlert }
async function run() {
  status.value = 'running'; error.value = ''
  try { result.value = await runBuildValidation(courseId.value); status.value = 'ready' }
  catch (caught) { error.value = caught?.message || '质量检查失败'; status.value = 'error' }
}

watch([status], () => {
  if (workbench) {
    workbench.stageActions = {
      canRefresh: true,
      refreshing: status.value === 'running',
      onRefresh: run,
      refreshLabel: '重新检查',
    }
  }
}, { immediate: true })
onMounted(run)
onBeforeUnmount(() => { if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="validate-stage">
    <div class="gate-summary" :class="{ running: status === 'running' }"><ShieldCheck :size="25" /><div><strong>{{ status === 'running' ? '正在检查课程一致性' : result?.passed ? '草稿已通过检查' : '发现需要关注的发布问题' }}</strong><p>{{ status === 'running' ? '正在核对证据、讲稿、图谱、映射与检索快照。' : `必须先处理 ${summary.blocker} 项 · 需教师确认 ${summary.error + summary.warning} 项` }}</p></div></div>
    <p v-if="error" class="validation-error" role="alert"><CircleAlert :size="16" /> {{ error }}</p>
    <div v-else-if="status === 'running'" class="loading-state">正在运行发布前检查…</div>
    <div v-else-if="result" class="check-wrap">
      <div class="check-list">
        <article v-for="check in result.checks || []" :key="check.check_id" class="check-row" :class="{ failed: !check.passed }"><component :is="icon(check)" :size="19" /><div><header><strong>{{ check.name || check.check_id }}</strong><SfxBadge :tone="tone(check)">{{ severityLabel(check) }}</SfxBadge></header><p>{{ check.message || (check.passed ? '检查通过' : '需要关注') }}</p><code v-if="check.check_id">{{ check.check_id }}</code></div></article>
        <p v-if="!(result.checks || []).length" class="loading-state">后端未返回逐项检查结果。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.validate-stage{display:flex;flex-direction:column;gap:var(--space-4);padding:0;height:100%;overflow:hidden}
.gate-summary{display:flex;gap:var(--space-3);align-items:flex-start;padding:var(--space-4);border:1px solid var(--green-300);border-radius:var(--radius-md);background:var(--green-100);color:var(--green-700);flex-shrink:0}
.gate-summary.running{border-color:var(--ink-300);background:var(--ink-100);color:var(--ink-700)}
.gate-summary strong{color:var(--text-primary);font-size:var(--ui-md-size)}
.gate-summary p{margin:var(--space-1) 0 0;font-size:var(--ui-sm-size)}
.validation-error{display:flex;align-items:center;gap:var(--space-1);margin:0;padding:var(--space-3);border:1px solid var(--red-300);border-radius:var(--radius-md);background:var(--red-100);color:var(--red-700);font-size:var(--ui-sm-size);flex-shrink:0}
.loading-state{margin:0;padding:var(--space-8);color:var(--text-muted);font-size:var(--ui-md-size);text-align:center}
.check-wrap{min-height:0;overflow-y:auto;flex:1}
.check-list{display:grid;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow:hidden}
.check-row{display:grid;grid-template-columns:24px minmax(0,1fr);gap:var(--space-2);padding:var(--space-3) var(--space-4);color:var(--green-700);border-bottom:1px solid var(--border-subtle)}
.check-row:last-child{border-bottom:0}
.check-row.failed{color:var(--red-700);background:var(--red-100)}
.check-row>div{display:grid;gap:var(--space-1)}
.check-row header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2)}
.check-row strong{color:var(--text-primary);font-size:var(--ui-md-size)}
.check-row p{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}
.check-row code{color:var(--text-muted);font-family:var(--font-mono);font-size:11px}
@media(max-width:560px){.validate-stage{padding:var(--space-3)}.check-row{padding:var(--space-3)}}
</style>
