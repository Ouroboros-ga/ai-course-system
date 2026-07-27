<script setup>
import { onMounted, ref } from 'vue'
import { listMyLabs } from '@/api/labs.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const state = ref('loading')
const labs = ref([])
const error = ref('')
async function load() { state.value = 'loading'; try { const data = await listMyLabs(); labs.value = Array.isArray(data?.items) ? data.items : []; state.value = labs.value.length ? 'ready' : 'empty' } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || ''; state.value = 'error' } }
onMounted(load)
</script>

<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">我的实验</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">继续你已加入的实验任务。</p></div></header><SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取我的实验。'" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有已加入的实验" description="可在实验大厅加入自主实验，或在课程任务中进入课程实验。" /><div v-else class="experiment-list"><article v-for="lab in labs" :key="lab.lab_id" class="sfx-panel experiment-card"><div><h2 class="sfx-t-title3">{{ lab.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ lab.description || '暂无实验说明。' }}</p></div><SfxBadge :tone="lab.course_id ? 'ink' : 'green'">{{ lab.course_id ? '课程实验' : '自主实验' }}</SfxBadge></article></div></div></template>

<style scoped>.experiment-list{display:grid;gap:var(--space-3)}.experiment-card{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);margin:0}</style>
