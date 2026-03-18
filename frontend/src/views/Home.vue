<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const containerRef = ref(null)

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
    <div class="main-container" ref="containerRef">

      <!-- 第 1 屏：主视觉页 (左右布局) -->
      <section class="slide hero-page">
        <div class="split-content">
          <div class="text-side">
            <div class="badge">Next-Gen AI</div>
            <h1 class="main-title">
              泛雅 AI 智课 <br>
              <span class="text-blue">实时互动</span>
            </h1>
            <p class="description">
              免费试用・重构课堂体验。融合 RAG 与大模型技术，自动生成互动课件、智能续接学习进度、7×24 小时实时答疑。
            </p>
            <div class="btn-group">
              <button class="use-btn" @click="goToChat">立即使用</button>
            </div>
          </div>
          <div class="visual-side">
            <!-- 建议配合一张 AI 教学场景的 3D 插画或产品截图 -->
            <div class="image-placeholder main-hero-img">
              <div class="abstract-shape"></div>
              <p>产品核心展示图</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 第 2 屏：AI 智课核心功能 (卡片布局) -->
      <section class="slide bg-white">
        <div class="container-narrow">
          <h2 class="section-title">AI 智课生成・让备课更简单</h2>
          <div class="feature-cards">
            <div class="f-card">
              <div class="f-icon">📄</div>
              <h3>课件智能生成</h3>
              <p>上传文档自动生成结构化课件，省去手动排版烦恼。</p>
            </div>
            <div class="f-card">
              <div class="f-icon">✍️</div>
              <h3>随堂习题产出</h3>
              <p>AI 一键生成练习题与互动任务，实时反馈学习效果。</p>
            </div>
            <div class="f-card">
              <div class="f-icon">🔗</div>
              <h3>进度智能续接</h3>
              <p>自动记录学习轨迹，支持跨设备断点续学。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 第 3 屏：AI 实时问答 (模拟对话框布局) -->
      <section class="slide qna-page bg-gray">
        <div class="split-content flex-reverse">
          <div class="text-side">
            <h2 class="section-title text-left">7×24 小时 <br>AI 实时答疑</h2>
            <p class="description">
              基于 RAG 精准检索泛雅平台知识库，回答可靠无幻觉。支持知识点讲解、作业辅导、课堂即时答疑。
            </p>
          </div>
          <div class="visual-side">
            <!-- 模拟 AI 对话组件 -->
            <div class="mock-chat-window">
              <div class="chat-header">泛雅 AI 助手</div>
              <div class="chat-body">
                <div class="msg user">如何理解这个物理概念？</div>
                <div class="msg ai">根据课件第三章，核心要点在于...</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 第 4 屏：项目价值 (四宫格布局) -->
      <section class="slide bg-white">
        <div class="container-narrow">
          <h2 class="section-title">赋能智慧教育・升级课堂体验</h2>
          <div class="value-grid">
            <div class="v-item">
              <span class="v-num">01</span>
              <h4>高校教学</h4>
              <p>定制化适配课程，辅助老师打造高水平课堂。</p>
            </div>
            <div class="v-item">
              <span class="v-num">02</span>
              <h4>线上学习</h4>
              <p>打破时空限制，学生随时随地获得指导。</p>
            </div>
            <div class="v-item">
              <span class="v-num">03</span>
              <h4>教师备课</h4>
              <p>解放生产力，让老师更聚焦于教学设计。</p>
            </div>
            <div class="v-item">
              <span class="v-num">04</span>
              <h4>效率提升</h4>
              <p>无广告无水印，轻量化交互体验。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 第 5 屏：结尾页 (居中收尾) -->
      <section class="slide end-page hero-page">
        <div class="content-box">
          <h2 class="main-title">立即开启你的 <span class="text-blue">AI 智课</span> 之旅</h2>
          <p class="description">免费试用，无需注册，即刻体验智能教学新方式</p>
          <div class="btn-group">
            <button class="use-btn" @click="goToChat">立即使用</button>
            <button class="secondary-btn" @click="goNext">了解更多</button>
          </div>
        </div>
      </section>

    </div>

    <!-- UI 部件: 滚动指示线 -->
    <div class="scroll-arrow" @click="goNext">
      <div class="mouse"><div class="wheel"></div></div>
    </div>

    <!-- UI 部件: 回到顶部按钮 -->
    <button class="back-top" @click="goToTop">
      <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="3">
        <path d="M18 15l-6-6-6 6" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
/* 基础容器 */
.home-wrapper {
  position: fixed; inset: 0; overflow: hidden; background: #f8fafc; font-family: sans-serif;
}
.main-container {
  width: 100%; height: 100%; overflow-y: auto; scroll-behavior: smooth;
  scroll-snap-type: y mandatory; scrollbar-width: none;
}
.main-container::-webkit-scrollbar { display: none; }

.slide {
  width: 100%; height: 100vh; scroll-snap-align: start;
  display: flex; align-items: center; justify-content: center; padding: 0 10%;
}

