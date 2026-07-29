<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, CircleAlert, Info, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-vue-next'
import { runBuildValidation } from '@/api/course_build.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const status = ref('idle')
const result = ref(null)
const error = ref('')
const summary = computed(() => ({
  blocker: result.value?.blocker_count ?? 0,
  error: result.value?.error_count ?? 0,
  warning: result.value?.warning_count ?? 0,
}))
function tone(check) { if (check.passed) return 'green'; if (check.severity === 'WARNING') return 'amber'; return 'red' }
function icon(check) { if (check.passed) return CheckCircle2; if (check.severity === 'INFO') return Info; return check.severity === 'WARNING' ? CircleAlert : ShieldAlert }
async function run() {
  status.value = 'running'; error.value = ''
  try { result.value = await runBuildValidation(courseId.value); status.value = 'ready' }
  catch (caught) { error.value = caught?.message || '质量检查失败'; status.value = 'error' }
}
onMounted(run)
</script>

<template>
  <section class="validate-stage">
    <header class="validate-head"><div><h2>发布前质量检查</h2><p>检查结果按阻断、错误、警告与提示分级。只有 Warning 可以由教师在发布时明确确认。</p></div><SfxButton :loading="status === 'running'" @click="run"><RefreshCw :size="16" /> 重新检查</SfxButton></header>
    <div class="gate-summary" :class="{ running: status === 'running' }"><ShieldCheck :size="25" /><div><strong>{{ status === 'running' ? '正在检查课程一致性' : result?.passed ? '当前草稿可进入教师审核' : '发现需要处理的发布问题' }}</strong><p>{{ status === 'running' ? '正在核对证据、讲稿、图谱、映射与检索快照。' : `BLOCKER ${summary.blocker} · ERROR ${summary.error} · WARNING ${summary.warning}` }}</p></div></div>
    <p v-if="error" class="validation-error" role="alert"><CircleAlert :size="16" /> {{ error }}</p>
    <div v-else-if="status === 'running'" class="loading-state">正在从后端运行质量门禁…</div>
    <div v-else-if="result" class="check-list">
      <article v-for="check in result.checks || []" :key="check.check_id" class="check-row" :class="{ failed: !check.passed }"><component :is="icon(check)" :size="19" /><div><header><strong>{{ check.name || check.check_id }}</strong><SfxBadge :tone="tone(check)">{{ check.passed ? '已通过' : check.severity }}</SfxBadge></header><p>{{ check.message || (check.passed ? '检查通过' : '需要教师处理') }}</p><code v-if="check.check_id">{{ check.check_id }}</code></div></article>
      <p v-if="!(result.checks || []).length" class="loading-state">后端未返回逐项检查结果。</p>
    </div>
  </section>
</template>

<style scoped>
.validate-stage{display:grid;gap:var(--space-4);padding:var(--space-5);background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-lg)}.validate-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);padding-bottom:var(--space-4);border-bottom:1px solid var(--border-default)}.validate-head h2{margin:0;color:var(--text-primary);font-size:var(--title-3-size)}.validate-head p{max-width:700px;margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.gate-summary{display:flex;gap:var(--space-3);align-items:flex-start;padding:var(--space-4);border:1px solid var(--green-300);border-radius:var(--radius-md);background:var(--green-100);color:var(--green-700)}.gate-summary.running{border-color:var(--ink-300);background:var(--ink-100);color:var(--ink-700)}.gate-summary strong{color:var(--text-primary);font-size:var(--ui-md-size)}.gate-summary p{margin:var(--space-1) 0 0;font-size:var(--ui-sm-size)}.validation-error{display:flex;align-items:center;gap:var(--space-1);margin:0;padding:var(--space-3);border:1px solid var(--red-300);border-radius:var(--radius-md);background:var(--red-100);color:var(--red-700);font-size:var(--ui-sm-size)}.loading-state{margin:0;padding:var(--space-8);color:var(--text-muted);font-size:var(--ui-md-size);text-align:center}.check-list{display:grid;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow:hidden}.check-row{display:grid;grid-template-columns:24px minmax(0,1fr);gap:var(--space-2);padding:var(--space-3) var(--space-4);color:var(--green-700);border-bottom:1px solid var(--border-subtle)}.check-row:last-child{border-bottom:0}.check-row.failed{color:var(--red-700);background:var(--red-100)}.check-row>div{display:grid;gap:var(--space-1)}.check-row header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2)}.check-row strong{color:var(--text-primary);font-size:var(--ui-md-size)}.check-row p{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.check-row code{color:var(--text-muted);font-family:var(--font-mono);font-size:11px}@media(max-width:560px){.validate-stage{padding:var(--space-3)}.validate-head{align-items:stretch;flex-direction:column}.validate-head :deep(.sfx-btn){width:100%}.check-row{padding:var(--space-3)}}
</style>
