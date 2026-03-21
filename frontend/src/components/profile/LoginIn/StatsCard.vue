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
  background: #ffffff;
  border-radius: 20px;
  padding: 28px 30px; /* 整体内边距缩小，更紧凑 */
  display: flex;
  align-items: center;
  justify-content: space-around;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.stats-item {
  text-align: center;
}
.stats-number {
  /* 原 52px → 改为 36px，数字字体缩小 */
  font-size: 36px;
  font-weight: 800;
  color: #667eea;
  line-height: 1.1;
}
.stats-label {
  /* 原 16px → 改为 14px，文字字体缩小 */
  font-size: 14px;
  color: #666;
  margin-top: 6px; /* 文字和数字间距略缩小 */
  font-weight: 500;
}

/* 移动端适配也同步缩小 */
@media (max-width: 768px) {
  .stats-card { padding: 20px 20px; }
  .stats-number { font-size: 28px; }
  .stats-label { font-size: 12px; }
}
</style>
