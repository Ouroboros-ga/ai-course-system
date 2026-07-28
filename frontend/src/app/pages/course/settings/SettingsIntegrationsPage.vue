<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { confirmFanyaSync, listFanyaSyncRuns, previewFanyaSync, startFanyaSync } from '@/api/course_lifecycle.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext=inject('courseContext'); const courseId=computed(()=>courseContext.courseId.value); const allowed=computed(()=>courseContext.allowed.value?.['membership.sync']); const runs=ref([]); const state=ref('loading'); const working=ref(''); const error=ref('')
async function load(){state.value='loading';try{const data=await listFanyaSyncRuns(courseId.value);runs.value=data?.items??[];state.value=runs.value.length?'ready':'empty'}catch(e){error.value=e?.message||'泛雅同步记录读取失败';state.value='error'}}
async function start(){working.value='start';try{await startFanyaSync(courseId.value);await load()}finally{working.value=''}}
async function preview(run){working.value=run.sync_run_id;try{await previewFanyaSync(courseId.value,run.sync_run_id);await load()}finally{working.value=''}}
async function confirm(run){working.value=run.sync_run_id;try{await confirmFanyaSync(courseId.value,run.sync_run_id);await load()}finally{working.value=''}}
onMounted(load)
</script>
<template><div class="sfx-integrations"><header class="sfx-integrations-head"><div><h1 class="sfx-t-title2">泛雅集成</h1><p class="sfx-t-ui sfx-t-secondary">同步先生成变更预览；确认后才会写入课程成员或材料，不会静默覆盖本地数据。</p></div><SfxButton :disabled="!allowed" :loading="working==='start'" @click="start">发起同步</SfxButton></header><SfxError v-if="state==='error'" :description="error" @retry="load"/><SfxEmpty v-else-if="state==='empty'" title="暂无同步记录" description="需要时由教师显式发起一次预览同步。"/><section v-else class="sfx-panel"><div class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>同步批次</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="run in runs" :key="run.sync_run_id"><td>{{run.sync_run_id}}</td><td><SfxBadge tone="neutral">{{run.status}}</SfxBadge></td><td>{{run.created_at?new Date(run.created_at).toLocaleString('zh-CN'):'—'}}</td><td class="sfx-actions"><SfxButton size="sm" variant="secondary" :loading="working===run.sync_run_id" @click="preview(run)">预览</SfxButton><SfxButton v-if="run.status==='preview_ready'" size="sm" :loading="working===run.sync_run_id" @click="confirm(run)">确认同步</SfxButton></td></tr></tbody></table></div></section></div></template>
<style scoped>.sfx-integrations{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-6);max-width:1080px}.sfx-integrations-head{display:flex;justify-content:space-between;align-items:flex-end;gap:var(--space-3)}.sfx-actions{display:flex;gap:var(--space-2)}</style>
