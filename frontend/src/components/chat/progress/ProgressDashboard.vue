<template>
  <div class="progress-dashboard">
    <div class="progress-header">
      <h3 class="section-title"><BarChart3 :size="18" /> 学习进度</h3>
      <div class="completion-badge" :class="completionClass">
        {{ Math.round(completionRate * 100) }}%
      </div>
    </div>

    <div class="progress-overview">
      <div class="progress-bar-container">
        <div class="progress-bar" :style="{ width: completionRate * 100 + '%' }"></div>
      </div>
      <div class="progress-stats">
        <div class="stat-item">
          <span class="stat-label">已完成节点</span>
          <span class="stat-value">{{ completedNodes }} / {{ totalNodes }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">学习时长</span>
          <span class="stat-value">{{ formatDuration(totalLearningTime) }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">学习次数</span>
          <span class="stat-value">{{ sessionCount }} 次</span>
        </div>
      </div>
    </div>

    <div class="nodes-progress" v-if="nodesProgress.length > 0">
      <h4 class="section-title"><BookOpen :size="18" /> 知识点掌握情况</h4>
      <div class="node-list">
        <div
          v-for="node in nodesProgress"
          :key="node.id"
          class="node-item"
          :class="{
            completed: node.isCompleted,
            current: node.id === currentNodeId,
            'key-point': node.isKeyPoint
          }"
          @click="$emit('node-click', node.id)"
        >
          <div class="node-header">
            <span class="node-index">{{ node.index + 1 }}</span>
            <span class="node-title">{{ node.title }}</span>
            <span v-if="node.isKeyPoint" class="key-point-badge">⭐</span>
          </div>
          
          <div class="node-status">
            <span v-if="node.isCompleted" class="status completed"><CheckCircle :size="14" /> 已完成</span>
            <span v-else class="status pending">○ 未完成</span>
            
            <div v-if="node.understandingLevel" class="understanding-indicator">
              <div
                class="understanding-bar"
                :class="node.understandingLevel"
                :style="{ width: (node.understandingScore || 0) * 100 + '%' }"
              ></div>
            </div>
          </div>

          <div v-if="node.questionCount > 0" class="node-meta">
            <span class="question-count"><MessageCircle :size="14" /> {{ node.questionCount }} 次提问</span>
          </div>
        </div>
      </div>
    </div>

    <div class="understanding-analysis" v-if="latestAnalysis">
      <h4 class="section-title"><Target :size="18" /> 最近理解度分析</h4>
      <div class="analysis-card">
        <div class="analysis-header">
          <span class="analysis-level" :class="latestAnalysis.level">
            {{ getLevelText(latestAnalysis.level) }}
          </span>
          <span class="analysis-score">{{ Math.round(latestAnalysis.score * 100) }}分</span>
        </div>
        <p class="analysis-reason">{{ latestAnalysis.reason }}</p>
        <div v-if="latestAnalysis.suggestions" class="analysis-suggestions">
          <strong class="suggestion-title"><Lightbulb :size="16" /> 学习建议：</strong>
          <p>{{ latestAnalysis.suggestions }}</p>
        </div>
      </div>
    </div>

    <div class="pace-recommendation" v-if="paceAdjustment">
      <h4 class="section-title"><Zap :size="18" /> 讲授节奏建议</h4>
      <div class="pace-card">
        <div class="pace-strategy">
          <span class="strategy-label">推荐策略：</span>
          <span class="strategy-value">{{ getStrategyText(paceAdjustment.nextNodeStrategy) }}</span>
        </div>
        <div class="pace-speed">
          <span class="speed-label">建议速度：</span>
          <span class="speed-value">{{ Math.round(paceAdjustment.speedFactor * 100) }}%</span>
        </div>
        <ul class="pace-actions">
          <li v-for="(action, index) in paceAdjustment.recommendedActions" :key="index">
            {{ action }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { BarChart3, BookOpen, CheckCircle, MessageCircle, Target, Lightbulb, Zap } from 'lucide-vue-next'
import api from '@/api/index.js'

const props = defineProps({
  courseId: {
    type: Number,
    required: true
  },
  currentNodeId: {
    type: Number,
    default: null
  }
})

const emit = defineEmits(['node-click'])

const progressData = ref(null)
const completionRate = ref(0)
const completedNodes = ref(0)
const totalNodes = ref(0)
const totalLearningTime = ref(0)
const sessionCount = ref(0)
const nodesProgress = ref([])
const latestAnalysis = ref(null)
const paceAdjustment = ref(null)

const completionClass = computed(() => {
  if (completionRate.value >= 1.0) return 'complete'
  if (completionRate.value >= 0.5) return 'halfway'
  return 'started'
})

const loadProgressData = async () => {
  try {
    const res = await api.progress.getVisualization(props.courseId)
    if (res) {
      progressData.value = res
      
      if (res.overallProgress) {
        completionRate.value = res.overallProgress.completionRate || 0
        totalLearningTime.value = res.overallProgress.totalLearningTime || 0
        sessionCount.value = res.overallProgress.sessionCount || 0
      }
      
      if (res.nodesProgress) {
        nodesProgress.value = res.nodesProgress
        totalNodes.value = res.nodesProgress.length
        completedNodes.value = res.nodesProgress.filter(n => n.isCompleted).length
      }
      
      if (res.recentAnalyses && res.recentAnalyses.length > 0) {
        latestAnalysis.value = res.recentAnalyses[0]
      }
    }
  } catch (err) {
    console.error('加载进度数据失败:', err)
  }
}

const formatDuration = (seconds) => {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours}小时${minutes}分钟`
}

const getLevelText = (level) => {
  const levelMap = {
    'excellent': '优秀',
    'high': '良好',
    'medium': '中等',
    'low': '需加强'
  }
  return levelMap[level] || '未知'
}

const getStrategyText = (strategy) => {
  const strategyMap = {
    'continue': '继续学习',
    'review': '回顾复习',
    'skip': '跳过基础',
    'deepen': '深入理解'
  }
  return strategyMap[strategy] || '继续学习'
}

const updatePaceAdjustment = (adjustment) => {
  paceAdjustment.value = adjustment
}

watch(() => props.courseId, () => {
  loadProgressData()
}, { immediate: true })

onMounted(() => {
  loadProgressData()
})

defineExpose({
  loadProgressData,
  updatePaceAdjustment
})
</script>

<style scoped>
.progress-dashboard {
  background: var(--color-surface);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.progress-header h3 {
  margin: 0;
  font-size: 20px;
  color: var(--color-text);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.completion-badge {
  padding: 6px 16px;
  border-radius: 20px;
  font-weight: 600;
  font-size: 14px;
}

.completion-badge.started {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
}

.completion-badge.halfway {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.completion-badge.complete {
  background: var(--color-success-light);
  color: var(--color-success-hover);
}

.progress-overview {
  margin-bottom: 24px;
}

.progress-bar-container {
  width: 100%;
  height: 12px;
  background: var(--color-border);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-bar {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: 6px;
  transition: width 0.3s ease;
}

.progress-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
}

.nodes-progress {
  margin-bottom: 24px;
}

.nodes-progress h4 {
  margin: 0 0 12px 0;
  font-size: 16px;
  color: var(--color-text-secondary);
}

.node-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.node-item {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.node-item:hover {
  border-color: var(--color-primary);
  background: var(--color-surface-2);
}

.node-item.current {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.node-item.completed {
  border-left: 3px solid var(--color-success);
}

.node-item.key-point {
  background: var(--color-warning-light);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.node-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: var(--color-border);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.node-title {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}

.key-point-badge {
  font-size: 14px;
}

.node-status {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}

.status {
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status.completed {
  color: var(--color-success-hover);
}

.status.pending {
  color: var(--color-text-muted);
}

.understanding-indicator {
  flex: 1;
  height: 6px;
  background: var(--color-border);
  border-radius: 3px;
  overflow: hidden;
}

.understanding-bar {
  height: 100%;
  border-radius: 3px;
}

.understanding-bar.excellent {
  background: var(--color-success);
}

.understanding-bar.high {
  background: var(--color-primary);
}

.understanding-bar.medium {
  background: var(--color-warning);
}

.understanding-bar.low {
  background: var(--color-danger);
}

.node-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.question-count {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.understanding-analysis,
.pace-recommendation {
  margin-bottom: 24px;
}

.understanding-analysis h4,
.pace-recommendation h4 {
  margin: 0 0 12px 0;
  font-size: 16px;
  color: var(--color-text-secondary);
}

.analysis-card,
.pace-card {
  padding: 16px;
  background: var(--color-surface-2);
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.analysis-level {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.analysis-level.excellent {
  background: var(--color-success-light);
  color: var(--color-success-hover);
}

.analysis-level.high {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.analysis-level.medium {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
}

.analysis-level.low {
  background: var(--color-danger-light);
  color: var(--color-danger-hover);
}

.analysis-score {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text);
}

.analysis-reason {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.analysis-suggestions {
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}

.analysis-suggestions strong {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}

.suggestion-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.analysis-suggestions p {
  margin: 0;
  font-size: 14px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.pace-strategy,
.pace-speed {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.strategy-label,
.speed-label {
  font-size: 14px;
  color: var(--color-text-muted);
}

.strategy-value,
.speed-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.pace-actions {
  margin: 0;
  padding-left: 20px;
}

.pace-actions li {
  margin-bottom: 4px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

@media (max-width: 768px) {
  .progress-stats {
    grid-template-columns: 1fr;
  }
  
  .node-list {
    max-height: 200px;
  }
}
</style>
