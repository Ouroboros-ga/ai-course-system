<template>
  <div class="ppt-header">
    <div class="header-info">
      <h2 v-if="file">{{ file.name }}</h2>
      <h2 v-else>未选择课程文件</h2>
      <p v-if="file">当前进度：{{ currentPage }} / {{ totalPages }} 页</p>
      <p v-else>请上传 PPT 或 PDF 开始生成智课</p>
    </div>
    <button v-if="file" class="btn-knowledge">📄 知识图谱</button>
  </div>
</template>

<script setup>
// 👇 新增 currentPage 属性
defineProps(['file', 'totalPages', 'currentPage']);
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

.btn-knowledge {
  background: #eff6ff;
  color: #2563eb;
  border: none;
  padding: 6px 12px;
  border-radius: 99px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
