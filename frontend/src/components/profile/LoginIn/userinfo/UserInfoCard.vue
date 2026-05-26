<template>
  <div class="user-card-container">
    <!-- 毛玻璃卡片 -->
    <div class="glass-card">

      <!-- 顶部用户信息区域 -->
      <div class="user-header">
        <div class="avatar">
          <!-- 这里可以根据用户名动态生成头像背景色或显示首字母 -->
          <span>{{ counter.userData.username ? counter.userData.username.charAt(0).toUpperCase() : 'U' }}</span>
        </div>
        <div class="user-info">
          <h3 class="username">{{ counter.userData.username || '未登录' }}</h3>
          <p class="user-id">ID: {{ counter.userData.id || '...' }}</p>
        </div>
      </div>

      <!-- 内容区域：菜单 与 表单切换 -->
      <div class="card-body">
        <TransitionGroup name="soft-transition" tag="div" class="transition-wrapper">

          <!-- 默认菜单视图 -->
          <div v-if="activePanel === 'menu'" key="menu" class="panel-content">
            <div class="menu-list">
              <div class="menu-item" @click="activePanel = 'username'">
                <div class="icon">✏️</div>
                <span>修改用户名</span>
                <div class="arrow">›</div>
              </div>
              <div class="menu-item" @click="activePanel = 'password'">
                <div class="icon">🔒</div>
                <span>修改密码</span>
                <div class="arrow">›</div>
              </div>
            </div>

            <button class="logout-btn" @click="handleLogout">
              退出登录
            </button>
          </div>

          <!-- 修改用户名视图 -->
          <div v-else-if="activePanel === 'username'" key="username" class="panel-content">
            <div class="panel-header">
              <button class="back-btn" @click="resetForm">‹ 返回</button>
              <h4>修改用户名</h4>
            </div>
            <form @submit.prevent="handleSubmitUsername" class="edit-form">
              <div class="input-group">
                <label>新用户名</label>
                <input
                  type="text"
                  v-model="form.username"
                  placeholder="请输入新的用户名 (仅英文字母)"
                  maxlength="80"
                />
              </div>
              <div class="input-group">
                <label>当前密码</label>
                <input
                  type="password"
                  v-model="form.oldPassword"
                  placeholder="请输入当前密码"
                />
              </div>
              <button type="submit" class="submit-btn">保存修改</button>
            </form>
          </div>

          <!-- 修改密码视图 -->
          <div v-else-if="activePanel === 'password'" key="password" class="panel-content">
            <div class="panel-header">
              <button class="back-btn" @click="resetForm">‹ 返回</button>
              <h4>修改密码</h4>
            </div>
            <form @submit.prevent="handleSubmitPassword" class="edit-form">
              <div class="input-group">
                <label>当前密码</label>
                <input
                  type="password"
                  v-model="form.oldPassword"
                  placeholder="请输入当前密码"
                />
              </div>
              <div class="input-group">
                <label>新密码</label>
                <input
                  type="password"
                  v-model="form.newPassword"
                  placeholder="6-18位字母或数字"
                  maxlength="18"
                />
              </div>
              <div class="input-group">
                <label>确认新密码</label>
                <input
                  type="password"
                  v-model="form.confirmPassword"
                  placeholder="再次输入新密码"
                  maxlength="18"
                />
              </div>
              <button type="submit" class="submit-btn">确认修改</button>
            </form>
          </div>

        </TransitionGroup>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { showToast } from '@/utils/toast'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

// 定义事件
const emit = defineEmits(['updateUsername', 'updatePassword', 'logout'])

// 状态管理：当前显示的面板
const activePanel = ref('menu')

