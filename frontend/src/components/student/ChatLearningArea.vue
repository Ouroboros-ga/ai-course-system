<template>
  <div class="chat-learning-area">
    <div class="message-list" ref="messageListRef">
      <div class="message-row ai-message">
        <AgentAvatar />
        <div class="bubble ai-bubble">
          <div class="welcome-content">
            <h4><GraduationCap :size="18" /> 欢迎来到《{{ selectedCourse.title }}》</h4>
            <p>我将按照文档结构为您讲解课程内容，每讲完一个小节会进行互动问答来检验您的理解程度。</p>
            <button
              v-if="!isStreaming && currentNodeIndex === 0"
              class="start-learning-btn"
              @click="startLearning"
            >
              <Rocket :size="16" /> 开始学习
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
        <Hourglass :size="14" /> 请等待当前内容讲解完成...
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
import { GraduationCap, Rocket, Hourglass } from 'lucide-vue-next'

const {
  chatMessages,
  isStreaming,
  streamingContent,
  canInput,
  selectedCourse,
  currentNodeIndex,
  scriptNodes,
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
  const currentNode = scriptNodes.value[currentNodeIndex.value]
  const result = await prerequisiteJump.actions.executeJumpToPrerequisite({
    courseId: selectedCourse.value.id,
    fromNodeId: currentNode?.id || currentNodeIndex.value,
    fromNodeTitle: currentNode?.title || '',
    fromNodeIndex: currentNode?.node_index || currentNodeIndex.value,
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
  background: var(--color-surface-2);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.message-row {
  display: flex;
  gap: var(--space-3);
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.user-message { flex-direction: row-reverse; }

.bubble {
  max-width: 85%;
  padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-lg);
  line-height: var(--leading-relaxed);
}

.ai-bubble {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-top-left-radius: var(--space-1);
  box-shadow: var(--shadow-sm);
}

.welcome-content h4 {
  margin: 0 0 var(--space-2) 0;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.welcome-content p {
  margin: 0 0 var(--space-3) 0;
  color: var(--color-text-secondary);
  font-size: var(--text-base);
}

.start-learning-btn {
  padding: var(--space-3) var(--space-5);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.start-learning-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.streaming .ai-bubble {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}

.typing-indicator {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-2) 0 0 0;
  justify-content: flex-start;
}

.typing-indicator span {
  width: var(--space-2);
  height: var(--space-2);
  background: var(--color-primary);
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
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
}

.input-wrapper {
  display: flex;
  gap: var(--space-2);
  max-width: 900px;
  margin: 0 auto;
}

.chat-input {
  flex: 1;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius-2xl);
  font-size: var(--text-base);
  outline: none;
  transition: var(--transition-all);
}

.chat-input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.chat-input:disabled {
  background: var(--color-surface-2);
  cursor: not-allowed;
}

.send-btn {
  padding: var(--space-3) var(--space-5);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-2xl);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-all);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: var(--space-2);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
}

@media (max-width: 1024px) {
  .chat-learning-area {
    flex: 1;
  }
}
</style>
