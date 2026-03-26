<template>
  <section class="about-section" :class="{ 'fade-in-up': animated }">
    <h2>技术栈</h2>
    <div class="tech-list">
      <span>Vue 3</span>
      <span>Vue Router</span>
      <span>AI 大模型</span>
      <span>RAG 检索</span>
      <span>泛雅平台 API</span>
    </div>
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

.tech-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.tech-list span {
  background: #eff6ff;
  color: #3b82f6;
  padding: 8px 16px;
  border-radius: 99px;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}
.tech-list span:hover {
  transform: scale(1.06);
  background: #3b82f6;
  color: #fff;
}
</style>
