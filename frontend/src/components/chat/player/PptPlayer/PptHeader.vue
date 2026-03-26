<template>
  <div class="ppt-header">
    <div class="header-info">
      <h2 v-if="file">{{ file.name }}</h2>
      <h2 v-else>未选择课程文件</h2>
      <p v-if="file">当前进度：{{ currentPage }} / {{ totalPages }} 页</p>
      <p v-else>请上传 PPT 或 PDF 开始生成智课</p>
    </div>

    <!-- 知识图谱按钮（美化版 + 点击打开弹窗） -->
    <button
      v-if="file"
      class="btn-knowledge"
      @click="openModal"
    >
      🗺️ 知识图谱
    </button>

    <!-- 知识图谱弹窗组件 -->
    <KnowledgeGraphModal
      v-model:show="showModal"
      :fileName="file?.name"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import KnowledgeGraphModal from './KnowledgeGraphModal.vue'

defineProps(['file', 'totalPages', 'currentPage'])

const showModal = ref(false)

const openModal = () => {
  showModal.value = true
}
</script>

<style scoped>
.ppt-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px;
}

.header-info h2 {
  font-size: 18px;
  color: #1f2937;
  margin: 0 0 4px 0;
}

.header-info p {
  font-size: 12px;
  color: #6b7280;
  margin: 0;
}

/* 知识图谱按钮（更美观） */
.btn-knowledge {
  background: linear-gradient(90deg, #4f46e5, #7c3aed);
  color: #fff;
  border: none;
  padding: 7px 14px;
  border-radius: 99px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}
.btn-knowledge:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
.btn-knowledge:active {
  transform: translateY(0);
}
</style>
