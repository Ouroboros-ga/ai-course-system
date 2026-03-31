<template>
  <div class="message-bubble" :class="role === 'user' ? 'bubble-user' : 'bubble-ai'">
    <div v-html="content"></div>
    <div v-if="showResumeBtn" class="resume-action">
      <button class="btn-resume"> 回到刚才的讲解进度</button>
    </div>
  </div>
  <div v-if="tags" class="tags-row">
    <span v-for="tag in tags" :key="tag" class="tag-item">{{ tag }}</span>
  </div>
</template>
<script setup>
defineProps(['role', 'content', 'tags', 'showResumeBtn']);
</script>
<style scoped>
.message-bubble { padding: 12px; border-radius: 16px; font-size: 14px; line-height: 1.5; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05); border: 1px solid transparent; }
.bubble-ai { background: white; color: #374151; border-top-left-radius: 4px; border-color: #f3f4f6; }
.bubble-user { background: #2563eb; color: white; border-top-right-radius: 4px; }
.resume-action { margin-top: 12px; padding-top: 12px; border-top: 1px solid #eff6ff; }
.btn-resume { width: 100%; background: #eff6ff; color: #2563eb; border: none; padding: 8px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; }
.tags-row { display: flex; gap: 6px; margin-top: 4px; }
.tag-item { font-size: 10px; background: #eff6ff; color: #2563eb; padding: 2px 6px; border-radius: 4px; border: 1px solid #dbeafe; }
</style>
