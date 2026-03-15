<script setup>
import { ref, nextTick } from 'vue';

const emit = defineEmits(['send', 'add']);

const message = ref('');
const isFocused = ref(false);
const isComposing = ref(false); // 输入法组合状态
const textareaRef = ref(null);

const handleFileChange = (event) => {
  const file = event.target.files[0]

  if (file) {
    console.log('选择的文件:', file.name)

    // 这里可以把文件传给父组件
    emit('add', file)

    // 或者直接在这里处理上传逻辑
    // ...
  }

  // 清空 value，允许重复选择相同文件
  event.target.value = ''
}

// 自动调整 textarea 高度
const autoResize = () => {
  const textarea = textareaRef.value;
  if (!textarea) return;

  textarea.style.height = 'auto'; // 先重置高度
  const lineHeight = 24; // 单行高度
  const maxHeight = lineHeight * 3; // 最大3行

  const newHeight = Math.min(textarea.scrollHeight, maxHeight);
  textarea.style.height = newHeight + 'px';
};

// 发送消息
const handleSend = () => {
  const text = message.value.trim();
  if (!text || isComposing.value) return; // 组合中不发送

  emit('send', text);
  message.value = '';
  nextTick(() => autoResize()); // 清空后重置高度
};

// 键盘事件（改为 keydown 及时阻止默认行为）
const handleKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();          // 阻止换行/提交
    if (!isComposing.value) {    // 不在输入法组合中才触发发送
      handleSend();
    }
  }
};

// 组合事件：开始组合时标记
const handleCompositionStart = () => {
  isComposing.value = true;
};

// 组合事件：结束组合时取消标记
const handleCompositionEnd = () => {
  isComposing.value = false;
};
</script>

<template>
  <div class="input-container">
    <!-- 装饰光晕 -->
    <div class="glow-effect"></div>

    <div class="input-wrapper" :class="{ 'focused': isFocused }">

      <!-- 添加附件按钮 -->
      <label
        class="action-btn add-btn"
        aria-label="添加附件"
      >
        <input
          type="file"
          style="display: none"
          @change="handleFileChange"
          accept=".xlsx,.xls,.doc,.docx,.jpg,.png"
        />
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
      </label>

      <!-- 输入框区域 -->
      <div class="input-area">
        <textarea
          ref="textareaRef"
          class="input-text"
          v-model="message"
          placeholder="输入消息..."
          rows="1"
          @focus="isFocused = true"
          @blur="isFocused = false"
          @keydown="handleKeydown"
          @input="autoResize"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
          aria-label="消息输入框"
        ></textarea>
      </div>

      <!-- 发送按钮 -->
      <button
        class="action-btn send-btn"
        type="button"
        :class="{ 'active': message.trim().length > 0 && !isComposing }"
        :disabled="message.trim().length === 0 || isComposing"
        @click="handleSend"
        aria-label="发送消息"
      >
        <svg viewBox="0 0 24 24"
             fill="none"
             stroke="currentColor"
             stroke-width="2"
             stroke-linecap="round"
             stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>

    </div>
  </div>
</template>

<style scoped>

.input-text {
  width: 100%;
  border: none;
  outline: none;
  font-size: 16px;
  color: #333;
  padding: 0;
  font-family: inherit;
  -webkit-appearance: none;
  appearance: none;
  resize: none;
  line-height: 1.5;
  height: 24px;
  min-height: 24px;
  max-height: 72px; /* 3行高度 */
  overflow-y: auto;
  word-wrap: break-word;
  word-break: break-all;

  background: rgba(0, 0, 0, 0);
}

/* 自定义滚动条样式 */
.input-text::-webkit-scrollbar {
  width: 4px;
}

.input-text::-webkit-scrollbar-track {
  background: transparent;
}

.input-text::-webkit-scrollbar-thumb {
  background: #ddd;
  border-radius: 2px;
}

.input-text::-webkit-scrollbar-thumb:hover {
  background: #ccc;
}

/* ========== 容器样式 ========== */
.input-container {
  position: relative;      /* 为光晕提供定位参考 */
  width: 100%;
  display: flex;
  justify-content: center;
  z-index: 1000;
  opacity: 1;
  transform: translateY(0);
  pointer-events: none;    /* 允许内部元素接收事件 */
}

.input-container * {
  pointer-events: auto;
}

/* ========== 主包裹层 ========== */
.input-wrapper {
  display: flex;
  align-items: flex-end;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  padding: 8px 12px;
  border-radius: 30px;
  box-shadow:
    0 10px 30px -10px rgba(0, 0, 0, 0.1),
    0 0 0 1px rgba(0, 0, 0, 0.05);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  max-width: 600px;
  width: 90%;
  margin: 16px auto;
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
  display: flex;
  align-items: center;
  padding: 8px 0;

  //background: blue;
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
  left: 50%;
  transform: translateX(-50%);
  width: 60%;
  height: 20px;
  background: radial-gradient(ellipse at center, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0) 70%);
  filter: blur(10px);
  z-index: -1;
  pointer-events: none;
}

/* ========== 移动端适配 ========== */
@media (max-width: 768px) {
  .input-wrapper {
    width: 100%;
    max-width: 100%;
    padding: 6px 10px;
    margin: 12px 12px calc(12px + env(safe-area-inset-bottom));
  }

  .action-btn {
    width: 36px;
    height: 36px;
  }

  .input-area input {
    font-size: 14px;
  }

  /* 光晕适当缩小 */
  .glow-effect {
    width: 80%;
  }
}
</style>
