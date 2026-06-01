<template>
  <div class="chat-learning-area">
    <div class="message-list" ref="messageListRef">
      <div class="message-row ai-message">
        <AgentAvatar />
        <div class="bubble ai-bubble">
          <div class="welcome-content">
            <h4>🎓 欢迎来到《{{ selectedCourse.title }}》</h4>
            <p>我将按照文档结构为您讲解课程内容，每讲完一个小节会进行互动问答来检验您的理解程度。</p>
            <button
              v-if="!isStreaming && currentNodeIndex === 0"
              class="start-learning-btn"
              @click="startLearning"
            >
              🚀 开始学习
            </button>
          </div>
        </div>
      </div>

      <ChatMessage
        v-for="(msg, index) in chatMessages"
        :key="msg.id || index"
        :msg="msg"
      />

      <div v-if="isStreaming" class="message-row ai-message streaming">
        <AgentAvatar />
        <div class="bubble ai-bubble">
          <div class="streaming-content markdown-body" v-html="renderContent(streamingContent)"></div>
          <div class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <div class="input-wrapper">
        <input
          type="text"
          v-model="userInput"
          placeholder="输入您的问题或回答..."
          @keyup.enter="sendMessage"
          :disabled="isStreaming || !canInput"
          class="chat-input"
        />
        <button
          class="send-btn"
          @click="sendMessage"
          :disabled="!userInput.trim() || isStreaming || !canInput"
        >
          发送
        </button>
      </div>
      <div class="input-hint" v-if="!canInput">
        ⏳ 请等待当前内容讲解完成...
      </div>
    </div>

    <PrerequisiteJumpDialog
      v-if="prerequisiteJump.state.showJumpDialog.value"
      :visible="prerequisiteJump.state.showJumpDialog.value"
      :analysisData="prerequisiteJump.state.jumpAnalysisResult.value"
      @confirm="handleConfirmJump"
      @cancel="handleCancelJump"
    />
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { inject } from 'vue'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'
import AgentAvatar from './AgentAvatar.vue'
import ChatMessage from './ChatMessage.vue'
import PrerequisiteJumpDialog from './PrerequisiteJumpDialog.vue'

const {
  chatMessages,
  isStreaming,
  streamingContent,
  canInput,
  selectedCourse,
  currentNodeIndex,
  userInput,
  scrollTrigger,
  renderContent,
  startLearning,
  sendMessage,
  prerequisiteJump,
} = inject(STUDENT_LEARNING_KEY)

const messageListRef = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

watch(scrollTrigger, () => {
  scrollToBottom()
})

async function handleConfirmJump(prereqData) {
  const result = await prerequisiteJump.actions.executeJumpToPrerequisite({
    courseId: selectedCourse.value.id,
    fromNodeId: currentNodeIndex.value?.id,
    fromNodeTitle: currentNodeIndex.value?.title,
    fromNodeIndex: currentNodeIndex.value?.node_index,
    toPrerequisiteId: prereqData.prerequisiteId,
    toNodeTitle: prereqData.title,
    toNodeIndex: prereqData.targetNodeIndex || 0,
    triggerQuestion: '',
    analysisResult: prerequisiteJump.state.jumpAnalysisResult.value,
    gapDescription: prereqData.reason || '',
    confidenceScore: prereqData.confidence || 0.8,
    urgencyLevel: prereqData.urgencyLevel || 'medium',
  })

  if (result.success) {
    console.log('[前置知识跳转] 成功跳转到', result.targetNodeId)
  }
}

function handleCancelJump() {
  prerequisiteJump.actions.dismissDialog()
}
</script>

<style scoped>
.chat-learning-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fafbfc;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-row {
  display: flex;
  gap: 12px;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.user-message { flex-direction: row-reverse; }

.bubble {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: 12px;
  line-height: 1.6;
}

.ai-bubble {
  background: white;
  border: 1px solid #e5e7eb;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.welcome-content h4 {
  margin: 0 0 8px 0;
  color: #111827;
}

.welcome-content p {
  margin: 0 0 12px 0;
  color: #6b7280;
  font-size: 14px;
}

.start-learning-btn {
  padding: 10px 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.start-learning-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.streaming .ai-bubble {
  border-color: #93c5fd;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0 0 0;
  justify-content: flex-start;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #6366f1;
  border-radius: 50%;
  animation: bounce 1.4s ease-in-out infinite;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.input-area {
  padding: 16px 20px;
  background: white;
  border-top: 1px solid #e5e7eb;
}

.input-wrapper {
  display: flex;
  gap: 8px;
  max-width: 900px;
  margin: 0 auto;
}

.chat-input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid #d1d5db;
  border-radius: 24px;
  font-size: 14px;
  outline: none;
  transition: all 0.2s ease;
}

.chat-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.chat-input:disabled {
  background: #f9fafb;
  cursor: not-allowed;
}

.send-btn {
  padding: 12px 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
}

@media (max-width: 1024px) {
  .chat-learning-area {
    flex: 1;
  }
}
</style>
