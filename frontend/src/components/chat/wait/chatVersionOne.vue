<template>
  <div class="chat-page-container">

    <!-- 左侧：课件展示区 -->
    <div class="ppt-section">
      <!-- 顶部信息 -->
      <div class="section-header">
        <div class="header-info">
          <h2>计算机组成原理 - 第 3 章：存储器系统</h2>
          <p>当前进度：12 / 45 页</p>
        </div>
        <button class="btn-knowledge">
          <span>📄</span> 知识图谱
        </button>
      </div>

      <!-- PPT 容器 -->
      <div class="ppt-display-area">
        <div class="ppt-placeholder">
          <div style="font-size: 48px; color: #fee2e2; margin-bottom: 16px;">📊</div>
          <p>PPT 第 12 页预览区域</p>
          <span style="font-size: 12px; color: #9ca3af;">(此处接入 PDF/PPT 渲染组件)</span>
        </div>

        <!-- 底部控制条 -->
        <div class="ai-control-bar">
          <div class="control-left">
            <button class="btn-play">⏸</button>
            <div class="progress-info">
              <span class="status-text">AI 讲师正在讲解...</span>
              <div class="progress-track"><div class="progress-fill"></div></div>
            </div>
          </div>
          <div class="control-right">
            <button title="回退">↺</button>
            <span class="speed-tag">1.0x</span>
            <button title="音量">🔊</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：聊天交互区 -->
    <div class="chat-section">
      <!-- 聊天头部 -->
      <div class="chat-header">
        <div class="assistant-status">
          <div class="status-dot"></div>
          <span>AI 助教</span>
        </div>
        <button class="btn-more"></button>
      </div>

      <!-- 消息列表 -->
      <div class="message-list">
        <div class="time-stamp">14:30</div>

        <!-- 循环消息 -->
        <div v-for="(msg, index) in messages" :key="index"
             :class="['message-row', msg.role === 'user' ? 'row-user' : 'row-ai']">

          <!-- 头像 -->
          <div class="avatar" :class="msg.role === 'ai' ? 'avatar-ai' : 'avatar-user'">
            <img v-if="msg.role === 'user'" src="https://api.dicebear.com/7.x/avataaars/svg?seed=Felix" alt="User">
            <span v-else>AI</span>
          </div>

          <!-- 气泡 -->
          <div class="bubble-container">
            <div class="message-bubble" :class="msg.role === 'user' ? 'bubble-user' : 'bubble-ai'">
              <div v-html="msg.content"></div>

              <!-- 进度接续按钮 -->
              <div v-if="msg.showResumeBtn" class="resume-action">
                <button class="btn-resume">
                  <span>⏪</span> 回到刚才的讲解进度
                </button>
              </div>
            </div>
            <!-- 标签 -->
            <div v-if="msg.tags" class="tags-row">
              <span v-for="tag in msg.tags" :key="tag" class="tag-item">{{ tag }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <div class="quick-tips">
          <button v-for="tip in quickTips" :key="tip" class="tip-chip">{{ tip }}</button>
        </div>
        <div class="input-box-wrapper">
          <input type="text" v-model="inputContent" @keyup.enter="sendMessage" placeholder="输入问题，或点击右侧麦克风...">
          <button class="btn-mic">🎤</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive } from 'vue';

const messages = reactive([
  {
    role: 'ai',
    content: '同学们好，我们现在讲到<strong>"Cache 映射方式”</strong>。大家看屏幕上的这张图，这是直接映射的原理...',
    tags: ['知识点：直接映射']
  },
  {
    role: 'user',
    content: '等一下，这里如果发生冲突了怎么办？'
  },
  {
    role: 'ai',
    content: '好问题！在直接映射中，如果两个主存块映射到同一个 Cache 行，就会发生<strong>冲突</strong>，后调入的块会替换掉先前的块。<br><div style="font-size:12px; color:#6b7280; background:#f9fafb; padding:8px; border-radius:4px; margin-top:8px; border:1px solid #e5e7eb;">ℹ️ 是否需要我详细讲解“替换算法”？</div>',
    showResumeBtn: true
  }
]);

const inputContent = ref('');
const quickTips = ['没听懂，再讲一遍', '这页 PPT 重点是什么？', '快进 5 分钟'];

