<script setup>
import { onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { enrollLab, listLabCatalog } from '@/api/labs.js'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const state = ref('loading')
const labs = ref([])
const sandbox = ref(null)
const languages = ref([])
const error = ref('')
const enrollingId = ref(null)

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const [catalog, health, supported] = await Promise.all([
      listLabCatalog(), getSandboxHealth().catch(() => null), getSandboxLanguages().catch(() => null),
    ])
    labs.value = Array.isArray(catalog?.items) ? catalog.items : []
    sandbox.value = health
    languages.value = Array.isArray(supported?.languages) ? supported.languages : []
    state.value = labs.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || ''
    state.value = 'error'
  }
}
async function enroll(lab) {
  enrollingId.value = lab.lab_id
  try { await enrollLab(lab.lab_id) } catch (caught) { error.value = caught?.response?.data?.detail || caught?.message || '加入实验失败。' } finally { enrollingId.value = null }
}
onMounted(load)
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">实验大厅</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">发现已发布的自主实验与课程实验。</p></div><SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton></header>
    <section class="sfx-panel environment"><div><h2 class="sfx-panel-title"><FlaskConical :size="18" /> 代码运行环境</h2><p class="sfx-t-ui sfx-t-secondary">代码只会发送到独立 Judge0 沙箱，不会在主应用中执行。</p></div><SfxBadge :tone="sandbox?.available ? 'green' : 'amber'">{{ sandbox?.available ? '沙箱可用' : '沙箱暂不可用' }}</SfxBadge><p v-if="languages.length" class="sfx-t-caption sfx-t-secondary">支持 {{ languages.length }} 种语言</p></section>
    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" :description="error || '无法读取实验目录。'" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="暂无可加入的实验" description="已发布的自主实验或你有权限的课程实验会显示在这里。" />
    <div v-else class="lab-grid"><article v-for="lab in labs" :key="lab.lab_id" class="sfx-panel lab-card"><div class="lab-card-head"><h2 class="sfx-t-title3">{{ lab.title }}</h2><SfxBadge :tone="lab.course_id ? 'ink' : 'green'">{{ lab.course_id ? '课程实验' : '自主实验' }}</SfxBadge></div><p class="sfx-t-ui sfx-t-secondary">{{ lab.description || '暂无实验说明。' }}</p><p class="sfx-t-caption sfx-t-secondary">{{ lab.language_whitelist?.join(' · ') || '语言由课程策略决定' }} · {{ lab.cpu_time_limit }} 秒 CPU · {{ lab.memory_limit }} KB</p><SfxButton variant="primary" size="sm" :loading="enrollingId === lab.lab_id" @click="enroll(lab)">加入实验</SfxButton></article></div>
    <p v-if="error && state === 'ready'" class="lab-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.environment { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-6); }
.environment > div { flex: 1; }.lab-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-4); }.lab-card { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-3); margin: 0; }.lab-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); width: 100%; }.lab-error { color: var(--red-700); margin-top: var(--space-3); }
</style>
