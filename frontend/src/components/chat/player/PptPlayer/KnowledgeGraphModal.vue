<template>
  <div
    v-if="show"
    class="modal-overlay"
    @click.self="close"
  >
    <div class="modal-container">
      <div class="modal-header">
        <h3>🧠 知识图谱</h3>
        <button class="close-btn" @click="close">✕</button>
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
// 引入新创建的思维导图组件
import MindMap from './mindMap/MindMap.vue'

const props = defineProps({
  show: Boolean,
  fileName: String
})

const emit = defineEmits(['update:show'])

const close = () => {
  emit('update:show', false)
}

// 定义存储思维导图数据的 JSON 变量TODO: 用状态管理变量替换
// 结构为树状：name 为节点名称，children 为子节点数组
const mindMapData = ref({
  name: '前端开发技术',
  children: [
    {
      name: 'HTML',
      children: [
        { name: '语义化标签' },
        { name: '表单验证' }
      ]
    },
    {
      name: 'CSS',
      children: [
        { name: 'Flex布局' },
        { name: 'Grid布局' },
        { name: '响应式设计' }
      ]
    },
    {
      name: 'JavaScript',
      children: [
        {
          name: 'Vue.js',
          children: [
            { name: 'Composition API' },
            { name: 'Reactivity' }
          ]
        },
        { name: 'React' },
        { name: 'TypeScript' }
      ]
    }
  ]
})
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
  background: #fff;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: #1f2937;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #6b7280;
  cursor: pointer;
}

.modal-body {
  padding: 24px;
  overflow-y: auto; /* 内容过长时允许滚动 */
}

.tip {
  text-align: center;
  font-size: 13px;
  color: #4f46e5;
  margin-bottom: 16px;
}

.graph-box {
  height: 500px; /* 调整为足够的高度 */
  background: #ffffff;
  border-radius: 14px;
  border: 1px solid #e5e7eb;
  overflow: hidden; /* 必须hidden配合内部absolute */
  position: relative;
}
</style>
