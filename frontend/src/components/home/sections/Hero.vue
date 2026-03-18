<template>
  <section class="slide hero-page">
    <div class="split-content">
      <div class="text-side">
        <h1 class="main-title">泛雅 AI 智课<br /><span class="text-blue">实时互动</span></h1>
        <p class="description">免费试用・重构课堂体验。融合 RAG 与大模型技术，自动生成互动课件、智能续接学习进度、7×24 小时实时答疑。</p>
        <div class="btn-group">
          <button class="use-btn" @click="$emit('go-chat')">立即使用</button>
        </div>
      </div>
      <div class="visual-side">
        <div class="image-placeholder main-hero-img"><div class="abstract-shape"></div></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.slide { width: 100%; height: 100vh; scroll-snap-align: start; display: flex; align-items: center; justify-content: center; padding: 0 10%; }
.hero-page { background: radial-gradient(circle at 20% 50%, rgba(59, 130, 246, 0.12), transparent 45%), radial-gradient(circle at 80% 80%, rgba(124, 58, 237, 0.08), transparent 40%), #f8fafc; }
.split-content { display: flex; align-items: center; gap: 4rem; width: 100%; max-width: 1200px; }
.text-side { flex: 1; text-align: left; }
.visual-side { flex: 1; display: flex; justify-content: center; }
.main-title { font-size: 3.5rem; font-weight: 800; line-height: 1.2; margin-bottom: 1.5rem; background: linear-gradient(90deg, #0f172a, #3b82f6, #8b5cf6); background-size: 200% 200%; -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: flow 6s ease infinite; }
@keyframes flow { 0% { background-position: 0 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
.text-blue { color: #3b82f6; }
.description { font-size: 1.2rem; color: #64748b; line-height: 1.6; margin-bottom: 2rem; }
.btn-group { display: flex; gap: 1rem; justify-content: flex-start; }
.use-btn { padding: 1.2rem 3.2rem; background: #3b82f6; color: white; border: none; border-radius: 14px; font-size: 1.15rem; font-weight: 600; cursor: pointer; transition: 0.3s; box-shadow: 0 8px 25px rgba(59, 130, 246, 0.25); position: relative; overflow: hidden; }
.use-btn::after { content: ''; position: absolute; top: 0; left: -100%; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); transition: 0.5s; }
.use-btn:hover::after { left: 100%; }
.use-btn:hover { background: #2563eb; transform: translateY(-3px); box-shadow: 0 14px 32px rgba(59, 130, 246, 0.35); }
.image-placeholder { width: 100%; max-width: 500px; height: 350px; border-radius: 24px; position: relative; overflow: hidden; background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); }
.abstract-shape { position: absolute; width: 220px; height: 220px; background: linear-gradient(90deg, #3b82f6, #8b5cf6); filter: blur(90px); opacity: 0.25; top: 20%; left: 20%; }
</style>
