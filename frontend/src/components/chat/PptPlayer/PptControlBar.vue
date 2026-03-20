<template>
  <div class="ai-control-bar">
    <div class="control-left">
      <button class="btn-play" @click="$emit('toggle')">
        <span v-if="isPlaying">⏸</span>
        <span v-else>▶</span>
      </button>
      <div class="progress-info">
        <span class="status-text">{{ isPlaying ? 'AI 讲师正在讲解...' : '已暂停' }}</span>
        <div class="progress-track"><div class="progress-fill" style="width: 45%"></div></div>
      </div>
    </div>
    <div class="control-right">
      <button>↺</button>
      <span class="speed-tag">1.0x</span>
      <button>🔊</button>
    </div>
  </div>
</template>
<script setup>
defineProps(['isPlaying']);
defineEmits(['toggle']);
</script>
<style scoped>
.ai-control-bar { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); width: 90%; background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(8px); border-radius: 16px; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.2); border: 1px solid rgba(255,255,255,0.5); }
.control-left { display: flex; align-items: center; gap: 16px; }
.btn-play { width: 40px; height: 40px; border-radius: 50%; background: #2563eb; color: white; border: none; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.progress-info { display: flex; flex-direction: column; gap: 4px; width: 128px; }
.status-text { font-size: 12px; color: #6b7280; font-weight: 500; }
.progress-track { height: 6px; background: #f3f4f6; border-radius: 99px; overflow: hidden; }
.progress-fill { width: 66%; height: 100%; background: #3b82f6; border-radius: 99px; }
.control-right { display: flex; gap: 16px; color: #6b7280; align-items: center; }
.control-right button { background: none; border: none; cursor: pointer; font-size: 16px; color: inherit; }
.speed-tag { font-size: 12px; font-family: monospace; background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
</style>
