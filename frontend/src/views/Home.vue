<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const containerRef = ref(null)

// 🔥 这里的逻辑变得非常简单自然
const goNext = () => {
  const container = containerRef.value
  const nextTop = container.scrollTop + window.innerHeight
  container.scrollTo({ top: nextTop, behavior: 'smooth' })
}

const goToTop = () => {
  containerRef.value.scrollTo({ top: 0, behavior: 'smooth' })
}

const goToChat = () => {
  router.push('/chat')
}
</script>

<template>
  <div class="home-wrapper">
    <!-- 主滚动容器 -->
    <div class="main-container" ref="containerRef">

      <!-- 第一页：Hero Section -->
      <section class="slide hero-page">
        <div class="content-box">
          <div class="badge">Next-Gen AI Education</div>
          <h1 class="main-title">
            泛雅 AI 智课 <span class="text-blue">实时互动</span><br>
            <span class="sub-gradient">重构课堂学习体验</span>
          </h1>
          <p class="description">
            基于泛雅平台的 AI 互动智课生成与实时问答系统。融合 RAG 与大模型技术，自动生成互动课件、智能续接学习进度。支持高校教学场景，助力教育数字化升级。
          </p>

          <div class="btn-group">
            <button class="use-btn" @click="goToChat">立即使用</button>
            <button class="secondary-btn">了解更多</button>
          </div>
        </div>
      </section>

      <!-- 其他页面：直接使用图片背景 -->
      <section class="slide page2"></section>
      <section class="slide page3"></section>
      <section class="slide page4"></section>
    </div>

    <!-- 固定 UI 元素 -->
    <div class="scroll-arrow" @click="goNext">
      <div class="mouse">
        <div class="wheel"></div>
      </div>
    </div>

    <button class="back-top" @click="goToTop" title="回到顶部">
      <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="3">
        <path d="M18 15l-6-6-6 6" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
/* 1. 基础布局：强制全屏且锁定滚动 */
.home-wrapper {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #f8fafc;
}

.main-container {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  scroll-behavior: smooth;
  /* 🔥 核心：CSS 物理滚动捕捉 */
  scroll-snap-type: y mandatory;
  scrollbar-width: none; /* 隐藏滚动条 (Firefox) */
}

.main-container::-webkit-scrollbar {
  display: none; /* 隐藏滚动条 (Chrome/Safari) */
}

/* 2. Slide 基础定义 */
.slide {
  width: 100%;
  height: 100vh;
  /* 确保每一页都能精准对齐 */
  scroll-snap-align: start;
  scroll-snap-stop: always;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

/* 3. 第一页 Hero 内容排版 */
.hero-page {
  background: radial-gradient(circle at 10% 20%, rgba(216, 241, 255, 0.4) 0%, rgba(255, 255, 255, 1) 90%);
  padding: 0 5%;
}

.content-box {
  max-width: 1000px;
  text-align: center;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.5rem;
}

.badge {
  padding: 6px 16px;
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  border-radius: 100px;
  font-size: 0.875rem;
  font-weight: 600;
  letter-spacing: 1px;
}

.main-title {
  font-size: clamp(2rem, 5vw, 4rem);
  font-weight: 800;
  line-height: 1.1;
  color: #0f172a;
}

.sub-gradient {
  background: linear-gradient(90deg, #3b82f6, #2dd4bf);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.description {
  font-size: clamp(1rem, 1.5vw, 1.25rem);
  color: #64748b;
  max-width: 750px;
  line-height: 1.6;
}

/* 4. 按钮样式 */
.btn-group {
  display: flex;
  gap: 1rem;
  margin-top: 1rem;
}

.use-btn {
  padding: 16px 40px;
  font-size: 1.125rem;
  font-weight: 600;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.3);
}

.use-btn:hover {
  transform: translateY(-2px);
  background: #2563eb;
  box-shadow: 0 20px 25px -5px rgba(59, 130, 246, 0.4);
}

.secondary-btn {
  padding: 16px 40px;
  font-size: 1.125rem;
  font-weight: 600;
  background: white;
  color: #334155;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.secondary-btn:hover {
  background: #f1f5f9;
}

/* 5. 图片背景页 */
.page2, .page3, .page4 {
  background-image: url('@/assets/home/主页照片1.png');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}

/* 6. 交互元素 - 更好的向下指引 */
.scroll-arrow {
  position: fixed;
  bottom: 30px;
  left: 50%;
  transform: translateX(-50%);
  cursor: pointer;
  z-index: 100;
  opacity: 0.6;
  transition: 0.3s;
}

.scroll-arrow:hover { opacity: 1; }

.mouse {
  width: 26px;
  height: 42px;
  border: 2px solid #64748b;
  border-radius: 20px;
  display: flex;
  justify-content: center;
  padding-top: 8px;
}

.wheel {
  width: 4px;
  height: 8px;
  background: #3b82f6;
  border-radius: 2px;
  animation: scroll-anim 2s infinite;
}

@keyframes scroll-anim {
  0% { transform: translateY(0); opacity: 1; }
  100% { transform: translateY(15px); opacity: 0; }
}

/* 7. 返回顶部 */
.back-top {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: white;
  color: #3b82f6;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.3s;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
}

.back-top:hover {
  background: #3b82f6;
  color: white;
  transform: scale(1.1);
}

/* 8. 响应式微调 */
@media (max-width: 768px) {
  .btn-group { flex-direction: column; width: 100%; }
  .content-box { width: 100%; }
  .main-title { font-size: 2.25rem; }
}
</style>
