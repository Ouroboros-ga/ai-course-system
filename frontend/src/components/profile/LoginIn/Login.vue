<script setup>
import { ref } from 'vue'
import { showToast } from '@/utils/toast.js'

// 状态管理：当前是否为登录模式
const isLoginMode = ref(true)

// 自定义信号
const emit = defineEmits(['loginSend', 'registerSend']);


// 表单数据
const form = ref({
  username: '',
  password: '',
  confirmPassword: ''
})

// 提交表单
const handleSubmit = () => {
  // --- 定义校验规则 ---

  // 用户名规则：1-80位，纯英文字母
  const usernameRegex = /^[a-zA-Z]{1,80}$/

  // 密码规则：6-18位，仅包含英文字母和数字
  const passwordRegex = /^[a-zA-Z0-9]{6,18}$/

  // 1. 校验用户名
  if (!form.value.username) {
    showToast('用户名不能为空！')
    return
  }
  if (!usernameRegex.test(form.value.username)) {
    showToast('用户名格式错误：仅允许英文字母，且不能超过80个字符。')
    return
  }

  // 2. 校验密码
  if (!form.value.password) {
    showToast('密码不能为空！')
    return
  }
  if (!passwordRegex.test(form.value.password)) {
    showToast('密码格式错误：长度需在6~18位之间，且只能包含英文字母和数字。')
    return
  }

  // 3. 注册模式下的额外校验
  if (!isLoginMode.value) {
    if (form.value.password !== form.value.confirmPassword) {
      showToast('两次密码输入不一致！')
      return
    }
    // 注册：只发送 username 和 password
    const registerData = {
      username: form.value.username,
      password: form.value.password
    }
    emit('registerSend', registerData)
  } else {
    // 登录：发送 username 和 password
    const loginData = {
      username: form.value.username,
      password: form.value.password
    }
    emit('loginSend', loginData)
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
              <label>用户名</label>
              <input
                type="text"
                v-model="form.username"
                placeholder="请输入用户名 (仅英文字母)"
                maxlength="80"
                required
              />
            </div>
            <div class="input-group">
              <label>密码</label>
              <input
                type="password"
                v-model="form.password"
                placeholder="请输入密码 (6-18位字母或数字)"
                maxlength="18"
                required
              />
            </div>
            <div class="options">
              <label class="remember">
                <input type="checkbox"> 记住我
              </label>
<!--              <a href="#" class="forgot">忘记密码？</a>-->
            </div>
          </div>

          <!-- 注册模板 -->
          <div v-else key="register" class="form-content">
            <div class="input-group">
              <label>用户名</label>
              <input
                type="text"
                v-model="form.username"
                placeholder="请输入用户名 (仅英文字母)"
                maxlength="80"
                required
              />
            </div>
            <div class="input-group">
              <label>密码</label>
              <input
                type="password"
                v-model="form.password"
                placeholder="请输入密码 (6-18位字母或数字)"
                maxlength="18"
                required
              />
            </div>
            <div class="input-group">
              <label>确认密码</label>
              <input
                type="password"
                v-model="form.confirmPassword"
                placeholder="再次输入密码"
                maxlength="18"
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
.login-container {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  pointer-events: none;  /* 让非卡片区域点击穿透 */

  //background-color: red;
  transform: translateY(-80px);
}

/* --- 毛玻璃卡片 --- */
.glass-card {
  position: relative;
  width: 420px;
  padding: 40px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  z-index: 10;
  color: #555;
  pointer-events: auto;
}

/* --- 头部切换 --- */
.tab-header {
  display: flex;
  position: relative;
  margin-bottom: 35px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 12px;
  padding: 4px;
}

.tab-header button {
  flex: 1;
  padding: 12px 0;
  background: transparent;
  border: none;
  color: #888;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.3s ease;
  z-index: 2;
}

.tab-header button.active {
  color: #333;
}

.tab-header .slider {
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc(50% - 4px);
  height: calc(100% - 8px);
  background: #fff;
  border-radius: 8px;
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

.input-group input::placeholder {
  color: #a0a0a0;
}

.input-group input:focus {
  background: rgba(255, 255, 255, 0.9);
  border-color: #a8c0ff;
  box-shadow: 0 0 0 3px rgba(168, 192, 255, 0.15);
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
.soft-transition-enter-active,
.soft-transition-leave-active {
  transition: all 0.35s ease;
}

.soft-transition-enter-from {
  opacity: 0;
  transform: translateY(15px);
}

.soft-transition-leave-to {
  opacity: 0;
  transform: translateY(-15px);
}

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
