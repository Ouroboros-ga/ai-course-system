<script setup>
import { ref } from 'vue'

// 状态管理：当前是否为登录模式
const isLoginMode = ref(true)

// 表单数据
const form = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// 提交表单
const handleSubmit = () => {
  if (isLoginMode.value) {
    console.log('登录信息:', { email: form.value.email, password: form.value.password })
    alert('登录请求已发送（查看控制台）')
  } else {
    if (form.value.password !== form.value.confirmPassword) {
      alert('两次密码输入不一致！')
      return
    }
    console.log('注册信息:', form.value)
    alert('注册请求已发送（查看控制台）')
  }
}
</script>

<template>
  <div class="login-container">
    <!-- 毛玻璃卡片 -->
    <div class="glass-card">
      <!-- 头部切换 Tab -->
      <div class="tab-header">
        <button
          :class="{ active: isLoginMode }"
          @click="isLoginMode = true"
        >
          登录
        </button>
        <button
          :class="{ active: !isLoginMode }"
          @click="isLoginMode = false"
        >
          注册
        </button>
        <!-- 滑块背景 -->
        <div class="slider" :class="{ 'slider-right': !isLoginMode }"></div>
      </div>

      <!-- 表单区域 -->
      <form @submit.prevent="handleSubmit" class="form-body">
        <!-- 使用 transition-group 实现平滑过渡 -->
        <TransitionGroup name="soft-transition" tag="div" class="form-wrapper">

          <!-- 登录模板 -->
          <div v-if="isLoginMode" key="login" class="form-content">
            <div class="input-group">
              <label>邮箱</label>
              <input
                type="email"
                v-model="form.email"
                placeholder="请输入邮箱"
                required
              />
            </div>
            <div class="input-group">
              <label>密码</label>
              <input
                type="password"
                v-model="form.password"
                placeholder="请输入密码"
                required
              />
            </div>
            <div class="options">
              <label class="remember">
                <input type="checkbox"> 记住我
              </label>
              <a href="#" class="forgot">忘记密码？</a>
            </div>
          </div>

          <!-- 注册模板 -->
          <div v-else key="register" class="form-content">
            <div class="input-group">
              <label>用户名</label>
              <input
                type="text"
                v-model="form.username"
                placeholder="请输入用户名"
                required
              />
            </div>
            <div class="input-group">
              <label>邮箱</label>
              <input
                type="email"
                v-model="form.email"
                placeholder="请输入邮箱"
                required
              />
            </div>
            <div class="input-group">
              <label>密码</label>
              <input
                type="password"
                v-model="form.password"
                placeholder="请输入密码"
                required
              />
            </div>
            <div class="input-group">
              <label>确认密码</label>
              <input
                type="password"
                v-model="form.confirmPassword"
                placeholder="再次输入密码"
                required
              />
            </div>
          </div>

        </TransitionGroup>

        <!-- 提交按钮 -->
        <button type="submit" class="submit-btn">
          {{ isLoginMode ? '登 录' : '创 建 账 户' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
/* --- 容器与背景 --- */
/* Login.vue 中的 <style scoped> */
.login-container {
  /* 1. 删除 top/left/transform 的居中方式 */
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;

  /* 2. 使用 Flexbox 实现水平垂直居中 */
  display: flex;
  justify-content: center;
  align-items: center;

  overflow: hidden;
  font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  /* 确保 z-index 足够高，盖住下面的内容 */
  z-index: 20;

  pointer-events: none; /* 让鼠标事件穿透 */
}



/* --- 毛玻璃卡片 --- */
.glass-card {
  position: relative;
  width: 420px;
  padding: 40px;
  /* 白色半透明背景，营造高级玻璃感 */
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(15px);
  -webkit-backdrop-filter: blur(15px);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  z-index: 10;
  color: #555; /* 全局灰色字体 */

  pointer-events: auto;
}

/* --- 头部切换 --- */
.tab-header {
  display: flex;
  position: relative;
  margin-bottom: 35px;
  background: rgba(0, 0, 0, 0.03); /* 极淡的灰底 */
  border-radius: 12px;
  padding: 4px;
}

.tab-header button {
  flex: 1;
  padding: 12px 0;
  background: transparent;
  border: none;
  color: #888; /* 未激活时深灰 */
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.3s ease; /* 柔和过渡 */
  z-index: 2;
}

.tab-header button.active {
  color: #333; /* 激活时主色 */
}

.tab-header .slider {
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc(50% - 4px);
  height: calc(100% - 8px);
  background: #fff;
  border-radius: 8px;
  /* 修改动画：去掉弹跳，使用柔和的 ease */
  transition: transform 0.35s ease-in-out;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  z-index: 1;
}

.tab-header .slider.slider-right {
  transform: translateX(100%);
}

/* --- 表单样式 --- */
.form-body {
  position: relative;
  min-height: 250px;
}

.input-group {
  margin-bottom: 24px;
}

.input-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #666; /* 标签灰色 */
}

.input-group input {
  width: 100%;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.5); /* 半透明白底输入框 */
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 10px;
  color: #333; /* 输入内容灰色 */
  font-size: 15px;
  outline: none;
  transition: all 0.3s ease;
  box-sizing: border-box;
}

.input-group input::placeholder {
  color: #a0a0a0; /* 占位符浅灰 */
}

.input-group input:focus {
  background: rgba(255, 255, 255, 0.9);
  border-color: #a8c0ff; /* 柔和的聚焦色 */
  box-shadow: 0 0 0 3px rgba(168, 192, 255, 0.15); /* 极淡的光晕 */
}

/* 辅助选项 */
.options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  font-size: 13px;
}

.options .remember {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #666;
}

.options .forgot {
  color: #888;
  text-decoration: none;
  transition: color 0.3s;
}

.options .forgot:hover {
  color: #333;
}

/* --- 提交按钮 --- */
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
}

.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}

.submit-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 10px rgba(102, 126, 234, 0.4);
}

/* --- 动画定义 --- */
/* 柔和的淡入淡出上移动画 */
.soft-transition-enter-active,
.soft-transition-leave-active {
  transition: all 0.35s ease;
}

.soft-transition-enter-from {
  opacity: 0;
  transform: translateY(15px); /* 从下方淡入 */
}

.soft-transition-leave-to {
  opacity: 0;
  transform: translateY(-15px); /* 向上方淡出 */
}

/* 确保离开的元素绝对定位，不占空间 */
.soft-transition-leave-active {
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}

.form-wrapper {
  position: relative;
  width: 100%;
}
</style>
