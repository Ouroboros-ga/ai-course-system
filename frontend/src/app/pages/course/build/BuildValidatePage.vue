<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { runBuildValidation } from '@/api/course_build.js'
const route=useRoute();const status=ref('idle');const result=ref(null)
async function run(){status.value='running';try{const data=await runBuildValidation(Number(route.params.courseId));result.value=data;status.value='ready'}catch(e){result.value={message:e?.message||'检查失败'};status.value='error'}}
onMounted(run)
</script>
<template><section class="stage"><p class="eyebrow">Step 9</p><h1>发布前检查</h1><button @click="run">重新检查</button><pre v-if="result">{{JSON.stringify(result,null,2)}}</pre><p v-else>正在检查…</p></section></template><style scoped>.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}h1{margin:4px 0 18px}button{padding:8px 14px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;cursor:pointer}pre{margin-top:18px;background:#f8fafc;padding:16px;border-radius:8px;white-space:pre-wrap}</style>
