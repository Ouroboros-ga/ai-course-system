<template>
  <div class="about-page">
    <!-- 顶部标题区 -->
    <section class="about-hero">
      <h1>About</h1>
      <p>基于泛雅平台的 AI 互动智课生成与实时问答系统</p>
    </section>

    <!-- 项目介绍 -->
    <section class="about-section">
      <h2>项目介绍</h2>
      <p>
        本项目依托泛雅教学平台，结合 AI 大模型与 RAG 检索技术，
        实现智能课件生成、课堂互动、7×24 小时实时答疑，
        为教师备课与学生学习提供轻量化、高效率的智慧教学解决方案。
      </p>
    </section>

    <!-- 核心功能 -->
    <section class="about-section">
      <h2>核心功能</h2>
      <div class="feature-grid">
        <div class="card">
          <h3>AI 课件生成</h3>
          <p>自动结构化排版，快速生成教学课件</p>
        </div>
        <div class="card">
          <h3>实时智能答疑</h3>
          <p>基于知识库精准回答，无幻觉、更可靠</p>
        </div>
        <div class="card">
          <h3>学习进度跟踪</h3>
          <p>记录学习轨迹，支持多端续学</p>
        </div>
        <div class="card">
          <h3>极简清爽界面</h3>
          <p>统一设计语言，流畅舒适的使用体验</p>
        </div>
      </div>
    </section>

    <!-- 技术栈 -->
    <section class="about-section">
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
    <footer class="about-footer">
      <p>© 2026 泛雅 AI 智课系统 · 服创=设计项目</p>
    </footer>
  </div>
</template>

<style scoped>
.about-page {
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  font-family: sans-serif;
  padding: 100px 20px 60px;
}

/* 顶部标题 */
.about-hero {
  max-width: 800px;
  margin: 0 auto 60px;
  text-align: center;
}
.about-hero h1 {
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 12px;
}
.about-hero p {
  font-size: 1.1rem;
  color: #64748b;
}

/* 区块通用 */
.about-section {
  max-width: 800px;
  margin: 0 auto 60px;
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
}

/* 底部 */
.about-footer {
  max-width: 800px;
  margin: 100px auto 0;
  text-align: center;
  color: #94a3b8;
  font-size: 0.9rem;
}
</style>
