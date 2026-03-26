<template>
  <footer class="about-footer" :class="{ 'fade-in-up': animated }">
    <p>© 2026 泛雅 AI 智课系统 · 服创设计项目</p>
  </footer>
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

.about-footer {
  margin-top: auto;
  text-align: center;
  color: #94a3b8;
  font-size: 0.9rem;
  width: 100%;
}
</style>