/* 布局部件 */
.split-content {
  display: flex; align-items: center; gap: 4rem; width: 100%; max-width: 1200px;
}
.flex-reverse { flex-direction: row-reverse; }
.text-side { flex: 1; text-align: left; }
.visual-side { flex: 1; display: flex; justify-content: center; }

.container-narrow { max-width: 1000px; width: 100%; text-align: center; }

/* 文本样式 */
.main-title { font-size: 3.5rem; font-weight: 800; color: #0f172a; line-height: 1.2; margin-bottom: 1.5rem; }
.text-blue { color: #3b82f6; }
.description { font-size: 1.2rem; color: #64748b; line-height: 1.6; margin-bottom: 2rem; }
.section-title { font-size: 2.5rem; color: #0f172a; margin-bottom: 3rem; font-weight: 700; }
.text-left { text-align: left; }

.badge {
  display: inline-block; padding: 0.5rem 1rem; background: rgba(59, 130, 246, 0.1);
  color: #3b82f6; border-radius: 50px; font-weight: 600; font-size: 0.9rem; margin-bottom: 1rem;
}

/* 视觉模拟部件 (Placeholder) */
.image-placeholder {
  width: 100%; max-width: 500px; height: 350px; background: #e2e8f0;
  border-radius: 24px; display: flex; align-items: center; justify-content: center;
  position: relative; overflow: hidden; border: 1px solid #cbd5e1;
}
.main-hero-img { background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); }
.abstract-shape {
  position: absolute; width: 200px; height: 200px; background: #3b82f6;
  filter: blur(80px); opacity: 0.2; top: 20%; left: 20%;
}

/* 对话框模拟组件 */
.mock-chat-window {
  width: 320px; background: white; border-radius: 16px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1);
  border: 1px solid #e2e8f0; overflow: hidden;
}
.chat-header { background: #3b82f6; color: white; padding: 12px; font-weight: 600; text-align: center; }
.chat-body { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.msg { padding: 10px 14px; border-radius: 12px; font-size: 0.9rem; max-width: 80%; }
.msg.user { background: #f1f5f9; align-self: flex-end; color: #334155; }
.msg.ai { background: #eff6ff; align-self: flex-start; color: #1e40af; border: 1px solid #dbeafe; }

/* 卡片布局 */
.feature-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; }
.f-card {
  padding: 2.5rem; background: #f8fafc; border-radius: 20px; transition: 0.3s;
  border: 1px solid #e2e8f0; text-align: left;
}
.f-card:hover { transform: translateY(-10px); background: white; box-shadow: 0 10px 30px rgba(0,0,0,0.05); }
.f-icon { font-size: 2.5rem; margin-bottom: 1.5rem; }
.f-card h3 { margin-bottom: 1rem; color: #0f172a; }

/* 四宫格布局 */
.value-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }
.v-item {
  display: flex; flex-direction: column; align-items: flex-start; text-align: left;
  padding: 2rem; border-bottom: 1px solid #e2e8f0;
}
.v-num { font-size: 0.9rem; font-weight: 800; color: #3b82f6; margin-bottom: 0.5rem; }
.v-item h4 { font-size: 1.25rem; margin-bottom: 0.5rem; color: #0f172a; }

/* 按钮与交互 */
.btn-group { display: flex; gap: 1rem; justify-content: center; }
.end-page .btn-group { justify-content: center; }
.hero-page .btn-group { justify-content: flex-start; }

.use-btn {
  padding: 1rem 2.5rem; background: #3b82f6; color: white; border: none;
  border-radius: 12px; font-size: 1.1rem; font-weight: 600; cursor: pointer; transition: 0.3s;
}
.use-btn:hover { background: #2563eb; transform: scale(1.05); }

.secondary-btn {
  padding: 1rem 2.5rem; background: white; color: #64748b; border: 1px solid #e2e8f0;
  border-radius: 12px; font-size: 1.1rem; cursor: pointer;
}

/* 指示部件 */
.scroll-arrow {
  position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
  cursor: pointer; opacity: 0.5;
}
.mouse {
  width: 24px; height: 38px; border: 2px solid #64748b; border-radius: 12px;
  display: flex; justify-content: center; padding-top: 6px;
}
.wheel { width: 4px; height: 8px; background: #3b82f6; border-radius: 2px; animation: scroll-v 2s infinite; }
@keyframes scroll-v { 0% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(15px); } }

.back-top {
  position: fixed; right: 2rem; bottom: 2rem; width: 3rem; height: 3rem;
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  cursor: pointer; display: flex; align-items: center; justify-content: center; color: #3b82f6;
}

/* 响应式 */
@media (max-width: 968px) {
  .split-content { flex-direction: column; text-align: center; gap: 2rem; }
  .text-side { text-align: center; }
  .feature-cards, .value-grid { grid-template-columns: 1fr; }
  .hero-page .btn-group { justify-content: center; }
  .main-title { font-size: 2.5rem; }
}
</style>
