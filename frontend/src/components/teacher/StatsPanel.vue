<template>
  <div class="stats-panel">
    <h3>📊 课程统计</h3>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">{{ stats.totalStudents || 0 }}</div><div class="stat-label">学生数</div></div>
      <div class="stat-card"><div class="stat-value">{{ stats.totalNodes || 0 }}</div><div class="stat-label">知识点</div></div>
      <div class="stat-card"><div class="stat-value">{{ formatDuration(stats.totalDuration) }}</div><div class="stat-label">总时长</div></div>
      <div class="stat-card"><div class="stat-value">{{ stats.avgProgress || 0 }}%</div><div class="stat-label">平均进度</div></div>
    </div>

    <div v-if="stats.progressDistribution" class="progress-dist">
      <h4>进度分布</h4>
      <div v-for="(item, key) in stats.progressDistribution" :key="key" class="dist-item">
        <span>{{ getDistLabel(key) }}</span>
        <div class="dist-bar"><div class="dist-fill" :style="{ width: item + '%' }"></div></div>
        <span>{{ item }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ stats: { type: Object, default: () => ({}) } })

function formatDuration(seconds) {
  if (!seconds) return '0分'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}时${m}分`
  return `${m}分`
}

function getDistLabel(key) {
  const labels = { not_started: '未开始', in_progress: '学习中', completed: '已完成' }
  return labels[key] || key
}
</script>

<style scoped>
.stats-panel { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.stats-panel h3 { margin: 0 0 16px; font-size: 16px; color: #333; }
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-card { background: #f9fafb; border-radius: 8px; padding: 12px; text-align: center; }
.stat-value { font-size: 24px; font-weight: 700; color: #4f46e5; }
.stat-label { font-size: 12px; color: #6b7280; margin-top: 4px; }
.progress-dist h4 { font-size: 14px; margin: 0 0 10px; color: #374151; }
.dist-item { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 6px; }
.dist-item > span:first-child { width: 50px; color: #6b7280; }
.dist-bar { flex: 1; height: 6px; background: #e5e7eb; border-radius: 99px; overflow: hidden; }
.dist-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 99px; transition: width 0.3s; }
.dist-item > span:last-child { width: 30px; text-align: right; color: #374151; font-weight: 500; }
</style>
