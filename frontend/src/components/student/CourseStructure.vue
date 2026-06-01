<template>
  <div class="left-column">
    <div class="video-section">
      <PptSlidePlayer
        ref="pptSlidePlayerRef"
        :slides="courseSlides"
        :totalPages="courseSlidesTotal"
        :currentPage="currentSlidePage"
        :audioUrl="currentNodeAudioUrl"
        :audioDuration="currentNodeAudioDuration"
        :autoPlay="true"
        @page-change="onSlidePageChange"
        @audio-ended="onNodeAudioEnded"
        @auto-play-blocked="onAutoPlayBlocked"
      />
    </div>

    <div class="structure-section">
      <div class="panel-header">
        <h3>{{ selectedCourse.title }}</h3>
        <div class="header-actions">
          <button
            class="player-mode-btn"
            @click="enterPlayerMode"
            title="进入分屏视频播放器模式"
          >
            🎬 分屏播放器
          </button>
          <button class="back-btn" @click="exitCourse">← 返回</button>
        </div>
      </div>

      <div class="chapter-tree">
        <div class="tree-header">
          <span>📋 课程结构</span>
          <span class="node-count">{{ scriptNodes.length }} 个节点</span>
        </div>

        <div v-if="scriptNodes.length === 0" class="tree-empty">
          正在加载课程内容...
        </div>

        <div v-else class="tree-list">
          <div
            v-for="(node, index) in scriptNodes"
            :key="node.id"
            class="tree-node"
            :class="{
              active: currentNodeIndex === index,
              completed: isNodeCompleted(index),
              current: currentNodeIndex === index
            }"
            @click="jumpToNode(index)"
          >
            <div class="node-status">
              <span v-if="isNodeCompleted(index)" class="status-icon completed">✅</span>
              <span v-else-if="currentNodeIndex === index" class="status-icon current">▶️</span>
              <span v-else class="status-icon pending">⭕</span>
            </div>

            <div class="node-info">
              <span class="node-type-icon">{{ getNodeTypeIcon(node.node_type) }}</span>
              <span class="node-title">{{ node.title || `节点 ${index + 1}` }}</span>
            </div>

            <div v-if="getNodeProgress(index) && getNodeProgress(index).score !== null" class="understanding-bar">
              <div
                class="understanding-fill"
                :style="{ width: getNodeProgress(index).score + '%' }"
                :class="getUnderstandingClass(getNodeProgress(index).level)"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <div class="overall-progress">
        <div class="progress-label">总体进度</div>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: overallProgress + '%' }"
          ></div>
        </div>
        <div class="progress-text">{{ overallProgress.toFixed(0) }}% 完成</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { inject } from 'vue'
import PptSlidePlayer from '@/components/chat/PptSlidePlayer.vue'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'

const {
  selectedCourse,
  scriptNodes,
  currentNodeIndex,
  courseSlides,
  courseSlidesTotal,
  currentSlidePage,
  currentNodeAudioUrl,
  currentNodeAudioDuration,
  pendingAutoPlay,
  overallProgress,
  isNodeCompleted,
  getNodeProgress,
  getNodeTypeIcon,
  getUnderstandingClass,
  exitCourse,
  enterPlayerMode,
  jumpToNode,
  onSlidePageChange,
  onNodeAudioEnded,
  onAutoPlayBlocked,
  onAutoPlayTriggered,
} = inject(STUDENT_LEARNING_KEY)

const pptSlidePlayerRef = ref(null)

watch(pendingAutoPlay, (val) => {
  if (val) {
    nextTick(() => {
      if (pptSlidePlayerRef.value) {
        pptSlidePlayerRef.value.playAudio()
      }
      onAutoPlayTriggered()
    })
  }
})
</script>

<style scoped>
.left-column {
  width: 50%;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  flex-shrink: 1;
  border-right: 1px solid #e5e7eb;
}

.video-section {
  height: 50%;
  background: #1a1a1a;
  overflow: hidden;
}

.structure-section {
  height: 50%;
  background: white;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.player-mode-btn {
  padding: 6px 14px;
  border: 1px solid #4CAF50;
  border-radius: 6px;
  background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
  color: white;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-weight: 600;
}

.player-mode-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(76, 175, 80, 0.3);
}

.back-btn {
  padding: 6px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.back-btn:hover { background: #f3f4f6; }

.chapter-tree {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}

.node-count { color: #6366f1; font-weight: normal; }

.tree-empty {
  text-align: center;
  color: #9ca3af;
  padding: 40px 20px;
  font-size: 13px;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tree-node {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s ease;
  position: relative;
}

.tree-node:hover { background: #f3f4f6; }

.tree-node.active {
  background: linear-gradient(135deg, #eef2ff, #f5f3ff);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}

.tree-node.completed { opacity: 0.75; }

.node-status { flex-shrink: 0; }

.status-icon { font-size: 14px; }

.node-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.node-type-icon { font-size: 13px; flex-shrink: 0; }

.node-title {
  font-size: 13px;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node.active .node-title {
  color: #4f46e5;
  font-weight: 500;
}

.understanding-bar {
  position: absolute;
  bottom: 0;
  left: 38px;
  right: 8px;
  height: 3px;
  background: #e5e7eb;
  border-radius: 2px;
  overflow: hidden;
}

.understanding-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}

.understanding-fill.level-excellent { background: #10b981; }
.understanding-fill.level-high { background: #6366f1; }
.understanding-fill.level-medium { background: #f59e0b; }
.understanding-fill.level-low { background: #ef4444; }

.overall-progress {
  padding: 16px;
  border-top: 1px solid #e5e7eb;
  background: #fafbfc;
}

.progress-label {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
}

.progress-bar {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

@media (max-width: 1024px) {
  .left-column {
    width: 100%;
    height: 50vh;
  }

  .video-section {
    height: 50%;
  }

  .structure-section {
    height: 50%;
  }
}
</style>
