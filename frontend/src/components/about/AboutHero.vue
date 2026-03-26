<template>
  <section class="about-hero" :class="{ 'fade-in-up': animated }">
    <h1 class="floating-title">About</h1>
    <p class="typed-text"></p>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import Typed from 'typed.js'

const animated = ref(false)

onMounted(() => {
  animated.value = true
  new Typed('.typed-text', {
    strings: ['基于泛雅平台的 AI 互动智课生成与实时问答系统'],
    typeSpeed: 50,
    showCursor: false
  })
})
</script>

<style scoped>
.floating-title {
  font-size: 2.8rem;
  font-weight: 800;
  color: #4f46e5;
  margin-bottom: 12px;
  animation: float 3s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

.fade-in-up {
  animation: fadeInUp 0.7s ease forwards;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(15px); }
  to { opacity: 1; transform: translateY(0); }
}

.about-hero {
  max-width: 800px;
  margin-bottom: 30px;
  text-align: center;
}
.about-hero p {
  font-size: 1.1rem;
  color: #64748b;
}
</style>
