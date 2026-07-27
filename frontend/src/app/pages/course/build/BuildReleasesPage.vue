<script setup>
import { ref } from 'vue'
import { publishCourseBuild } from '@/api/course_editor.js'
import { useRoute } from 'vue-router'
const route=useRoute();const message=ref('');async function publish(){try{const data=await publishCourseBuild(Number(route.params.courseId));message.value=data?.message||'课程已发布'}catch(e){message.value=e?.message||'发布失败'}}
</script>
<template><section class="stage"><p class="eyebrow">Step 10</p><h1>课程发布</h1><p>发布会冻结当前目录与讲稿版本，并将课程状态切换为已发布。</p><button @click="publish">发布课程</button><p v-if="message">{{message}}</p></section></template><style scoped>.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}h1{margin:4px 0 12px}button{padding:9px 16px;border:0;border-radius:7px;background:#1769aa;color:#fff;cursor:pointer}</style>
