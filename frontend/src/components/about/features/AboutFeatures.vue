<template>
  <section class="about-section" :class="{ 'fade-in-up': animated }">
    <h2>核心功能</h2>
    <div class="feature-grid">
      <div class="card">
        <div class="card-icon">📄</div>
        <h3>AI 课件生成</h3>
        <p>自动结构化排版，快速生成教学课件</p>
      </div>
      <div class="card">
        <div class="card-icon">💬</div>
        <h3>实时智能答疑</h3>
        <p>基于知识库精准回答，无幻觉、更可靠</p>
      </div>
      <div class="card">
        <div class="card-icon">📊</div>
        <h3>学习进度跟踪</h3>
        <p>记录学习轨迹，支持多端续学</p>
      </div>
      <div class="card">
        <div class="card-icon">🎨</div>
        <h3>极简清爽界面</h3>
        <p>统一设计语言，流畅舒适的使用体验</p>
      </div>
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

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}
.card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 28px 24px;
  transition: transform 0.2s ease;
}
.card:hover {
  transform: translateY(-3px);
}
.card-icon {
  font-size: 28px;
  margin-bottom: 12px;
}
.card h3 {
  color: #3b82f6;
  margin-bottom: 8px;
  font-size: 1.1rem;
}
.card p {
  color: #64748b;
  font-size: 0.95rem;
}
</style>
