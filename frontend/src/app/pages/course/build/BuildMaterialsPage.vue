<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { listBuildMaterials } from '@/api/course_build.js'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const materials = ref([])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listBuildMaterials(Number(route.params.courseId))
    materials.value = data?.items ?? []
  } catch (err) {
    error.value = err?.message || '资料读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="stage">
    <p class="eyebrow">Step 1</p>
    <h1>课程资料</h1>
    <p class="muted">资料上传从统一导入入口进入；本页展示材料、版本和解析状态。</p>
    <p v-if="loading" class="empty">正在读取资料…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <div v-else-if="!materials.length" class="empty">尚未上传课程资料。</div>
    <div v-else class="materials">
      <article v-for="item in materials" :key="item.material_id" class="material">
        <strong>{{ item.name }}</strong>
        <span>{{ item.material_type }} · {{ item.status }}</span>
        <small>当前版本：{{ item.current_version_id || '无' }}</small>
      </article>
    </div>
  </section>
</template>

<style scoped>
.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}.eyebrow,.muted,small{color:#64748b;font-size:13px}h1{margin:4px 0 12px}.materials{display:grid;gap:10px;margin-top:20px}.material{display:grid;gap:5px;border:1px solid #e2e8f0;border-radius:10px;padding:14px}.material span{color:#64748b;font-size:13px}.empty{padding:48px;text-align:center;color:#64748b}.error{color:#b91c1c}
</style>
