<script setup>
import { onMounted, ref, watch } from 'vue'
import { deleteResource, listResources, purgeResource, restoreResource } from '@/api/resources.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const props = defineProps({ scope: { type: String, required: true }, courseId: { type: [Number, String], default: null } })
const loading = ref(false); const error = ref(''); const items = ref([]); const busyId = ref('')
async function load() { loading.value = true; error.value = ''; try { const data = await listResources({ scope: props.scope, ...(props.courseId == null ? {} : { course_id: props.courseId }) }); items.value = data?.items ?? [] } catch (e) { error.value = e?.message || '资源列表读取失败' } finally { loading.value = false } }
async function act(item, action) { busyId.value = item.resource_id; error.value = ''; try { if (action === 'delete') await deleteResource(item.resource_id); if (action === 'restore') await restoreResource(item.resource_id); if (action === 'purge') await purgeResource(item.resource_id); await load() } catch (e) { error.value = e?.message || '资源操作失败' } finally { busyId.value = '' } }
watch(() => [props.scope, props.courseId], load); onMounted(load)
</script>

<template>
  <SfxSkeleton v-if="loading" :lines="4" />
  <SfxError v-else-if="error" :description="error" @retry="load" />
  <SfxEmpty v-else-if="!items.length" title="暂无资源" description="此视图中还没有符合条件的资源。" />
  <div v-else class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>名称</th><th>类型</th><th>范围</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.resource_id"><td>{{ item.name }}</td><td>{{ item.resource_type }}</td><td><SfxBadge tone="neutral">{{ item.scope }}</SfxBadge></td><td>{{ item.updated_at ? new Date(item.updated_at).toLocaleString('zh-CN') : '—' }}</td><td><span class="sfx-resource-actions"><SfxButton v-if="scope === 'trash'" size="sm" :disabled="busyId === item.resource_id" @click="act(item, 'restore')">恢复</SfxButton><SfxButton v-if="scope === 'trash'" size="sm" variant="tertiary" :disabled="busyId === item.resource_id" @click="act(item, 'purge')">彻底删除</SfxButton><SfxButton v-else size="sm" variant="tertiary" :disabled="busyId === item.resource_id" @click="act(item, 'delete')">移入回收站</SfxButton></span></td></tr></tbody></table></div>
</template>

<style scoped>.sfx-resource-actions{display:flex;gap:var(--space-2);flex-wrap:wrap}</style>
