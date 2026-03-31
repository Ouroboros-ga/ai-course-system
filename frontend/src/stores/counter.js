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

  const userData = ref({
    username: null,
    id: null,
  })

  const token = ref(localStorage.getItem('token') || null)

  const isLoggedIn = computed(() => {
    return !!token.value && !!userData.value.id
  })

  function setAuth(authData) {
    token.value = authData.token
    userData.value = {
      username: authData.username || authData.userInfo?.username || null,
      id: authData.id || authData.userInfo?.id || null,
    }
    if (authData.token) {
      localStorage.setItem('token', authData.token)
    }
  }

  function clearAuth() {
    token.value = null
    userData.value = {
      username: null,
      id: null,
    }
    localStorage.removeItem('token')
  }

  function checkAuth() {
    const savedToken = localStorage.getItem('token')
    if (savedToken) {
      token.value = savedToken
    }
    return !!savedToken
  }

  return {
    messages,
    addMessage,
    clearMessages,
    removeMessage,
    userData,
    token,
    isLoggedIn,
    setAuth,
    clearAuth,
    checkAuth,
  }
})
