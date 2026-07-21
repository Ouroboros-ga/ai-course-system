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
        <ArrowUp :size="18" />
      </button>
      <button
        v-else
        class="btn-mic"
        @click="handleMic"
      >
        <Mic :size="18" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { Mic, ArrowUp } from 'lucide-vue-next';
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
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
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
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  padding: 6px 12px;
  border-radius: 99px;
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}
.tip-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}
.input-box-wrapper {
  position: relative;
}
.input-box-wrapper input {
  width: 100%;
  padding: 12px 48px 12px 16px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  font-size: 14px;
  box-sizing: border-box;
  outline: none;
}
.input-box-wrapper input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}
.btn-mic {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-send {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: var(--color-primary);
  color: var(--color-text-inverse);
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
