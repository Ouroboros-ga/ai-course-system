<template>
  <div class="about-page">
    <!-- 顶部标题区 -->
    <section class="about-hero" ref="heroRef">
      <h1 class="floating-title">About</h1>
      <p class="typed-text"></p>
    </section>

    <!-- 项目介绍 -->
    <section class="about-section" ref="introRef">
      <h2>项目介绍</h2>
      <p>
        本项目依托泛雅教学平台，结合 AI 大模型与 RAG 检索技术，
        实现智能课件生成、课堂互动、7×24 小时实时答疑，
        为教师备课与学生学习提供轻量化、高效率的智慧教学解决方案。
      </p>
    </section>

    <!-- 核心功能 -->
    <section class="about-section" ref="featureRef">
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

    <!-- 技术栈 -->
    <section class="about-section" ref="techRef">
      <h2>技术栈</h2>
      <div class="tech-list">
        <span>Vue 3</span>
        <span>Vue Router</span>
        <span>AI 大模型</span>
        <span>RAG 检索</span>
        <span>泛雅平台 API</span>
      </div>
    </section>

    <!-- 底部 -->
    <footer class="about-footer" ref="footerRef">
      <p>© 2026 泛雅 AI 智课系统 · 服创设计项目</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import Typed from 'typed.js'

const heroRef = ref(null)
const introRef = ref(null)
const featureRef = ref(null)
const techRef = ref(null)
const footerRef = ref(null)

onMounted(() => {
  heroRef.value?.classList.add('fade-in-up')
  introRef.value?.classList.add('fade-in-up')
  featureRef.value?.classList.add('fade-in-up')
  techRef.value?.classList.add('fade-in-up')
  footerRef.value?.classList.add('fade-in-up')

  new Typed('.typed-text', {
    strings: ['基于泛雅平台的 AI 互动智课生成与实时问答系统'],
    typeSpeed: 50,
    showCursor: false
  })
})
</script>

<style scoped>
.about-page {
  width: 100%;
  height: 100vh;
  background: #f8fafc;
  font-family: 'Segoe UI', Roboto, sans-serif;
  padding: 40px 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow: hidden;
}

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
/* 技术栈标签 悬浮动画 */
.tech-list span:hover {
  transform: scale(1.06);
  background: #3b82f6;
  color: #fff;
}

.about-footer {
  margin-top: auto;
  text-align: center;
  color: #94a3b8;
  font-size: 0.9rem;
  width: 100%;
}
</style>
