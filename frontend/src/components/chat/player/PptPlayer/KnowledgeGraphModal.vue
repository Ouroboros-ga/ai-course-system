<template>
  <div
    v-if="show"
    class="modal-overlay"
    @click.self="close"
  >
    <div class="modal-container">
      <div class="modal-header">
        <h3 class="modal-title"><Brain :size="18" /> 知识图谱</h3>
        <button class="close-btn" @click="close"><X :size="18" /></button>
      </div>

      <div class="modal-body">
        <div class="tip" v-if="fileName">
          当前文件：{{ fileName }}
        </div>

        <!-- 图谱展示区域 -->
        <div class="graph-box">
          <!-- 使用 MindMap 组件并传入 JSON 数据 -->
          <MindMap :data="mindMapData" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Brain, X } from 'lucide-vue-next'
// 引入新创建的思维导图组件
import MindMap from './mindMap/MindMap.vue'

const props = defineProps({
  mindMapData: Object,
  show: Boolean,
  fileName: String
})

const emit = defineEmits(['update:show'])

const close = () => {
  emit('update:show', false)
}

</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal-container {
  width: 90%;
  max-width: 800px; /* 稍微加宽以容纳树状图 */
  max-height: 80vh; /* 限制最大高度 */
  background: var(--color-surface);
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-text);
}

.modal-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-body {
  padding: 24px;
  overflow-y: auto; /* 内容过长时允许滚动 */
}

.tip {
  text-align: center;
  font-size: 13px;
  color: var(--color-primary);
  margin-bottom: 16px;
}

.graph-box {
  height: 500px; /* 调整为足够的高度 */
  background: var(--color-surface);
  border-radius: 14px;
  border: 1px solid var(--color-border);
  overflow: hidden; /* 必须hidden配合内部absolute */
  position: relative;
}
</style>