const sendMessage = () => {
  if (!inputContent.value.trim()) return;
  messages.push({ role: 'user', content: inputContent.value });
  inputContent.value = '';
  // 简单滚动到底部
  setTimeout(() => {
    const list = document.querySelector('.message-list');
    if(list) list.scrollTop = list.scrollHeight;
  }, 50);
};
</script>

<style scoped>
/* 容器布局 */
.chat-page-container {
  display: flex;
  gap: 16px;
  padding: 16px;
  height: 100%; /* 填满父容器 */
  width: 100%;
  box-sizing: border-box;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* 左侧 PPT 区 */
.ppt-section {
  flex: 7;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0; /* 防止内容溢出 */
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px;
}

.section-header h2 {
  font-size: 18px;
  color: #1f2937;
  margin: 0 0 4px 0;
}

.section-header p {
  font-size: 12px;
  color: #6b7280;
  margin: 0;
}

.btn-knowledge {
  background: #eff6ff;
  color: #2563eb;
  border: none;
  padding: 6px 12px;
  border-radius: 99px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}

.ppt-display-area {
  flex: 1;
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1);
  border: 1px solid #f3f4f6;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ppt-placeholder {
  text-align: center;
  color: #9ca3af;
}

/* 底部控制条 */
.ai-control-bar {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: 90%;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(8px);
  border-radius: 16px;
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.2);
  border: 1px solid rgba(255,255,255,0.5);
}

.control-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-play {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #2563eb;
  color: white;
  border: none;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.progress-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 128px;
}

.status-text {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
}

.progress-track {
  height: 6px;
  background: #f3f4f6;
  border-radius: 99px;
  overflow: hidden;
}

.progress-fill {
  width: 66%;
  height: 100%;
  background: #3b82f6;
  border-radius: 99px;
}

.control-right {
  display: flex;
  gap: 16px;
  color: #6b7280;
  align-items: center;
}

.control-right button {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  color: inherit;
}

.speed-tag {
  font-size: 12px;
  font-family: monospace;
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
}

/* 右侧 聊天区 */
.chat-section {
  flex: 3;
  background: white;
  border-radius: 16px;
  border: 1px solid #f3f4f6;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
}

.chat-header {
  padding: 16px;
  border-bottom: 1px solid #f9fafb;
  background: #f9fafb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.assistant-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #374151;
}

.status-dot {
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
}

.btn-more {
  background: none;
  border: none;
  font-size: 18px;
  color: #9ca3af;
  cursor: pointer;
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.time-stamp {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin: 4px 0;
}

.message-row {
  display: flex;
  gap: 12px;
}

.row-user {
  flex-direction: row-reverse;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
}

.avatar-ai { background: #dbeafe; color: #2563eb; }
.avatar-user { background: #e5e7eb; }
.avatar-user img { width: 100%; height: 100%; }

.bubble-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 85%;
}

.row-user .bubble-container {
  align-items: flex-end;
}

.message-bubble {
  padding: 12px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.5;
  box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
  border: 1px solid transparent;
}

.bubble-ai {
  background: white;
  color: #374151;
  border-top-left-radius: 4px;
  border-color: #f3f4f6;
}

.bubble-user {
  background: #2563eb;
  color: white;
  border-top-right-radius: 4px;
}

.resume-action {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #eff6ff;
}

.btn-resume {
  width: 100%;
  background: #eff6ff;
  color: #2563eb;
  border: none;
  padding: 8px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.tags-row {
  display: flex;
  gap: 6px;
}

.tag-item {
  font-size: 10px;
  background: #eff6ff;
  color: #2563eb;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #dbeafe;
}

/* 输入区 */
.input-area {
  padding: 16px;
  background: white;
  border-top: 1px solid #f3f4f6;
}

.quick-tips {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.tip-chip {
  white-space: nowrap;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  padding: 6px 12px;
  border-radius: 99px;
  font-size: 12px;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.2s;
}

.tip-chip:hover {
  border-color: #93c5fd;
  color: #2563eb;
  background: #eff6ff;
}

.input-box-wrapper {
  position: relative;
}

.input-box-wrapper input {
  width: 100%;
  padding: 12px 48px 12px 16px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  font-size: 14px;
  box-sizing: border-box;
  outline: none;
}

.input-box-wrapper input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.btn-mic {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  font-size: 18px;
  color: #9ca3af;
  cursor: pointer;
}
</style>
