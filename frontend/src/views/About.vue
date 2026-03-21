<template>
  <div class="about-page">
    <!-- 顶部标题区 -->
    <section class="about-hero" ref="heroRef">
      <div id="particles-container" class="particles"></div>
      <h1>About</h1>
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
        <div class="card" v-for="item in features" :key="item.title">
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </div>
      </div>
    </section>

    <!-- 技术栈 -->
    <section class="about-section" ref="techRef">
      <h2>技术栈</h2>
      <div class="tech-list">
        <span v-for="tech in techStack" :key="tech">{{ tech }}</span>
      </div>
    </section>

    <!-- 底部 -->
    <footer class="about-footer" ref="footerRef">
      <p>© 2026 泛雅 AI 智课系统 · 服创=设计项目</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useIntersectionObserver } from '@vueuse/core'
import Typed from 'typed.js'

const features = ref([
  { title: 'AI 课件生成', desc: '自动结构化排版，快速生成教学课件' },
  { title: '实时智能答疑', desc: '基于知识库精准回答，无幻觉、更可靠' },
  { title: '学习进度跟踪', desc: '记录学习轨迹，支持多端续学' },
  { title: '极简清爽界面', desc: '统一设计语言，流畅舒适的使用体验' }
])
const techStack = ref(['Vue 3', 'Vue Router', 'AI 大模型', 'RAG 检索', '泛雅平台 API'])

// 滚动动画监听
const setupScrollAnimation = (ref) => {
  const { stop } = useIntersectionObserver(
    ref,
    ([{ isIntersecting }]) => {
      if (isIntersecting) {
        ref.value.classList.add('fade-in-up')
        stop()
      }
    },
    { threshold: 0.1 }
  )
}
const heroRef = ref(null)
const introRef = ref(null)
const featureRef = ref(null)
const techRef = ref(null)
const footerRef = ref(null)
onMounted(() => {
  setupScrollAnimation(heroRef)
  setupScrollAnimation(introRef)
  setupScrollAnimation(featureRef)
  setupScrollAnimation(techRef)
  setupScrollAnimation(footerRef)

  // 打字机效果
  new Typed('.typed-text', {
    strings: ['基于泛雅平台的 AI 互动智课生成与实时问答系统'],
    typeSpeed: 40,
    showCursor: false
  })
})
</script>

<style scoped>
.about-page {
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  font-family: sans-serif;
  padding: 100px 20px 60px;
  position: relative;
}

/* 滚动动画 */
.fade-in-up {
  animation: fadeInUp 0.8s ease forwards;
}
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 顶部标题 */
.about-hero {
  max-width: 800px;
  margin: 0 auto 60px;
  text-align: center;
  position: relative;
  height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.particles {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
}
.about-hero h1 {
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 12px;
  position: relative;
  z-index: 1;
}
.about-hero p {
  font-size: 1.1rem;
  color: #64748b;
  position: relative;
  z-index: 1;
}

/* 区块通用 */
.about-section {
  max-width: 800px;
  margin: 0 auto 60px;
  opacity: 0; /* 初始隐藏，等待动画 */
}
.about-section h2 {
  font-size: 1.8rem;
  color: #0f172a;
  margin-bottom: 20px;
  font-weight: 700;
}
.about-section p {
  color: #475569;
  line-height: 1.7;
  font-size: 1rem;
}

/* 卡片 */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}
.card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 24px;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  position: relative;
  overflow: hidden;
}
.card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.1));
  opacity: 0;
  transition: opacity 0.3s ease;
}
.card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 24px rgba(0,0,0,0.08);
}
.card:hover::before {
  opacity: 1;
}
.card h3 {
  color: #3b82f6;
  margin-bottom: 8px;
  font-size: 1.1rem;
  position: relative;
  z-index: 1;
}
.card p {
  color: #64748b;
  font-size: 0.95rem;
  position: relative;
  z-index: 1;
}

/* 技术栈 */
.tech-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.tech-list span {
  background: #eff6ff;
  color: #3b82f6;
  padding: 8px 14px;
  border-radius: 99px;
  font-size: 0.9rem;
  transition: all 0.2s ease;
  cursor: default;
  animation: pulse 2s infinite;
}
.tech-list span:hover {
  background: #3b82f6;
  color: #fff;
  transform: scale(1.05);
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
  70% { box-shadow: 0 0 0 10px rgba(59, 130, 246, 0); }
  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}

/* 底部 */
.about-footer {
  max-width: 800px;
  margin: 100px auto 0;
  text-align: center;
  color: #94a3b8;
  font-size: 0.9rem;
  opacity: 0;
}
</style>
