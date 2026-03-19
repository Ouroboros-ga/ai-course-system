<template>
  <div class="feature-section">
    <div class="feature-grid">

      <!-- 卡片 1：课件智能生成 -->
      <div class="feature-card">
        <div class="card-icon">📄</div>
        <h3>课件智能生成</h3>
        <p>上传文档自动生成结构化课件，省去手动排版烦恼。</p>
      </div>

      <!-- 卡片 2：随堂习题产出 -->
      <div class="feature-card">
        <div class="card-icon">✏️</div>
        <h3>随堂习题产出</h3>
        <p>AI 一键生成练习题与互动任务，实时反馈学习效果。</p>
      </div>

      <!-- 卡片 3：进度智能续接 -->
      <div class="feature-card">
        <div class="card-icon">🔗</div>
        <h3>进度智能续接</h3>
        <p>自动记录学习轨迹，支持跨设备断点续学。</p>
      </div>

    </div>
  </div>
</template>

<style scoped>
.feature-section {
  width: 100%;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 120px 10% 60px; /* 顶部 padding 防止被导航挡住 */
  background: #f8fafc;
}

/* 电脑版：一排三个 */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 28px;
  width: 100%;
  max-width: 1200px;
}

.feature-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 32px 24px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  transition: 0.3s;
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
}

.feature-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 24px rgba(0,0,0,0.1);
}

.card-icon {
  font-size: 48px;
  margin-bottom: 20px;
}

.feature-card h3 {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px;
}

.feature-card p {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
}

/* 📱 手机版：自动变成一排一个 */
@media (max-width: 768px) {
  .feature-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }

  .feature-section {
    padding: 100px 20px 40px;
  }
}
</style>
