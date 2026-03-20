import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useCounterStore = defineStore('counter', () => {

  // messages格式：[{id: 1, class: 'user', message: 'Hello World'}]
  const messages = ref([])  // 消息列表

  function addMessage(message) {
    messages.value.push(message)
  }

  function removeMessage(id) {
    messages.value = messages.value.filter(msg => msg.id !== id)
  }

  function clearMessages() {
    messages.value = []
  }

  return {
    messages,
    addMessage,
    clearMessages,
    removeMessage,
  }
})