// 表单数据
const form = reactive({
  username: '',
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

// 重置表单状态
const resetForm = () => {
  activePanel.value = 'menu'
  form.username = ''
  form.oldPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
}

// --- 业务逻辑 ---

// 1. 提交用户名修改
const handleSubmitUsername = () => {
  const usernameRegex = /^[a-zA-Z]{1,80}$/

  if (!form.oldPassword) {
    showToast('请输入当前密码！', 'error')
    return
  }
  if (!form.username) {
    showToast('用户名不能为空！', 'error')
    return
  }
  if (!usernameRegex.test(form.username)) {
    showToast('用户名格式错误：仅允许英文字母，且不能超过80个字符。', 'error')
    return
  }

  // 发送事件给父组件处理 API
  emit('updateUsername', { username: form.username, oldPassword: form.oldPassword })

  // 乐观更新或等待父组件反馈后关闭
  // resetForm()
}

// 2. 提交密码修改
const handleSubmitPassword = () => {
  const passwordRegex = /^[a-zA-Z0-9]{6,18}$/

  if (!form.oldPassword) {
    showToast('请输入当前密码！', 'error')
    return
  }
  if (!passwordRegex.test(form.newPassword)) {
    showToast('新密码格式错误：长度需在6~18位之间，且只能包含英文字母和数字。', 'error')
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    showToast('两次输入的新密码不一致！', 'error')
    return
  }

  // 发送事件
  emit('updatePassword', {
    oldPassword: form.oldPassword,
    newPassword: form.newPassword
  })
}

// 3. 退出登录
const handleLogout = () => {
  if (confirm('确定要退出登录吗？')) {
    emit('logout')
  }
}
</script>

<style scoped>
.user-card-container {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  pointer-events: none;
}
.glass-card {
  position: relative;
  width: 420px;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  z-index: 10;
  color: #555;
  pointer-events: auto;
  overflow: hidden;
}
.user-header {
  display: flex;
  align-items: center;
  padding-bottom: 20px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  margin-bottom: 20px;
}
.avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  justify-content: center;
  align-items: center;
  color: #fff;
  font-size: 24px;
  font-weight: 600;
  margin-right: 16px;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}
.user-info .username {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}
.user-info .user-id {
  margin: 4px 0 0 0;
  font-size: 12px;
  color: #999;
}
.card-body {
  position: relative;
  min-height: 260px;
}
.transition-wrapper {
  position: relative;
  width: 100%;
}
.menu-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.menu-item {
  display: flex;
  align-items: center;
  padding: 14px 16px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.menu-item:hover {
  background: rgba(102, 126, 234, 0.08);
  transform: translateX(4px);
}
.menu-item .icon {
  font-size: 18px;
  margin-right: 12px;
}
.menu-item span {
  flex: 1;
  font-size: 15px;
  color: #444;
}
.menu-item .arrow {
  font-size: 18px;
  color: #ccc;
  font-weight: 300;
}
.logout-btn {
  width: 100%;
  margin-top: 30px;
  padding: 12px;
  background: transparent;
  border: 1px solid rgba(255, 100, 100, 0.3);
  border-radius: 12px;
  color: #ff6b6b;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.3s ease;
}
.logout-btn:hover {
  background: rgba(255, 100, 100, 0.1);
  border-color: rgba(255, 100, 100, 0.5);
}
.panel-header {
  display: flex;
  align-items: center;
  margin-bottom: 24px;
}
.back-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #888;
  cursor: pointer;
  padding-right: 12px;
  transition: color 0.2s;
}
.back-btn:hover { color: #333; }
.panel-header h4 {
  margin: 0;
  font-size: 16px;
  color: #333;
  font-weight: 500;
}
.edit-form {
  display: flex;
  flex-direction: column;
}
.input-group {
  margin-bottom: 20px;
}
.input-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #666;
}
.input-group input {
  width: 100%;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 10px;
  color: #333;
  font-size: 15px;
  outline: none;
  transition: all 0.3s ease;
  box-sizing: border-box;
}
.input-group input:focus {
  background: rgba(255, 255, 255, 0.9);
  border-color: #a8c0ff;
  box-shadow: 0 0 0 3px rgba(168, 192, 255, 0.15);
}
.submit-btn {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 12px;
  color: #fff;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
  margin-top: 10px;
}
.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}
.soft-transition-enter-active,
.soft-transition-leave-active {
  transition: all 0.35s ease;
}
.soft-transition-enter-from {
  opacity: 0;
  transform: translateX(20px);
}
.soft-transition-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}
.soft-transition-leave-active {
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}
</style>
