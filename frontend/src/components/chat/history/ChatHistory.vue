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
import { ref, onMounted } from 'vue';
import { getChatHistory } from '@/api/chat.js'
import { useCounterStore } from '@/stores/counter.js'

const counter = useCounterStore()
const historyList = ref([])
const loading = ref(false)

const emit = defineEmits(['select'])

const loadHistory = async () => {
  if (!counter.userData.id) return
  loading.value = true
  try {
    const res = await getChatHistory({ userId: counter.userData.id })
    if (res && res.records) {
      historyList.value = res.records
    }
  } catch (e) {
    console.error('加载历史记录失败:', e)
  }
  loading.value = false
}

onMounted(() => {
  loadHistory()
})

const handleSelect = (item) => {
  emit('select', item)
};
</script>


<style scoped>
.history-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border-radius: 16px;
  padding: 18px;
  box-sizing: border-box;
}


.history-header {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-border);
}


.history-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
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
  background: var(--color-surface-2);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}


.history-item:hover {
  background: var(--color-primary-light);
}


.item-title {
  font-size: 14px;
  color: var(--color-text);
  font-weight: 500;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}


.item-time {
  font-size: 12px;
  color: var(--color-text-muted);
}


.empty {
  text-align: center;
  padding: 40px 0;
  color: var(--color-border);
  font-size: 14px;
}
</style>
