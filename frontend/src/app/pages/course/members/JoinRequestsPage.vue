<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { approveJoinRequest, listJoinRequests, rejectJoinRequest, requestJoinInfo } from '@/api/course_lifecycle.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const state = ref('loading')
const requests = ref([])
const note = ref('')
const working = ref('')
const tone = { pending: 'amber', approved: 'green', rejected: 'red', need_info: 'ink', cancelled: 'neutral' }
async function load() { state.value = 'loading'; try { const data = await listJoinRequests(courseId.value); requests.value = data?.items ?? []; state.value = requests.value.length ? 'ready' : 'empty' } catch { state.value = 'error' } }
async function decide(request, action) { working.value = request.request_id; try { if (action === 'approve') await approveJoinRequest(courseId.value, request.request_id, note.value); else if (action === 'reject') await rejectJoinRequest(courseId.value, request.request_id, note.value); else await requestJoinInfo(courseId.value, request.request_id, note.value); note.value = ''; await load() } finally { working.value = '' } }
onMounted(load)
</script>
<template>
  <div class="sfx-joinrequests"><header class="sfx-joinrequests-head"><div><h1 class="sfx-t-title2">加入申请</h1><p class="sfx-t-ui sfx-t-secondary">审核无邀请码加入课程的申请；操作会留下课程审计记录。</p></div><SfxButton size="sm" variant="secondary" @click="load">刷新</SfxButton></header>
  <SfxSkeleton v-if="state === 'loading'" :lines="4" block /><SfxError v-else-if="state === 'error'" description="加入申请暂时无法读取" @retry="load"/><SfxEmpty v-else-if="state === 'empty'" title="暂无待审核申请" description="学生提交申请后会在这里出现。"/>
  <section v-else class="sfx-panel"><label class="sfx-t-caption">审核说明（可选）<input v-model="note" class="sfx-input" maxlength="500" /></label><div class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>申请人</th><th>说明</th><th>状态</th><th>申请时间</th><th>操作</th></tr></thead><tbody><tr v-for="request in requests" :key="request.request_id"><td>{{ request.user_name || request.user_id }}</td><td>{{ request.message || request.reason || '—' }}</td><td><SfxBadge :tone="tone[request.status] || 'neutral'">{{ request.status }}</SfxBadge></td><td>{{ request.created_at ? new Date(request.created_at).toLocaleString('zh-CN') : '—' }}</td><td class="sfx-actions"><SfxButton v-if="request.status === 'pending'" size="sm" :loading="working === request.request_id" @click="decide(request, 'approve')">通过</SfxButton><SfxButton v-if="request.status === 'pending'" size="sm" variant="secondary" :loading="working === request.request_id" @click="decide(request, 'info')">补充信息</SfxButton><SfxButton v-if="request.status === 'pending'" size="sm" variant="secondary" :loading="working === request.request_id" @click="decide(request, 'reject')">拒绝</SfxButton></td></tr></tbody></table></div></section></div>
</template>
<style scoped>.sfx-joinrequests{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-6);max-width:1080px}.sfx-joinrequests-head{display:flex;justify-content:space-between;align-items:flex-end;gap:var(--space-3)}.sfx-actions{display:flex;gap:var(--space-2);flex-wrap:wrap}</style>
