<template>
  <div class="input-area" :style="{ opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? 'none' : 'auto' }">
    <div class="quick-tips">
      <button
        v-for="tip in tips"
        :key="tip"
        class="tip-chip"
        @click="handleTipClick(tip)"
      >
        {{ tip }}
      </button>
    </div>
    <div class="input-box-wrapper">
      <input
        type="text"
        v-model="text"
        @keyup.enter="handleSend"
        @input="handleInput"
        placeholder="输入问题..."
      >
      <button
        v-if="text.trim()"
        class="btn-send"
        @click="handleSend"
      >
        ↑
      </button>
      <button
        v-else
        class="btn-mic"
        @click="handleMic"
      >
        🎤
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
const props = defineProps(['disabled', 'tips']);
const emit = defineEmits(['send']);

const text = ref('');

const handleInput = () => {};

const handleSend = () => {
  if (!text.value.trim()) return;
  emit('send', text.value);
  text.value = '';
};

const handleTipClick = (tip) => {
  emit('send', tip);
};

const handleMic = () => {
  alert('语音功能开发中~');
};
</script>

<style scoped>
.input-area {
  padding: 16px;
  background: white;
  border-top: 1px solid #f3f4f6;
  transition: opacity 0.3s;
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
.btn-send {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: #2563eb;
  color: white;
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
