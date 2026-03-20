<template>
  <div class="input-area" :style="{ opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? 'none' : 'auto' }">
    <div class="quick-tips">
      <button v-for="tip in tips" :key="tip" class="tip-chip">{{ tip }}</button>
    </div>
    <div class="input-box-wrapper">
      <input type="text" v-model="text" @keyup.enter="$emit('send', text); text=''" placeholder="输入问题...">
      <button class="btn-mic">🎤</button>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue';
defineProps(['disabled', 'tips']);
defineEmits(['send']);
const text = ref('');
</script>
<style scoped>
.input-area { padding: 16px; background: white; border-top: 1px solid #f3f4f6; transition: opacity 0.3s; }
.quick-tips { display: flex; gap: 8px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; }
.tip-chip { white-space: nowrap; background: #f9fafb; border: 1px solid #e5e7eb; padding: 6px 12px; border-radius: 99px; font-size: 12px; color: #4b5563; cursor: pointer; transition: all 0.2s; }
.tip-chip:hover { border-color: #93c5fd; color: #2563eb; background: #eff6ff; }
.input-box-wrapper { position: relative; }
.input-box-wrapper input { width: 100%; padding: 12px 48px 12px 16px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 12px; font-size: 14px; box-sizing: border-box; outline: none; }
.input-box-wrapper input:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1); }
.btn-mic { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; font-size: 18px; color: #9ca3af; cursor: pointer; }
</style>
