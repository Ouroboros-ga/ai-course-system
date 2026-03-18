<template>
  <section class="slide bg-white">
    <div class="container-narrow">
      <h2 class="section-title">AI 智课生成・让备课更简单</h2>
      <div class="feature-cards">
        <div class="f-card"><div class="f-icon">📄</div><h3>课件智能生成</h3><p>上传文档自动生成结构化课件，省去手动排版烦恼。</p></div>
        <div class="f-card"><div class="f-icon">✍️</div><h3>随堂习题产出</h3><p>AI一键生成练习题与互动任务，实时反馈学习效果。</p></div>
        <div class="f-card"><div class="f-icon">🔗</div><h3>进度智能续接</h3><p>自动记录学习轨迹，支持跨设备断点续学。</p></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.slide { width: 100%; height: 100vh; scroll-snap-align: start; display: flex; align-items: center; justify-content: center; padding: 0 10%; }
.bg-white { background: #fff; }
.container-narrow { max-width: 1000px; width: 100%; text-align: center; }
.section-title { font-size: 2.5rem; color: #0f172a; margin-bottom: 3rem; font-weight: 700; }
.feature-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; }
.f-card { padding: 2.5rem; background: white; border-radius: 22px; border: 1px solid #e2e8f0; text-align: left; transition: 0.4s; position: relative; overflow: hidden; }
.f-card::before { content: ''; position: absolute; top:0; left:0; right:0; height:4px; background: linear-gradient(90deg, #3b82f6, #8b5cf6); }
.f-card:hover { transform: translateY(-12px); box-shadow: 0 18px 40px rgba(59,130,246,0.12); border-color: #cbd5e1; }
.f-icon { font-size: 2.6rem; margin-bottom: 1.4rem; }
</style>
