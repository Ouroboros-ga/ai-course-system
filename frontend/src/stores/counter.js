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
    platform_permissions: [],
  })

  const token = ref(localStorage.getItem('token') || null)

  const isLoggedIn = computed(() => {
    return !!token.value && !!userData.value.id
  })

  const platformPermissions = computed(() => userData.value.platform_permissions || [])
  const hasPlatformPermission = (permission) =>
    platformPermissions.value.includes(permission) || platformPermissions.value.includes('platform.admin')
  const canManageUsers = computed(() => hasPlatformPermission('platform.admin') || hasPlatformPermission('platform.user.manage'))
  // 目标模型：任何登录用户都可以创建课程；课程内教学身份由 Course Access 决定。
  const canCreateCourses = computed(() => isLoggedIn.value)
  const isTeacher = computed(() => false)
  const isStudent = computed(() => false)
  const isAdmin = computed(() => canManageUsers.value)

  function setAuth(authData) {
    token.value = authData.token
    userData.value = {
      username: authData.username || authData.userInfo?.username || null,
      id: authData.id || authData.userInfo?.id || null,
      role: authData.role || authData.userInfo?.role || null,
      platform_permissions: authData.platform_permissions || authData.userInfo?.platform_permissions || [],
    }
    if (authData.token) {
      localStorage.setItem('token', authData.token)
    }
    if (authData.role) {
      localStorage.setItem('userRole', authData.role)
    }
    localStorage.setItem('platformPermissions', JSON.stringify(userData.value.platform_permissions))
    if (userData.value.id) {
      localStorage.setItem('userId', userData.value.id)
    }
    if (userData.value.username) {
      localStorage.setItem('username', userData.value.username)
    }
  }

  function clearAuth() {
    token.value = null
    userData.value = {
      username: null,
      id: null,
      role: null,
      platform_permissions: [],
    }
    localStorage.removeItem('token')
    localStorage.removeItem('userRole')
    localStorage.removeItem('platformPermissions')
    localStorage.removeItem('userId')
    localStorage.removeItem('username')
  }

  function checkAuth() {
    const savedToken = localStorage.getItem('token')
    const savedRole = localStorage.getItem('userRole')
    const savedUserId = localStorage.getItem('userId')
    const savedUsername = localStorage.getItem('username')
    const savedPlatformPermissions = localStorage.getItem('platformPermissions')

    if (savedToken) {
      token.value = savedToken
    }
    if (savedRole) {
      userData.value.role = savedRole
    }
    if (savedUserId) {
      userData.value.id = savedUserId
    }
    if (savedUsername) {
      userData.value.username = savedUsername
    }
    if (savedPlatformPermissions) {
      try { userData.value.platform_permissions = JSON.parse(savedPlatformPermissions) || [] } catch { userData.value.platform_permissions = [] }
    }
    return !!savedToken
  }

  function setPlatformPermissions(permissions) {
    userData.value.platform_permissions = Array.isArray(permissions) ? permissions : []
    localStorage.setItem('platformPermissions', JSON.stringify(userData.value.platform_permissions))
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
    isAdmin,
    platformPermissions,
    hasPlatformPermission,
    canManageUsers,
    canCreateCourses,
    setPlatformPermissions,
    setAuth,
    clearAuth,
    checkAuth,
  }
})
