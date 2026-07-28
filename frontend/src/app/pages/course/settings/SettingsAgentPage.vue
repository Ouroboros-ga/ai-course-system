<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { getCourseSettings, updateCourseAgentPolicy } from '@/api/course_lifecycle.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext=inject('courseContext'); const courseId=computed(()=>courseContext.courseId.value); const allowed=computed(()=>courseContext.allowed.value?.['agent.policy.configure']); const form=ref({ enabled_tools: [], require_teacher_confirmation: true, web_research_enabled: false }); const version=ref(null); const saving=ref(false); const error=ref(''); const saved=ref(false)
const tools=['graph_read','course_retrieval','question_bank','sandbox','visualization','learning_event','web_research']
async function load(){try{const data=await getCourseSettings(courseId.value);version.value=data?.version??null;form.value={...form.value,...(data?.agent_policy??{})}}catch(e){error.value=e?.message||'智能体策略读取失败'}}
async function save(){saving.value=true;error.value='';saved.value=false;try{await updateCourseAgentPolicy(courseId.value,form.value,version.value);saved.value=true;await load()}catch(e){error.value=e?.message||'保存智能体策略失败'}finally{saving.value=false}}
onMounted(load)
</script>
<template><div class="sfx-agent"><header><h1 class="sfx-t-title2">智能体策略</h1><p class="sfx-t-ui sfx-t-secondary">工具本身仍会执行课程、学生和能力校验；此处只控制课程级可用范围与教师确认。</p></header><form class="sfx-panel sfx-agent-form" @submit.prevent="save"><label v-for="tool in tools" :key="tool" class="sfx-check"><input v-model="form.enabled_tools" type="checkbox" :value="tool" :disabled="!allowed"/><span>{{tool}}</span></label><label class="sfx-check"><input v-model="form.require_teacher_confirmation" type="checkbox" :disabled="!allowed"/>高风险教学动作必须教师确认</label><label class="sfx-check"><input v-model="form.web_research_enabled" type="checkbox" :disabled="!allowed"/>允许补充外部资料（不写入课程事实或认知结论）</label><SfxError v-if="error" :description="error"/><p v-if="saved" class="sfx-save-ok">已保存。</p><SfxButton type="submit" :disabled="!allowed" :loading="saving">保存智能体策略</SfxButton></form></div></template>
<style scoped>.sfx-agent{display:flex;flex-direction:column;gap:var(--space-4);max-width:860px;padding:var(--space-6)}.sfx-agent-form{display:grid;gap:var(--space-3)}.sfx-check{display:flex;align-items:center;gap:var(--space-2)}.sfx-save-ok{color:var(--green-700)}</style>
