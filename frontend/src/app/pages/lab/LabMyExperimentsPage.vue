<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listMyLabs } from '@/api/labs.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
const router = useRouter(); const state = ref('loading'); const labs = ref([]); const error = ref('')
async function load() { state.value = 'loading'; try { const data = await listMyLabs(); labs.value = data?.items || []; state.value = labs.value.length ? 'ready' : 'empty' } catch (reason) { error.value = reason?.message || ''; state.value = 'error' } } onMounted(load)
</script>
<template><div class="sfx-page sfx-page--narrow"><header class="sfx-page-header"><div><h1 class="sfx-t-title1">我的实验</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">教师确认后的课程实验推荐。系统不会替你开始或提交代码。</p></div></header><SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取我的实验。'" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有实验推荐" description="教师确认推荐后，实验会出现在这里。" /><div v-else class="experiment-list"><article v-for="lab in labs" :key="lab.lab_id" class="sfx-panel experiment-card"><div><h2 class="sfx-t-title3">{{ lab.title }}</h2><p class="sfx-t-ui sfx-t-secondary">{{ lab.description || '暂无实验说明。' }}</p></div><SfxButton size="sm" @click="router.push(`/app/course/${lab.course_id}/experiments`)">自行开始</SfxButton></article></div></div></template>
<style scoped>.experiment-list{display:grid;gap:var(--space-3)}.experiment-card{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-4);margin:0}</style>
