<template>
  <div class="history-wrapper">
    <div class="history-header">
      <h3>历史对话</h3>
    </div>


    <div class="history-list">
      <div
        class="history-item"
        v-for="item in historyList"
        :key="item.id"
        @click="handleSelect(item)"
      >
        <div class="item-title">{{ item.title }}</div>
        <div class="item-time">{{ item.time }}</div>
      </div>


      <div class="empty" v-if="!historyList.length">
        暂无聊天记录
      </div>
    </div>
  </div>
</template>


<script setup>
import { ref } from 'vue';
const historyList = ref([
  { id: 1, title: 'Vue3 组件化开发', time: '今天 14:30' },
  { id: 2, title: 'PPT 解析与知识点总结', time: '今天 10:20' },
  { id: 3, title: '前端工程化配置', time: '昨天 16:10' },
]);


const handleSelect = (item) => {
  console.log('选中记录：', item);
};
</script>


<style scoped>
.history-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 16px;
  padding: 18px;
  box-sizing: border-box;
}


.history-header {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f3f5;
}


.history-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}


.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}


.history-item {
  padding: 12px 14px;
  background: #f9fafb;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}


.history-item:hover {
  background: #eff6ff;
}


.item-title {
  font-size: 14px;
  color: #1f2937;
  font-weight: 500;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}


.item-time {
  font-size: 12px;
  color: #9ca3af;
}


.empty {
  text-align: center;
  padding: 40px 0;
  color: #ccc;
  font-size: 14px;
}
</style>
