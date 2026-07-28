<script setup>
import { computed, onMounted, ref } from 'vue'
import { cancelTask, listTasks, retryTask } from '@/api/tasks.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const props = defineProps({ view: { type: String, required: true }, title: { type: String, required: true } })
const state = ref('loading')
const items = ref([])
const working = ref('')

const statusTone = { pending: 'neutral', queued: 'neutral', running: 'ink', succeeded: 'green', failed: 'red', cancelled: 'neutral', interrupted: 'amber' }
const ordered = computed(() => [...items.value].sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at))))

async function load() {
  state.value = 'loading'
  try {
    const data = await listTasks({ view: props.view })
    items.value = Array.isArray(data?.items) ? data.items : []
    state.value = items.value.length ? 'ready' : 'empty'
  } catch {
    state.value = 'error'
  }
}
async function cancel(item) {
  working.value = item.task_id
  try { await cancelTask(item.task_id); await load() } finally { working.value = '' }
}
async function retry(item) {
  working.value = item.task_id
  try { await retryTask(item.task_id); await load() } finally { working.value = '' }
}
function when(value) { return value ? new Date(value).toLocaleString('zh-CN') : '—' }
onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-tasks">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">{{ title }}</h1><p class="sfx-t-ui sfx-t-secondary">课程解析、图谱、媒体和实验运行任务的真实状态。</p></div><SfxButton size="sm" variant="secondary" @click="load">刷新</SfxButton></header>
    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" description="任务中心暂时无法读取" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="暂无任务" description="后续创建解析、媒体或实验任务后会在这里显示。" />
    <section v-else class="sfx-panel"><div class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>任务</th><th>状态</th><th>阶段</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in ordered" :key="item.task_id"><td><strong>{{ item.input_summary || item.task_type }}</strong><p class="sfx-t-caption sfx-t-muted">{{ item.task_id }}</p></td><td><SfxBadge :tone="statusTone[item.status] || 'neutral'">{{ item.status }}</SfxBadge></td><td>{{ item.stage || '—' }}</td><td class="sfx-t-caption">{{ when(item.updated_at || item.created_at) }}</td><td><span class="sfx-task-actions"><SfxButton v-if="['pending','queued','running'].includes(item.status)" size="sm" variant="secondary" :loading="working === item.task_id" @click="cancel(item)">取消</SfxButton><SfxButton v-if="['failed','interrupted','cancelled'].includes(item.status)" size="sm" variant="secondary" :loading="working === item.task_id" @click="retry(item)">重试</SfxButton></span></td></tr></tbody></table></div></section>
  </div>
</template>

<style scoped>.sfx-tasks{max-width:1180px}.sfx-task-actions{display:flex;gap:var(--space-2)}</style>
