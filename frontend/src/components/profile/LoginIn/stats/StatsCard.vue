<template>
  <div class="stats-card">
    <div class="stats-item">
      <div class="stats-number">{{ userStats.courseCount || '-' }}</div>
      <div class="stats-label">已上传课件</div>
    </div>
    <div class="stats-item">
      <div class="stats-number">{{ userStats.chatCount || '-' }}</div>
      <div class="stats-label">AI对话次数</div>
    </div>
    <div class="stats-item">
      <div class="stats-number">{{ userStats.studyMinutes || '-' }}</div>
      <div class="stats-label">学习分钟</div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  userStats: {
    type: Object,
    default: () => ({
      courseCount: '',
      chatCount: '',
      studyMinutes: ''
    })
  }
})
</script>

<style scoped>
.stats-card {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: 28px 30px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border);
}
.stats-item {
  text-align: center;
}
.stats-number {
  font-size: 36px;
  font-weight: var(--font-bold);
  color: var(--color-primary);
  line-height: 1.1;
}
.stats-label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-1);
  font-weight: var(--font-medium);
}

/* 移动端适配也同步缩小 */
@media (max-width: 768px) {
  .stats-card { padding: var(--space-5) var(--space-5); }
  .stats-number { font-size: 28px; }
  .stats-label { font-size: var(--text-xs); }
}
</style>
