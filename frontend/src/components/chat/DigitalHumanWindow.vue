<template>
  <div class="digital-human-wrapper">
    <Transition name="slide-fade">
      <div v-if="isOpen" class="dh-panel">
        <div class="dh-header">
          <div class="dh-title">
            <span class="dh-avatar">🤖</span>
            <span>数字人</span>
            <span class="dh-status-dot"></span>
          </div>
          <div class="dh-actions">
            <button class="dh-btn" @click="clearMessages" title="清空对话">🗑️</button>
            <button class="dh-btn" @click="togglePanel" title="最小化">➖</button>
          </div>
        </div>

        <div class="dh-messages" ref="messagesRef">
          <div v-if="messages.length === 0" class="dh-welcome">
<!--            <div class="dh-welcome-icon">🎓</div>-->
            <p>数字人窗口</p>
<!--            <p class="dh-welcome-hint">你可以向我提问课程相关的问题</p>-->
          </div>

          <div
            v-for="(msg, index) in messages"
            :key="index"
            :class="['dh-message', msg.role === 'user' ? 'dh-msg-user' : 'dh-msg-ai']"
          >
            <div class="dh-msg-avatar">
              {{ msg.role === 'user' ? '👤' : '🤖' }}
            </div>
            <div class="dh-msg-bubble" :class="msg.role">
              {{ msg.content }}
            </div>
          </div>

          <div v-if="isLoading" class="dh-message dh-msg-ai">
            <div class="dh-msg-avatar">🤖</div>
            <div class="dh-msg-bubble ai typing">
              <span class="dot"></span>
              <span class="dot"></span>
              <span class="dot"></span>
            </div>
          </div>
        </div>

<!--        <div class="dh-input-area">-->
<!--          <input-->
<!--            v-model="inputText"-->
<!--            @keyup.enter="sendMessage"-->
<!--            placeholder="输入你的问题..."-->
<!--            class="dh-input"-->
<!--            :disabled="isLoading"-->
<!--          />-->
<!--          <button-->
<!--            class="dh-send-btn"-->
<!--            @click="sendMessage"-->
<!--            :disabled="!inputText.trim() || isLoading"-->
<!--          >-->
<!--            发送-->
<!--          </button>-->
<!--        </div>-->
      </div>
    </Transition>

    <Transition name="bounce">
      <div v-if="!isOpen" class="dh-fab" @click="togglePanel">
        <span class="fab-icon">🤖</span>
        <span v-if="unreadCount > 0" class="fab-badge">{{ unreadCount }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'
import { showToast } from '@/utils/toast'

const counter = useCounterStore()

const isOpen = ref(false)
const messages = ref([])
const inputText = ref('')
const isLoading = ref(false)
const messagesRef = ref(null)
const unreadCount = ref(0)

const emit = defineEmits(['send'])

function togglePanel() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    unreadCount.value = 0
    nextTick(() => {
      scrollToBottom()
    })
  }
}

function clearMessages() {
  messages.value = []
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isLoading.value) return

  messages.value.push({
    role: 'user',
    content: text,
  })

  inputText.value = ''
  isLoading.value = true
  scrollToBottom()

  try {
    const res = await api.chat.askQuestion({
      question: text,
    })

    messages.value.push({
      role: 'ai',
      content: res.answer || '抱歉，我暂时无法回答这个问题。',
    })

    if (!isOpen.value) {
      unreadCount.value++
    }
  } catch (error) {
    console.error('数字人问答失败:', error)
    messages.value.push({
      role: 'ai',
      content: '抱歉，网络似乎出了点问题，请稍后再试。',
    })
  } finally {
    isLoading.value = false
    scrollToBottom()
  }

  emit('send', text)
}

watch(messages, () => {
  scrollToBottom()
}, { deep: true })
</script>

<style scoped>
.digital-human-wrapper {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 999;
}

.dh-panel {
  width: 360px;
  height: 520px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15), 0 2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e5e7eb;
}

.dh-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  flex-shrink: 0;
}

.dh-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}

.dh-avatar {
  font-size: 18px;
}

.dh-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse-dot 2s infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.dh-actions {
  display: flex;
  gap: 4px;
}

.dh-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;
}

.dh-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.dh-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #f9fafb;
}

.dh-welcome {
  text-align: center;
  padding: 40px 16px;
  color: #6b7280;
}

.dh-welcome-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.dh-welcome p {
  margin: 4px 0;
  font-size: 14px;
}

.dh-welcome-hint {
  font-size: 12px !important;
  color: #9ca3af !important;
}

.dh-message {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.dh-msg-user {
  flex-direction: row-reverse;
}

.dh-msg-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
  background: #f3f4f6;
}

.dh-msg-bubble {
  max-width: 75%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.dh-msg-bubble.user {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border-top-right-radius: 4px;
}

.dh-msg-bubble.ai {
  background: white;
  color: #374151;
  border: 1px solid #e5e7eb;
  border-top-left-radius: 4px;
}

.dh-msg-bubble.typing {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  align-items: center;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #9ca3af;
  animation: typing-bounce 1.4s infinite ease-in-out;
}

.dot:nth-child(1) { animation-delay: 0s; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.dh-input-area {
  display: flex;
  gap: 8px;
  padding: 12px;
  background: white;
  border-top: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.dh-input {
  flex: 1;
  padding: 8px 14px;
  border: 1px solid #d1d5db;
  border-radius: 20px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease;
}

.dh-input:focus {
  border-color: #6366f1;
}

.dh-input:disabled {
  background: #f9fafb;
}

.dh-send-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.dh-send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.dh-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dh-fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
  transition: all 0.3s ease;
  position: relative;
}

.dh-fab:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 24px rgba(99, 102, 241, 0.5);
}

.fab-icon {
  font-size: 24px;
}

.fab-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ef4444;
  color: white;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid white;
}

.slide-fade-enter-active {
  transition: all 0.3s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.2s ease-in;
}

.slide-fade-enter-from {
  transform: translateY(20px);
  opacity: 0;
}

.slide-fade-leave-to {
  transform: translateY(20px);
  opacity: 0;
}

.bounce-enter-active {
  animation: bounce-in 0.4s ease;
}

.bounce-leave-active {
  animation: bounce-in 0.2s ease reverse;
}

@keyframes bounce-in {
  0% { transform: scale(0); }
  50% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

@media (max-width: 768px) {
  .dh-panel {
    width: calc(100vw - 20px);
    height: 60vh;
    right: 0;
    bottom: 0;
    border-radius: 16px 16px 0 0;
  }

  .digital-human-wrapper {
    right: 10px;
    bottom: 10px;
  }
}
</style>
