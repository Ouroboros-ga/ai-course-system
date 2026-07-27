<script setup>
import { onMounted, ref } from 'vue'
import { listLabRecords } from '@/api/labs.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const state = ref('loading')
const records = ref([])
const error = ref('')
function score(record) { return record.final_score == null ? '未评分' : `${Math.round(record.final_score * 100)}%` }
async function load() { state.value = 'loading'; try { const data = await listLabRecords(); records.value = Array.isArray(data?.items) ? data.items : []; state.value = records.value.length ? 'ready' : 'empty' } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || ''; state.value = 'error' } }
onMounted(load)
</script>

<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">学习记录</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">查看已经完成或已保存的实验结果。</p></div></header><SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取实验记录。'" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有实验记录" description="当实验完成流程写入结果后，记录会显示在这里。" /><section v-else class="sfx-panel records"><table><thead><tr><th>实验</th><th>结果</th><th>得分</th><th>完成时间</th></tr></thead><tbody><tr v-for="record in records" :key="record.record_id || record.attempt_id"><td>{{ record.lab_title || record.lab_id || '实验' }}</td><td><SfxBadge :tone="record.passed ? 'green' : 'amber'">{{ record.passed == null ? '待判定' : record.passed ? '通过' : '未通过' }}</SfxBadge></td><td>{{ score(record) }}</td><td>{{ record.created_at ? new Date(record.created_at).toLocaleString('zh-CN') : '—' }}</td></tr></tbody></table></section></div></template>

<style scoped>.records{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:var(--ui-sm-size)}th,td{padding:var(--space-3);border-bottom:1px solid var(--border-subtle);text-align:left;white-space:nowrap}th{color:var(--text-secondary);font-weight:var(--ui-md-weight)}</style>
