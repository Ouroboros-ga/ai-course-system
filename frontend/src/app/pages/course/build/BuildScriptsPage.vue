<script setup>
import { computed, onMounted, ref } from 'vue'
import { getTeachingScripts, lockTeachingScript, updateTeachingScript } from '@/api/course_editor.js'
import { useRoute } from 'vue-router'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
const route=useRoute();const courseId=computed(()=>Number(route.params.courseId));const state=ref('loading');const error=ref('');const items=ref([]);const editable=ref(false);const saving=ref('')
async function load(){try{const data=await getTeachingScripts(courseId.value);items.value=data?.items??[];editable.value=Boolean(data?.editable);state.value='ready'}catch(e){error.value=e?.message||'讲稿读取失败';state.value='error'}}
async function save(item){if(!editable.value||item.locked)return;saving.value=item.script_node_id;try{await updateTeachingScript(courseId.value,item.script_node_id,{content:item.content,style:item.style})}finally{saving.value=''}}
async function lock(item){await lockTeachingScript(courseId.value,item.script_node_id);item.locked=true}
onMounted(load)
</script>
<template><section class="stage"><header><div><p class="eyebrow">Step 6</p><h1>讲授脚本</h1><p class="muted">讲稿草稿可编辑；确认后再进入媒体与发布流程。</p></div></header><SfxSkeleton v-if="state==='loading'" :lines="5" block/><SfxError v-else-if="state==='error'" :description="error" @retry="load"/><div v-else-if="!items.length" class="empty">课程结构确认后会生成讲授脚本草稿。</div><div v-else class="script-list"><article v-for="item in items" :key="item.script_node_id" class="script-card"><div class="script-head"><span>{{item.outline_node_id}}</span><SfxButton v-if="!item.locked" variant="tertiary" size="sm" :disabled="!editable" @click="lock(item)">锁定</SfxButton><span v-else>已锁定</span></div><textarea v-model="item.content" :disabled="!editable||item.locked" @blur="save(item)"/><div class="script-foot"><input v-model="item.style" :disabled="!editable||item.locked" placeholder="讲解风格" @blur="save(item)"/><span>{{saving===item.script_node_id?'保存中…':'教师可继续编辑'}}</span></div></article></div></section></template>
<style scoped>.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}header{border-bottom:1px solid #e2e8f0;padding-bottom:18px;margin-bottom:18px}h1{margin:4px 0;font-size:24px}.eyebrow,.muted,.script-head,.script-foot{color:#64748b;font-size:13px}.script-list{display:grid;gap:14px}.script-card{border:1px solid #e2e8f0;border-radius:10px;padding:14px}.script-head,.script-foot{display:flex;justify-content:space-between;align-items:center;gap:8px}.script-card textarea{display:block;width:100%;min-height:150px;margin:12px 0;padding:12px;border:1px solid #cbd5e1;border-radius:8px;resize:vertical;font:inherit}.script-foot input{border:1px solid #cbd5e1;border-radius:6px;padding:6px 8px}.empty{padding:48px;text-align:center;color:#64748b}</style>
