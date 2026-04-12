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
    role: null,
  })

  const token = ref(localStorage.getItem('token') || null)

  const isLoggedIn = computed(() => {
    return !!token.value && !!userData.value.id
  })

  const isTeacher = computed(() => {
    return userData.value.role === 'teacher'
  })

  const isStudent = computed(() => {
    return userData.value.role === 'student'
  })

  function setAuth(authData) {
    token.value = authData.token
    userData.value = {
      username: authData.username || authData.userInfo?.username || null,
      id: authData.id || authData.userInfo?.id || null,
      role: authData.role || null,
    }
    if (authData.token) {
      localStorage.setItem('token', authData.token)
    }
    if (authData.role) {
      localStorage.setItem('userRole', authData.role)
    }
  }

  function clearAuth() {
    token.value = null
    userData.value = {
      username: null,
      id: null,
      role: null,
    }
    localStorage.removeItem('token')
    localStorage.removeItem('userRole')
  }

  function checkAuth() {
    const savedToken = localStorage.getItem('token')
    const savedRole = localStorage.getItem('userRole')
    if (savedToken) {
      token.value = savedToken
    }
    if (savedRole) {
      userData.value.role = savedRole
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
    isTeacher,
    isStudent,
    setAuth,
    clearAuth,
    checkAuth,
  }
})
