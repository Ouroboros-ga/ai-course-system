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
            <Clapperboard :size="14" /> 分屏播放器
          </button>
          <button class="back-btn" @click="exitCourse"><ArrowLeft :size="14" /> 返回</button>
        </div>
      </div>

      <div class="chapter-tree">
        <div class="tree-header">
          <span class="tree-header-title"><ClipboardList :size="14" /> 课程结构</span>
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
              <CheckCircle v-if="isNodeCompleted(index)" :size="16" class="status-icon completed" />
              <Play v-else-if="currentNodeIndex === index" :size="16" class="status-icon current" />
              <Circle v-else :size="16" class="status-icon pending" />
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
import {
  Clapperboard,
  ArrowLeft,
  ClipboardList,
  CheckCircle,
  Play,
  Circle,
} from 'lucide-vue-next'

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
  border-right: 1px solid var(--color-border);
}

.video-section {
  height: 50%;
  background: var(--color-surface-2);
  overflow: hidden;
}

.structure-section {
  height: 50%;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.panel-header h3 {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.player-mode-btn {
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-success);
  border-radius: var(--radius-sm);
  background: var(--gradient-success);
  color: var(--color-text-inverse);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition-all);
  font-weight: var(--font-semibold);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.player-mode-btn:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-success);
}

.back-btn {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.back-btn:hover { background: var(--color-surface-2); }

.chapter-tree {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}

.tree-header-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.node-count { color: var(--color-primary); font-weight: var(--font-normal); }

.tree-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: var(--space-7) var(--space-5);
  font-size: 13px;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.tree-node {
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  transition: var(--transition-all);
  position: relative;
}

.tree-node:hover { background: var(--color-surface-2); }

.tree-node.active {
  background: linear-gradient(135deg, var(--color-primary-light), var(--color-secondary-light));
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}

.tree-node.completed { opacity: 0.75; }

.node-status { flex-shrink: 0; display: flex; align-items: center; }

.status-icon.completed { color: var(--color-success); }
.status-icon.current { color: var(--color-primary); }
.status-icon.pending { color: var(--color-text-muted); }

.node-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.node-type-icon { font-size: 13px; flex-shrink: 0; }

.node-title {
  font-size: 13px;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node.active .node-title {
  color: var(--color-primary-hover);
  font-weight: var(--font-medium);
}

.understanding-bar {
  position: absolute;
  bottom: 0;
  left: 38px;
  right: var(--space-2);
  height: 3px;
  background: var(--color-border);
  border-radius: var(--space-1);
  overflow: hidden;
}

.understanding-fill {
  height: 100%;
  border-radius: var(--space-1);
  transition: width var(--duration-slow) var(--ease);
}

.understanding-fill.level-excellent { background: var(--color-success); }
.understanding-fill.level-high { background: var(--color-primary); }
.understanding-fill.level-medium { background: var(--color-warning); }
.understanding-fill.level-low { background: var(--color-danger); }

.overall-progress {
  padding: var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
}

.progress-label {
  font-size: 13px;
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.progress-bar {
  height: var(--space-2);
  background: var(--color-border);
  border-radius: var(--space-1);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.progress-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--space-1);
  transition: width var(--duration-slow) var(--ease);
}

.progress-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
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
