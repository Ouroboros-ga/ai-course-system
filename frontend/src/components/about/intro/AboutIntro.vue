<template>
  <section class="about-section" :class="{ 'fade-in-up': animated }">
    <h2>项目介绍</h2>
    <p>
      本项目依托泛雅教学平台，结合 AI 大模型与 RAG 检索技术，
      实现智能课件生成、课堂互动、7×24 小时实时答疑，
      为教师备课与学生学习提供轻量化、高效率的智慧教学解决方案。
    </p>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const animated = ref(false)

onMounted(() => {
  animated.value = true
})
</script>

<style scoped>
.fade-in-up {
  animation: fadeInUp 0.7s ease forwards;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(15px); }
  to { opacity: 1; transform: translateY(0); }
}

.about-section {
  max-width: 800px;
  width: 100%;
  margin-bottom: 30px;
}
.about-section h2 {
  font-size: 1.8rem;
  color: #0f172a;
  margin-bottom: 15px;
  font-weight: 700;
}
.about-section p {
  color: #475569;
  line-height: 1.7;
  font-size: 1rem;
}
</style>
