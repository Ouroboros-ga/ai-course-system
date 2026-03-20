<template>
  <div class="message-list">
    <div v-if="!hasFile" class="welcome-message">
      <div class="avatar avatar-ai">AI</div>
      <div class="bubble-container">
        <div class="message-bubble bubble-ai">
          <p>👋 你好！我是你的 AI 助教。</p>
          <p>请在左侧上传课程 PPT 或 PDF，我将为你生成互动智课。</p>
        </div>
      </div>
    </div>

    <template v-else>
      <div class="time-stamp">14:30</div>
      <div v-for="(msg, index) in messages" :key="index"
           :class="['message-row', msg.role === 'user' ? 'row-user' : '']">
        <div class="avatar" :class="msg.role === 'ai' ? 'avatar-ai' : 'avatar-user'">
          <img v-if="msg.role === 'user'" src="https://api.dicebear.com/7.x/avataaars/svg?seed=Felix" alt="User">
          <span v-else>AI</span>
        </div>
        <div class="bubble-container">
          <MessageBubble v-bind="msg" />
        </div>
      </div>
    </template>
  </div>
</template>
<script setup>
import MessageBubble from './MessageBubble.vue';
import { reactive } from 'vue';
defineProps(['hasFile']);

const messages = reactive([
  { role: 'ai', content: '同学们好，我们现在讲到<strong>"Cache 映射方式”</strong>...', tags: ['知识点：直接映射'] },
  { role: 'user', content: '等一下，这里如果发生冲突了怎么办？' },
  { role: 'ai', content: '好问题！...', showResumeBtn: true }
]);
</script>
<style scoped>
.message-list { flex: 1; overflow-y: auto; padding: 16px; background: #fafafa; display: flex; flex-direction: column; gap: 16px; }
.time-stamp { text-align: center; font-size: 12px; color: #9ca3af; margin: 4px 0; }
.message-row { display: flex; gap: 12px; }
.row-user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; }
.avatar-ai { background: #dbeafe; color: #2563eb; }
.avatar-user { background: #e5e7eb; }
.avatar-user img { width: 100%; height: 100%; }
.bubble-container { display: flex; flex-direction: column; gap: 4px; max-width: 85%; }
.row-user .bubble-container { align-items: flex-end; }
.welcome-message { display: flex; gap: 12px; padding: 20px; background: #f0f9ff; border-radius: 12px; margin-top: 20px; }
.welcome-message .avatar { width: 40px; height: 40px; font-size: 16px; }
.welcome-message .message-bubble { background: white; border: none; box-shadow: none; padding: 0; }
.welcome-message p { margin: 0 0 8px 0; color: #334155; }
</style>
