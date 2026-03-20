<template>
  <div class="chat-section slide">
    <div class="chat-container">
      <!-- 左侧：聊天预览框 -->
      <div class="chat-preview">
        <div class="chat-window">
          <div class="chat-header">泛雅 AI 助手</div>
          <div class="chat-body">
            <div class="chat-message user">
              如何理解这个物理概念？
            </div>
            <div class="chat-message bot">
              核心要点在...
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：文字说明 -->
      <div class="chat-text">
        <h2 class="chat-title">
          7×24 小时
          <br />
          AI 实时答疑
        </h2>
        <p class="chat-desc">
          基于 RAG 精准检索泛雅平台知识库，回答可靠无幻觉。<br />
          支持知识点讲解、作业辅导、课堂即时答疑。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
/* 基础结构 */
.chat-section {
  width: 100%;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 10%;
  background: #f8fafc;
}

.chat-container {
  display: flex;
  align-items: center;
  gap: 4rem;
  width: 100%;
  max-width: 1200px;
}

/* 聊天预览框 */
.chat-preview {
  flex: 1;
  display: flex;
  justify-content: flex-start;
}

.chat-window {
  width: 100%;
  max-width: 380px;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}

.chat-header {
  background: #3b82f6;
  color: white;
  padding: 12px 16px;
  font-size: 1.2rem;
  font-weight: 600;
}

.chat-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-message {
  padding: 10px 14px;
  border-radius: 12px;
  max-width: 85%;
  font-size: 0.95rem;
}

.chat-message.user {
  background: #f1f5f9;
  align-self: flex-start;
  color: #1e293b;
}

.chat-message.bot {
  background: #eff6ff;
  align-self: flex-end;
  color: #3b82f6;
}

/* 文字说明 */
.chat-text {
  flex: 1;
  text-align: left;
}

.chat-title {
  font-size: 2.8rem;
  font-weight: 800;
  line-height: 1.2;
  margin-bottom: 1.5rem;
  color: #0f172a;
}

.chat-desc {
  font-size: 1.1rem;
  color: #64748b;
  line-height: 1.7;
}

/* ====================================== */
/* 📱 手机端：文字在上，聊天框在下 */
/* ====================================== */
@media (max-width: 768px) {
  .chat-section {
    padding: 100px 20px 60px;
    min-height: auto;
  }

  .chat-container {
    flex-direction: column;
    gap: 2.5rem;
    text-align: center;
  }

  /* 文字在上 */
  .chat-text {
    order: 1 !important;
    text-align: center;
  }

  /* 聊天框在下 */
  .chat-preview {
    order: 2 !important;
    width: 100%;
    justify-content: center;
  }

  .chat-title {
    font-size: 2rem;
    line-height: 1.3;
  }

  .chat-desc {
    font-size: 1rem;
    line-height: 1.7;
  }
}
</style>
