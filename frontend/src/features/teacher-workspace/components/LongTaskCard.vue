<template>
  <article class="task-card" :class="`tone-${meta.tone}`" :aria-label="`${task.title}：${meta.label}`">
    <div class="task-head">
      <div>
        <p class="eyebrow">长任务</p>
        <h3>{{ task.title }}</h3>
      </div>
      <span class="status" :class="`status-${meta.tone}`">{{ meta.label }}</span>
    </div>
    <div v-if="task.progress !== null" class="progress-block">
      <div class="progress-label"><span>{{ task.message || '后台会继续处理，可离开本页。' }}</span><strong>{{ task.progress }}%</strong></div>
      <div class="track" aria-hidden="true"><span :style="{ width: `${task.progress}%` }"></span></div>
    </div>
    <p v-else class="task-note">{{ task.message || '尚未返回进度；刷新状态以获取最新结果。' }}</p>
    <p v-if="task.total > 0" class="counts">已完成 {{ task.completed }}/{{ task.total }}</p>
    <div class="task-actions">
      <button type="button" class="quiet-button" :disabled="loading" @click="$emit('refresh')"><RefreshCw :size="15" />刷新</button>
      <button v-if="task.canRetry" type="button" class="retry-button" :disabled="loading" @click="$emit('retry')"><RotateCcw :size="15" />重新执行</button>
      <button v-if="task.requiresReview" type="button" class="confirm-button" :disabled="loading" @click="$emit('confirm')"><Check :size="15" />教师确认</button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { Check, RefreshCw, RotateCcw } from 'lucide-vue-next'
import { taskStatusMeta } from '../taskStatus.js'

const props = defineProps({ task: { type: Object, required: true }, loading: Boolean })
defineEmits(['refresh', 'retry', 'confirm'])
const meta = computed(() => taskStatusMeta[props.task.status] || taskStatusMeta.pending)
</script>

<style scoped>
.task-card{border:1px solid var(--color-border);border-left:3px solid var(--color-primary);border-radius:12px;background:var(--color-surface);padding:16px}.tone-success{border-left-color:var(--color-success)}.tone-warning{border-left-color:var(--color-warning)}.tone-danger{border-left-color:var(--color-danger)}.task-head,.progress-label,.task-actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.eyebrow{margin:0 0 4px;color:var(--color-text-muted);font-size:12px}.task-head h3{margin:0;font-size:15px;color:var(--color-text)}.status{padding:3px 8px;border-radius:999px;font-size:12px;font-weight:600}.status-neutral{background:var(--color-surface-2);color:var(--color-text-secondary)}.status-info{background:var(--color-primary-light);color:var(--color-primary-hover)}.status-success{background:var(--color-success-light);color:var(--color-success-hover)}.status-warning{background:var(--color-warning-light);color:var(--color-warning-hover)}.status-danger{background:var(--color-danger-light);color:var(--color-danger-hover)}.progress-block{margin-top:14px}.progress-label,.task-note,.counts{color:var(--color-text-secondary);font-size:13px}.progress-label strong{font-variant-numeric:tabular-nums;color:var(--color-text)}.track{height:6px;border-radius:999px;background:var(--color-surface-3);overflow:hidden;margin-top:7px}.track span{display:block;height:100%;background:var(--color-primary);transition:width 200ms ease-out}.task-note{margin:14px 0 0}.counts{margin:8px 0 0}.task-actions{justify-content:flex-start;margin-top:14px}.task-actions button{min-height:36px;border-radius:8px;padding:0 10px;display:inline-flex;align-items:center;gap:6px;cursor:pointer;font-size:13px}.quiet-button{background:var(--color-surface);border:1px solid var(--color-border);color:var(--color-text-secondary)}.retry-button{background:var(--color-warning-light);border:1px solid transparent;color:var(--color-warning-hover)}.confirm-button{background:var(--color-success);border:1px solid var(--color-success);color:var(--color-text-inverse)}button:focus-visible{outline:3px solid var(--color-primary-light);outline-offset:2px}button:disabled{opacity:.55;cursor:not-allowed}@media (max-width:480px){.task-head{align-items:flex-start}.status{white-space:nowrap}}
</style>
