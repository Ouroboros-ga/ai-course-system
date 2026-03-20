<template>
  <div class="feature-section slide">
    <!-- 标题区 -->
    <div class="feature-header">
      <h2 class="section-title">开启智能学习时代</h2>
      <p class="section-subtitle">
        AI 伴学，让每一次学习<br />
        都更高效
      </p>
    </div>

    <!-- 卡片区域 -->
    <div class="card-wrapper">
      <div class="feature-grid">
        <!-- 第一行 -->
        <div class="feature-card row-1 col-2">
          <div class="card-inner">
            <div class="card-icon blue-bg">📄</div>
            <h3>课件智能生成</h3>
            <p>上传文档自动生成结构化课件，规范信息完整展示。</p>
            <div class="card-actions">
              <button class="action-btn heart-btn" @click="toggleLike(0)">
                {{ liked[0] ? '❤️' : '♡' }}
              </button>
              <button class="action-btn" @click="goToChat">→</button>
            </div>
          </div>
        </div>

        <div class="feature-card row-1 col-3">
          <div class="card-inner">
            <div class="card-icon yellow-bg">✏️</div>
            <h3>随堂习题产出</h3>
            <p>随时随地，自动生成练习与互动任务，沟通协作很便捷。</p>
            <div class="card-actions">
              <button class="action-btn heart-btn" @click="toggleLike(1)">
                {{ liked[1] ? '❤️' : '♡' }}
              </button>
              <button class="action-btn" @click="goToChat">→</button>
            </div>
          </div>
        </div>

        <!-- 第二行 -->
        <div class="feature-card row-2 col-1">
          <div class="card-inner">
            <div class="card-icon circle-blue">🔗</div>
            <h3>进度智能续接</h3>
            <p>清晰备注记录学习轨迹，团队合作更顺畅。</p>
            <div class="card-actions">
              <button class="action-btn heart-btn" @click="toggleLike(2)">
                {{ liked[2] ? '❤️' : '♡' }}
              </button>
              <button class="action-btn" @click="goToChat">→</button>
            </div>
          </div>
        </div>

        <div class="feature-card row-2 col-2">
          <div class="card-inner">
            <div class="card-icon orange-bg">🗣️</div>
            <h3>AI 实时讲解</h3>
            <p>上传课件后，AI 自动朗读页面内容，逐页讲解知识点。</p>
            <div class="card-actions">
              <button class="action-btn heart-btn" @click="toggleLike(3)">
                {{ liked[3] ? '❤️' : '♡' }}
              </button>
              <button class="action-btn" @click="goToChat">→</button>
            </div>
          </div>
        </div>

        <div class="feature-card row-2 col-3">
          <div class="card-inner">
            <div class="card-icon chat-blue">💬</div>
            <h3>智能问答互动</h3>
            <p>随时提问，AI 结合课件精准回答，支持语音交互。</p>
            <div class="card-actions">
              <button class="action-btn heart-btn" @click="toggleLike(4)">
                {{ liked[4] ? '❤️' : '♡' }}
              </button>
              <button class="action-btn" @click="goToChat">→</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

// ✅ 默认全部都是红心
const liked = ref([true, true, true, true, true])

// 切换爱心（带动画）
const toggleLike = (index) => {
  liked.value[index] = !liked.value[index]
}

// 跳转到聊天界面
const goToChat = () => {
  window.location.href = 'http://localhost:5173/chat#/chat'
}
</script>

<style scoped>
/* 核心容器 */
.feature-section {
  width: 100%;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 5%;
  background: #ffffff;
  overflow-x: hidden;
  gap: 80px;
  transition: all 0.5s ease;
}

/* 标题区样式 */
.feature-header {
  flex: 0 0 auto;
  text-align: left;
}

.section-title {
  font-size: 3.5rem;
  font-weight: 800;
  color: #1a1a1a;
  line-height: 1.2;
  margin: 0;
}

.section-subtitle {
  margin-top: 24px;
  color: #6b7280;
  font-size: 1.4rem;
  line-height: 1.7;
}

/* 卡片阵列容器 */
.card-wrapper {
  flex: 0 1 auto;
  display: flex;
  justify-content: center;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 280px);
  grid-auto-rows: 320px;
  gap: 25px;
}

/* 卡片斜度与正向修正 */
.feature-card {
  background: #f7f9fc;
  border-radius: 20px;
  transform: skewX(-10deg);
  transition: all 0.4s cubic-bezier(0.25, 1, 0.5, 1);
}

.card-inner {
  transform: skewX(10deg);
  padding: 40px 30px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.feature-card:hover {
  background: #fff;
  box-shadow: 0 20px 40px rgba(0,0,0,0.08);
  transform: skewX(-10deg) translateY(-10px);
  z-index: 10;
}

/* 错位排版控制 */
.col-1 { grid-column: 1; }
.col-2 { grid-column: 2; }
.col-3 { grid-column: 3; }
.row-1 { grid-row: 1; }
.row-2 { grid-row: 2; }

/* 图标与文字 */
.card-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  margin-bottom: 25px;
}

.blue-bg { background: #e6f7ff; color: #1890ff; }
.yellow-bg { background: #fffbe6; color: #faad14; }
.orange-bg { background: #fff7e6; color: #ffa940; }
.circle-blue { background: #e6f4ff; color: #1677ff; border-radius: 50%; }
.chat-blue { background: #e6faff; color: #13c2c2; }

.feature-card h3 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #111827;
  margin-bottom: 15px;
}

.feature-card p {
  font-size: 1.05rem;
  color: #4b5563;
  line-height: 1.6;
  flex: 1;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.action-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #9ca3af;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.25s ease;
}

/* ✅ 爱心动画：缩放 + 弹跳 */
.heart-btn {
  transition: transform 0.3s cubic-bezier(0.25, 1, 0.5, 1);
}
.heart-btn:active {
  transform: scale(0.7);
}

/* 箭头悬浮 */
.action-btn:last-child:hover {
  background: #f0f4ff;
  color: #3b82f6;
  transform: translateX(3px);
}

/* ============================================================
   响应式
   ============================================================ */
@media (max-width: 1350px) {
  .feature-section {
    flex-direction: column;
    align-items: center;
    padding-top: 100px;
    gap: 60px;
  }
  .feature-header {
    text-align: center;
  }
  .section-title {
    font-size: 3.2rem;
  }
}

@media (max-width: 950px) {
  .feature-grid {
    grid-template-columns: repeat(3, 240px);
    grid-auto-rows: 280px;
  }
}

@media (max-width: 768px) {
  .feature-section {
    padding: 60px 20px;
  }
  .feature-grid {
    grid-template-columns: 1fr;
    grid-auto-rows: auto;
    max-width: 450px;
  }
  .feature-card, .card-inner {
    transform: none;
    height: auto;
  }
  .row-1, .row-2, .col-1, .col-2, .col-3 {
    grid-column: auto !important;
    grid-row: auto !important;
  }
  .section-title {
    font-size: 2.2rem;
  }
}
</style>
