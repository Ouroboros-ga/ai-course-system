<template>
  <!-- 动画容器 p2 -->
  <div class="chat-section slide" id="p2">
    <div class="chat-container">
      <!-- 左侧：聊天预览框 -->
      <div class="chat-preview">
        <div class="chat-window">
          <div class="chat-header">Smartrab</div>

          <!-- 聊天内容区 -->
          <div class="chat-body">
            <!-- 用户：气泡 + 头像（一起弹出） -->
            <div class="chat-row user" :class="{ show: msgUserShow }">
              <div class="chat-message user">
                如何理解这个物理概念？
                <span class="chat-time">23:31</span>
              </div>
              <div class="avatar user-avatar">我</div>
            </div>

            <!-- AI 1：气泡 + 头像（一起弹出） -->
            <div class="chat-row bot" :class="{ show: msgBotShow1 }">
              <div class="avatar bot-avatar">AI</div>
              <div class="chat-message bot">
                同学你好，我们可以从这几个方面理解这个物理概念👇
                <span class="chat-time">23:31</span>
              </div>
            </div>

            <!-- AI 2 -->
            <div class="chat-row bot" :class="{ show: msgBotShow2 }">
              <div class="avatar bot-avatar">AI</div>
              <div class="chat-message bot">
                核心要点在于：物体本身就有保持运动或静止的惯性，不需要力来维持运动。
                <span class="chat-time">23:31</span>
              </div>
            </div>

            <!-- AI 3 -->
            <div class="chat-row bot" :class="{ show: msgBotShow3 }">
              <div class="avatar bot-avatar">AI</div>
              <div class="chat-message bot">
                简单说：力是改变物体运动状态的原因，而不是维持物体运动的原因。
                <span class="chat-time">23:31</span>
              </div>
            </div>
          </div>

          <!-- 底部输入框 -->
          <div class="chat-input-bar">
            <div class="input-typing">{{ inputText }}</div>
            <div class="send-btn">发送</div>
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
import { ref, onMounted, onUnmounted } from 'vue'

// ==============================================
// 打字内容
// ==============================================
const pinyin = 'ru he li jie zhe ge wu li gai nian?'
const chinese = '如何理解这个物理概念？'

// 状态
const inputText = ref('')
const msgUserShow = ref(false)
const msgBotShow1 = ref(false)
const msgBotShow2 = ref(false)
const msgBotShow3 = ref(false)

let timeouts = []

// 清理定时器
const clearAllTimeouts = () => {
  timeouts.forEach(clearTimeout)
  timeouts = []
}

// 重置动画
const resetChatAnimation = () => {
  clearAllTimeouts()
  inputText.value = ''
  msgUserShow.value = false
  msgBotShow1.value = false
  msgBotShow2.value = false
  msgBotShow3.value = false
}

// 打字：拼音 → 文字
const typeInputAnimation = async () => {
  // 先打拼音
  for (let i = 0; i < pinyin.length; i++) {
    inputText.value = pinyin.slice(0, i + 1)
    await new Promise(r => timeouts.push(setTimeout(r, 30)))
  }
  // 停顿 → 变中文
  await new Promise(r => timeouts.push(setTimeout(r, 400)))
  inputText.value = ''
  for (let i = 0; i < chinese.length; i++) {
    inputText.value = chinese.slice(0, i + 1)
    await new Promise(r => timeouts.push(setTimeout(r, 80)))
  }
}

// 发送 + 多轮AI回复（头像+气泡一起出）
const sendAnimation = async () => {
  inputText.value = ''
  // 用户消息
  msgUserShow.value = true

  // AI 依次回复
  await new Promise(r => timeouts.push(setTimeout(r, 800)))
  msgBotShow1.value = true

  await new Promise(r => timeouts.push(setTimeout(r, 900)))
  msgBotShow2.value = true

  await new Promise(r => timeouts.push(setTimeout(r, 700)))
  msgBotShow3.value = true
}

// 总动画
const playChatAnimation = () => {
  resetChatAnimation()
  setTimeout(() => {
    typeInputAnimation().then(sendAnimation)
  }, 300)
}

// 进入视口播放
onMounted(() => {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          playChatAnimation()
        } else {
          resetChatAnimation()
        }
      })
    },
    { threshold: 0.3 }
  )
  observer.observe(document.getElementById('p2'))
  onUnmounted(() => observer.disconnect())
})
</script>

<style scoped>
/* 基础结构 */
.chat-section {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
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
  position: relative;
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
  gap: 10px;
  min-height: 380px;
}

/* 头像 + 气泡 行布局（一起动画） */
.chat-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  opacity: 0;
  transform: translateY(20px);
  transition: all 0.4s cubic-bezier(0.25, 1, 0.5, 1);
}
.chat-row.show {
  opacity: 1;
  transform: translateY(0);
}
.chat-row.user {
  justify-content: flex-end;
}
.chat-row.bot {
  justify-content: flex-start;
}

/* 头像 */
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: bold;
  color: #fff;
  flex-shrink: 0;
}
.user-avatar {
  background: #3b82f6;
}
.bot-avatar {
  background: #10b981;
}

/* 气泡 */
.chat-message {
  padding: 10px 14px;
  border-radius: 12px;
  max-width: 75%;
  font-size: 0.95rem;
  position: relative;
  padding-bottom: 20px;
}
.chat-message.user {
  background: #f1f5f9;
  color: #1e293b;
}
.chat-message.bot {
  background: #eff6ff;
  color: #3b82f6;
}

/* 时间 */
.chat-time {
  position: absolute;
  right: 10px;
  bottom: 6px;
  font-size: 0.6rem;
  color: #94a3b8;
}

/* 输入框 */
.chat-input-bar {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border-top: 1px solid #e2e8f0;
  gap: 10px;
}
.input-typing {
  flex: 1;
  padding: 8px 12px;
  border-radius: 20px;
  background: #f8fafc;
  font-size: 0.9rem;
  min-height: 20px;
  color: #334155;
}
.send-btn {
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 500;
}

/* 右侧文字 */
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

/* 手机端 */
@media (max-width: 768px) {
  .chat-section { padding: 100px 20px 60px; min-height: auto; }
  .chat-container { flex-direction: column; gap: 2.5rem; text-align: center; }
  .chat-text { order: 1; text-align: center; }
  .chat-preview { order: 2; width: 100%; justify-content: center; }
  .chat-title { font-size: 2rem; line-height: 1.3; }
  .chat-desc { font-size: 1rem; line-height: 1.7; }
}
</style>
