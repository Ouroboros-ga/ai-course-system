<script setup>
import { ref } from 'vue';

// 定义发射的事件
const emit = defineEmits(['send', 'add']);

// 响应式数据
const message = ref('');
const isFocused = ref(false);

// 处理发送消息
const handleSend = () => {
  const text = message.value.trim();
  if (!text) return;

  emit('send', text);  // 向父组件发射 send 事件，携带消息文本
  message.value = '';  // 发送后清空输入框
};

// 处理键盘事件（回车发送，支持 Shift+Enter 换行）
const handleKeyup = (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();  // 阻止默认换行
    handleSend();
  }
};
</script>

<template>
  <div class="input-container">
    <!-- 装饰光晕 -->
    <div class="glow-effect"></div>

    <div class="input-wrapper" :class="{ 'focused': isFocused }">

      <!-- 添加附件按钮 -->
      <button
        class="action-btn add-btn"
        type="button"
        @click="emit('add')"
        aria-label="添加附件"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
      </button>

      <!-- 输入框区域 -->
      <div class="input-area">
        <input
          v-model="message"
          type="text"
          placeholder="输入消息..."
          @focus="isFocused = true"
          @blur="isFocused = false"
          @keyup="handleKeyup"
          aria-label="消息输入框"
        />
      </div>

      <!-- 发送按钮 -->
      <button
        class="action-btn send-btn"
        type="button"
        :class="{ 'active': message.trim().length > 0 }"
        :disabled="message.trim().length === 0"
        @click="handleSend"
        aria-label="发送消息"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>

    </div>
  </div>
</template>

<style scoped>
/* ========== 容器样式 ========== */
.input-container {
  width: 100%;
  display: flex;
  justify-content: center;
  z-index: 1000;
  /* ✅ 移除动画，直接显示 */
  opacity: 1;
  transform: translateY(0);
  pointer-events: none;
}

.input-container * {
  pointer-events: auto;
}

/* ========== 主包裹层 ========== */
.input-wrapper {
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  padding: 8px 12px;
  border-radius: 50px;
  box-shadow:
    0 10px 30px -10px rgba(0, 0, 0, 0.1),
    0 0 0 1px rgba(0, 0, 0, 0.05);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  max-width: 600px;
  width: 90%;
  position: relative;
}

.input-wrapper.focused {
  box-shadow:
    0 15px 35px -10px rgba(0, 0, 0, 0.15),
    0 0 0 2px rgba(64, 158, 255, 0.2);
  transform: translateY(-2px);
  background: rgba(255, 255, 255, 0.95);
}

/* ========== 按钮通用样式 ========== */
.action-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  transition: all 0.2s ease;
  flex-shrink: 0;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}

.action-btn:active {
  transform: scale(0.9);
}

.action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ========== 加号按钮 ========== */
.add-btn {
  color: #888;
}

.add-btn:hover:not(:disabled) {
  background-color: #f0f0f0;
  color: #333;
}

/* ========== 输入区域 ========== */
.input-area {
  flex: 1;
  margin: 0 4px;
  overflow: hidden;
}

.input-area input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 16px;
  color: #333;
  padding: 8px 4px;
  font-family: inherit;
  -webkit-appearance: none;
  appearance: none;
}

.input-area input::placeholder {
  color: #aaa;
  transition: color 0.2s;
}

.input-wrapper.focused .input-area input::placeholder {
  color: #ccc;
}

/* ========== 发送按钮 ========== */
.send-btn {
  color: #ddd;
  pointer-events: none;
}

.send-btn.active {
  color: #007aff;
  pointer-events: auto;
  background-color: rgba(0, 122, 255, 0.1);
}

.send-btn.active:hover {
  background-color: rgba(0, 122, 255, 0.2);
  transform: scale(1.05);
}

.send-btn.active:active {
  transform: scale(0.9);
}

/* ========== 装饰光晕 ========== */
.glow-effect {
  position: absolute;
  bottom: -20px;
  width: 60%;
  height: 20px;
  background: radial-gradient(ellipse at center, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0) 70%);
  filter: blur(10px);
  z-index: -1;
  pointer-events: none;
}

/* ========== 移动端适配 ========== */
@media (max-width: 768px) {
  .input-container {
    bottom: calc(16px + env(safe-area-inset-bottom));
    padding: 0 12px;
  }

  .input-wrapper {
    width: 100%;
    max-width: 100%;
    padding: 6px 10px;
  }

  .action-btn {
    width: 36px;
    height: 36px;
  }

  .input-area input {
    font-size: 14px;
  }
}
</style>
