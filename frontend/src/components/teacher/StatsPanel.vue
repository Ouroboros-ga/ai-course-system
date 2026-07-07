<template>
  <div class="stats-panel">
    <h3><BarChart3 class="panel-icon" :size="18" /> 课程统计</h3>
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
import { BarChart3 } from 'lucide-vue-next'

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
.stats-panel { background: var(--color-surface); border-radius: var(--radius-lg); padding: var(--space-5); box-shadow: var(--shadow-sm); }
.stats-panel h3 { margin: 0 0 var(--space-4); font-size: var(--text-base); color: var(--color-text); display: flex; align-items: center; gap: var(--space-2); }
.panel-icon { color: var(--color-primary); flex-shrink: 0; }
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); margin-bottom: var(--space-5); }
.stat-card { background: var(--color-surface-2); border-radius: var(--radius-md); padding: var(--space-3); text-align: center; }
.stat-value { font-size: var(--text-2xl); font-weight: var(--font-bold); color: var(--color-primary-hover); }
.stat-label { font-size: var(--text-xs); color: var(--color-text-secondary); margin-top: var(--space-1); }
.progress-dist h4 { font-size: var(--text-sm); margin: 0 0 var(--space-2); color: var(--color-text-secondary); }
.dist-item { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); margin-bottom: var(--space-2); }
.dist-item > span:first-child { width: 50px; color: var(--color-text-secondary); }
.dist-bar { flex: 1; height: var(--space-1); background: var(--color-surface-3); border-radius: var(--radius-full); overflow: hidden; }
.dist-fill { height: 100%; background: var(--gradient-primary); border-radius: var(--radius-full); transition: width var(--duration-slow) var(--ease); }
.dist-item > span:last-child { width: 30px; text-align: right; color: var(--color-text-secondary); font-weight: var(--font-medium); }
</style>
