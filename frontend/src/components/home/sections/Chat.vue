<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { Bot, User, Send, Sparkles, ArrowRight } from 'lucide-vue-next'

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
  for (let i = 0; i < pinyin.length; i++) {
    inputText.value = pinyin.slice(0, i + 1)
    await new Promise(r => timeouts.push(setTimeout(r, 30)))
  }
  await new Promise(r => timeouts.push(setTimeout(r, 400)))
  inputText.value = ''
  for (let i = 0; i < chinese.length; i++) {
    inputText.value = chinese.slice(0, i + 1)
    await new Promise(r => timeouts.push(setTimeout(r, 80)))
  }
}

// 发送 + 多轮 AI 回复
const sendAnimation = async () => {
  inputText.value = ''
  msgUserShow.value = true

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
  const el = document.getElementById('p2')
  if (el) observer.observe(el)
  onUnmounted(() => observer.disconnect())
})
</script>

<template>
  <div class="chat-section slide" id="p2">
    <div class="chat-container">
      <!-- 左侧：文字说明 + CTA -->
      <div class="chat-text">
        <div class="eyebrow">
          <Sparkles :size="16" />
          <span>AI 实时答疑</span>
        </div>
        <h2 class="chat-title">
          7×24 小时
          <br />
          <span class="gradient-text">AI 实时答疑</span>
        </h2>
        <p class="chat-desc">
          基于 RAG 精准检索课程知识库，回答可靠无幻觉。
          支持知识点讲解、作业辅导、课堂即时答疑。
        </p>
        <button class="cta-btn" @click="$emit('go-chat')">
          立即体验
          <ArrowRight :size="18" class="btn-icon" />
        </button>
      </div>

      <!-- 右侧：模拟聊天卡片 -->
      <div class="chat-preview">
        <div class="chat-window">
          <!-- 聊天头部 -->
          <div class="chat-header">
            <div class="header-avatar">
              <Bot :size="18" />
            </div>
            <span class="header-name">Smartrab AI</span>
            <span class="header-status">在线</span>
          </div>

          <!-- 聊天内容区 -->
          <div class="chat-body">
            <!-- 用户消息 -->
            <div class="chat-row user" :class="{ show: msgUserShow }">
              <div class="chat-message user">
                如何理解这个物理概念？
                <span class="chat-time">23:31</span>
              </div>
              <div class="avatar user-avatar">
                <User :size="16" />
              </div>
            </div>

            <!-- AI 回复 -->
            <div class="chat-row bot" :class="{ show: msgBotShow1 }">
              <div class="avatar bot-avatar">
                <Bot :size="16" />
              </div>
              <div class="chat-message bot">
                同学你好，我们可以从这几个方面理解这个物理概念。
                <span class="chat-time">23:31</span>
              </div>
            </div>

            <div class="chat-row bot" :class="{ show: msgBotShow2 }">
              <div class="avatar bot-avatar">
                <Bot :size="16" />
              </div>
              <div class="chat-message bot">
                核心要点在于：物体本身就有保持运动或静止的惯性，不需要力来维持运动。
                <span class="chat-time">23:31</span>
              </div>
            </div>

            <div class="chat-row bot" :class="{ show: msgBotShow3 }">
              <div class="avatar bot-avatar">
                <Bot :size="16" />
              </div>
              <div class="chat-message bot">
                简单说：力是改变物体运动状态的原因，而不是维持运动的原因。
                <span class="chat-time">23:31</span>
              </div>
            </div>
          </div>

          <!-- 底部输入框 -->
          <div class="chat-input-bar">
            <div class="input-typing">{{ inputText }}</div>
            <button class="send-btn" aria-label="发送消息">
              <Send :size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-section {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 var(--space-12);
  background: var(--color-bg);
}

.chat-container {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  width: 100%;
  max-width: 1200px;
}

/* ── 左侧文字 ── */
.chat-text {
  flex: 1;
  text-align: left;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-primary);
  margin-bottom: var(--space-4);
}

.eyebrow svg {
  color: var(--color-primary);
}

.chat-title {
  font-size: var(--text-4xl);
  font-weight: var(--font-extrabold);
  line-height: var(--leading-tight);
  margin-bottom: var(--space-6);
  color: var(--color-text);
}

.gradient-text {
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.chat-desc {
  font-size: var(--text-lg);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-8);
}

.cta-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-8);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-xl);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  cursor: pointer;
  box-shadow: var(--shadow-primary);
  transition: var(--transition-all);
}

.cta-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  background: var(--gradient-primary-hover);
}

.btn-icon {
  transition: transform var(--duration-normal) var(--ease);
}

.cta-btn:hover .btn-icon {
  transform: translateX(4px);
}

/* ── 右侧聊天卡片 ── */
.chat-preview {
  flex: 1;
  display: flex;
  justify-content: center;
}

.chat-window {
  width: 100%;
  max-width: 400px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.chat-header {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  padding: var(--space-4) var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.header-avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-name {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  flex: 1;
}

.header-status {
  font-size: var(--text-xs);
  padding: var(--space-1) var(--space-2);
  background: rgba(255, 255, 255, 0.2);
  border-radius: var(--radius-full);
}

.chat-body {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 360px;
}

/* 头像 + 气泡 */
.chat-row {
  display: flex;
  gap: var(--space-2);
  align-items: flex-end;
  opacity: 0;
  transform: translateY(16px);
  transition: all var(--duration-slow) var(--ease-spring);
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

.avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
  flex-shrink: 0;
}

.user-avatar {
  background: var(--color-primary);
}

.bot-avatar {
  background: var(--color-success);
}

.chat-message {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  max-width: 75%;
  font-size: var(--text-sm);
  position: relative;
  padding-bottom: var(--space-6);
  line-height: var(--leading-relaxed);
}

.chat-message.user {
  background: var(--color-surface-2);
  color: var(--color-text);
  border-radius: var(--radius-lg) var(--radius-sm) var(--radius-lg) var(--radius-lg);
}

.chat-message.bot {
  background: var(--color-primary-light);
  color: var(--color-text);
  border-radius: var(--radius-sm) var(--radius-lg) var(--radius-lg) var(--radius-lg);
}

.chat-time {
  position: absolute;
  right: var(--space-3);
  bottom: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* 输入框 */
.chat-input-bar {
  display: flex;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border);
  gap: var(--space-3);
}

.input-typing {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  background: var(--color-bg);
  font-size: var(--text-sm);
  min-height: 20px;
  color: var(--color-text);
}

.send-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  flex-shrink: 0;
  transition: var(--transition-all);
}

.send-btn:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary);
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .chat-container {
    gap: var(--space-8);
  }
  .chat-title {
    font-size: var(--text-3xl);
  }
}

@media (max-width: 768px) {
  .chat-section {
    padding: var(--space-10) var(--space-5);
    min-height: auto;
  }
  .chat-container {
    flex-direction: column;
    gap: var(--space-8);
    text-align: center;
  }
  .chat-text {
    text-align: center;
  }
  .chat-title {
    font-size: var(--text-2xl);
  }
  .chat-desc {
    font-size: var(--text-base);
  }
  .chat-preview {
    width: 100%;
  }
}

@media (max-width: 375px) {
  .chat-window {
    max-width: 100%;
  }
  .chat-body {
    min-height: 300px;
  }
}

/* 无障碍 */
@media (prefers-reduced-motion: reduce) {
  .chat-row {
    transition: none;
    opacity: 1;
    transform: none;
  }
  .cta-btn:hover,
  .send-btn:hover {
    transform: none;
  }
}
</style>
