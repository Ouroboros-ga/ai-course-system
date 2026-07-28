<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { createExperimentDefinition, listExperimentDefinitions, publishExperimentDefinition } from '@/api/experiments.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext=inject('courseContext'); const courseId=computed(()=>courseContext.courseId.value); const state=ref('loading'); const items=ref([]); const saving=ref(false); const error=ref(''); const form=ref({title:'',description:'',languages:'python',max_attempts:3,cooldown_minutes:30})
async function load(){state.value='loading';try{const data=await listExperimentDefinitions(courseId.value);items.value=data?.items??[];state.value=items.value.length?'ready':'empty'}catch(e){error.value=e?.message||'实验任务读取失败';state.value='error'}}
async function create(){if(!form.value.title.trim())return;saving.value=true;try{await createExperimentDefinition(courseId.value,{title:form.value.title.trim(),description:form.value.description,language_whitelist:form.value.languages.split(',').map((v)=>v.trim()).filter(Boolean),max_attempts:form.value.max_attempts,cooldown_minutes:form.value.cooldown_minutes});form.value.title='';form.value.description='';await load()}catch(e){error.value=e?.message||'创建实验任务失败'}finally{saving.value=false}}
async function publish(item){saving.value=true;try{await publishExperimentDefinition(courseId.value,item.experiment_id);await load()}finally{saving.value=false}}
onMounted(load)
</script>
<template><section class="sfx-teacher-experiments"><header><h2 class="sfx-panel-title">教师实验任务</h2><p class="sfx-t-ui sfx-t-secondary">先创建草稿，检查语言白名单和题目内容后再发布给学生。</p></header><form class="sfx-panel sfx-create" @submit.prevent="create"><input v-model.trim="form.title" class="sfx-input" required placeholder="实验任务名称"/><textarea v-model.trim="form.description" class="sfx-input" rows="3" placeholder="任务说明"/><input v-model="form.languages" class="sfx-input" placeholder="语言白名单，如 python"/><SfxButton type="submit" :loading="saving">创建草稿任务</SfxButton></form><SfxError v-if="state==='error'" :description="error" @retry="load"/><SfxEmpty v-else-if="state==='empty'" title="暂无实验任务" description="创建草稿任务后，可在这里发布。"/><section v-else class="sfx-panel"><div class="sfx-table-wrap"><table class="sfx-table"><thead><tr><th>任务</th><th>语言</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.experiment_id"><td><strong>{{item.title}}</strong><p class="sfx-t-caption">{{item.description}}</p></td><td>{{(item.language_whitelist||[]).join(', ')}}</td><td><SfxBadge :tone="item.publish_status==='published'?'green':'amber'">{{item.publish_status}}</SfxBadge></td><td><SfxButton v-if="item.publish_status!=='published'" size="sm" :loading="saving" @click="publish(item)">发布</SfxButton></td></tr></tbody></table></div></section></section></template>
<style scoped>.sfx-teacher-experiments{display:flex;flex-direction:column;gap:var(--space-4)}.sfx-create{display:grid;gap:var(--space-3)}</style>
