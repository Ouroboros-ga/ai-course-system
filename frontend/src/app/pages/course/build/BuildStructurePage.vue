<script setup>
import { computed, onMounted, ref } from 'vue'
import { createOutlineNode, getOutline, lockOutlineNode, reorderOutline, updateOutlineNode } from '@/api/course_editor.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const state = ref('loading'); const error = ref(''); const nodes = ref([]); const editable = ref(false); const saving = ref('')
async function load(){ state.value='loading'; try { const data=await getOutline(courseId.value); nodes.value=data?.nodes??[]; editable.value=Boolean(data?.editable); state.value='ready' } catch(e){ error.value=e?.message||'课程结构读取失败'; state.value='error' } }
async function save(node){ if(!editable.value||node.locked)return; saving.value=node.outline_node_id; try { await updateOutlineNode(courseId.value,node.outline_node_id,{title:node.title}); } finally { saving.value='' } }
async function lock(node){ await lockOutlineNode(courseId.value,node.outline_node_id); node.locked=true }
async function addNode(){ const data=await createOutlineNode(courseId.value,{title:'新知识点',node_type:'knowledge_point',order_index:nodes.value.length}); nodes.value.push(data) }
async function move(index,delta){ const next=index+delta;if(next<0||next>=nodes.value.length)return;[nodes.value[index],nodes.value[next]]=[nodes.value[next],nodes.value[index]];await reorderOutline(courseId.value,nodes.value.map(n=>n.outline_node_id)) }
onMounted(load)
</script>
<template>
  <section class="stage"><header><div><p class="eyebrow">Step 5</p><h1>课程结构</h1><p class="muted">AI 生成的是草稿，教师可以直接编辑、排序和锁定。</p></div><SfxButton variant="primary" size="sm" :disabled="!editable" @click="addNode">新增节点</SfxButton></header>
    <SfxSkeleton v-if="state==='loading'" :lines="5" block/><SfxError v-else-if="state==='error'" :description="error" @retry="load"/>
    <div v-else-if="!nodes.length" class="empty">当前还没有课程结构，上传材料解析后会生成草稿。</div>
    <div v-else class="node-list"><article v-for="(node,index) in nodes" :key="node.outline_node_id" class="node-card" :class="{locked:node.locked}"><div class="node-order">{{ index+1 }}</div><div class="node-body"><div class="node-meta">{{ node.node_type }} <span v-if="node.page_range">· 第 {{ node.page_range }} 页</span><span v-if="node.locked">· 已锁定</span></div><input v-model="node.title" :disabled="!editable||node.locked" @blur="save(node)"/><small v-if="node.source_block_refs?.length">来源 {{ node.source_block_refs.join(', ') }}</small></div><div class="node-actions"><button :disabled="index===0||!editable" @click="move(index,-1)">上移</button><button :disabled="index===nodes.length-1||!editable" @click="move(index,1)">下移</button><button v-if="!node.locked" :disabled="!editable" @click="lock(node)">锁定</button><span v-if="saving===node.outline_node_id">保存中…</span></div></article></div>
  </section>
</template>
<style scoped>.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}header{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid #e2e8f0;padding-bottom:18px;margin-bottom:18px}h1{margin:4px 0;font-size:24px}.eyebrow,.node-meta,.muted,small{color:#64748b;font-size:13px}.node-list{display:grid;gap:10px}.node-card{display:flex;gap:12px;align-items:center;border:1px solid #e2e8f0;border-radius:10px;padding:12px}.node-card.locked{background:#f8fafc}.node-order{width:28px;color:#94a3b8}.node-body{flex:1;min-width:0}.node-body input{width:100%;border:0;border-bottom:1px solid #cbd5e1;padding:6px 0;font-size:16px;background:transparent}.node-body input:disabled{color:#334155}.node-actions{display:flex;gap:5px;align-items:center}.node-actions button{border:1px solid #cbd5e1;background:#fff;border-radius:6px;padding:5px 7px;cursor:pointer}.node-actions button:disabled{opacity:.45}.empty{padding:48px;text-align:center;color:#64748b}</style>
