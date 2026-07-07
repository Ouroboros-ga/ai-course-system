<script setup>
import { ref } from 'vue'
import { showToast } from '@/utils/toast.js'
import { LogIn, UserPlus, User, Lock, Eye, EyeOff } from 'lucide-vue-next'

// 状态管理：当前是否为登录模式
const isLoginMode = ref(true)

// 密码显示切换
const showPassword = ref(false)
const showConfirmPassword = ref(false)

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
          <LogIn :size="18" />
          登录
        </button>
        <button
          :class="{ active: !isLoginMode }"
          @click="isLoginMode = false"
        >
          <UserPlus :size="18" />
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
              <div class="input-wrapper">
                <User class="input-icon" :size="20" />
                <input
                  type="text"
                  v-model="form.username"
                  placeholder="请输入用户名 (仅英文字母)"
                  maxlength="80"
                  required
                />
              </div>
            </div>
            <div class="input-group">
              <label>密码</label>
              <div class="input-wrapper has-toggle">
                <Lock class="input-icon" :size="20" />
                <input
                  :type="showPassword ? 'text' : 'password'"
                  v-model="form.password"
                  placeholder="请输入密码 (6-18位字母或数字)"
                  maxlength="18"
                  required
                />
                <button
                  type="button"
                  class="password-toggle"
                  @click="showPassword = !showPassword"
                  :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                >
                  <Eye v-if="showPassword" :size="20" />
                  <EyeOff v-else :size="20" />
                </button>
              </div>
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
              <div class="input-wrapper">
                <User class="input-icon" :size="20" />
                <input
                  type="text"
                  v-model="form.username"
                  placeholder="请输入用户名 (仅英文字母)"
                  maxlength="80"
                  required
                />
              </div>
            </div>
            <div class="input-group">
              <label>密码</label>
              <div class="input-wrapper has-toggle">
                <Lock class="input-icon" :size="20" />
                <input
                  :type="showPassword ? 'text' : 'password'"
                  v-model="form.password"
                  placeholder="请输入密码 (6-18位字母或数字)"
                  maxlength="18"
                  required
                />
                <button
                  type="button"
                  class="password-toggle"
                  @click="showPassword = !showPassword"
                  :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                >
                  <Eye v-if="showPassword" :size="20" />
                  <EyeOff v-else :size="20" />
                </button>
              </div>
            </div>
            <div class="input-group">
              <label>确认密码</label>
              <div class="input-wrapper has-toggle">
                <Lock class="input-icon" :size="20" />
                <input
                  :type="showConfirmPassword ? 'text' : 'password'"
                  v-model="form.confirmPassword"
                  placeholder="再次输入密码"
                  maxlength="18"
                  required
                />
                <button
                  type="button"
                  class="password-toggle"
                  @click="showConfirmPassword = !showConfirmPassword"
                  :aria-label="showConfirmPassword ? '隐藏密码' : '显示密码'"
                >
                  <Eye v-if="showConfirmPassword" :size="20" />
                  <EyeOff v-else :size="20" />
                </button>
              </div>
            </div>
          </div>

        </TransitionGroup>

        <!-- 提交按钮 -->
        <button type="submit" class="submit-btn">
          <LogIn v-if="isLoginMode" :size="20" />
          <UserPlus v-else :size="20" />
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
  font-family: var(--font-sans);
  pointer-events: none;
  transform: translateY(calc(-1 * var(--space-12)));
}

/* --- 毛玻璃卡片 --- */
.glass-card {
  position: relative;
  width: 420px;
  padding: var(--space-7);
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-overlay);
  color: var(--color-text-secondary);
  pointer-events: auto;
}

/* --- 头部切换 --- */
.tab-header {
  display: flex;
  position: relative;
  margin-bottom: var(--space-7);
  background: var(--color-surface-2);
  border-radius: var(--radius-lg);
  padding: var(--space-1);
}

.tab-header button {
  flex: 1;
  padding: var(--space-3) 0;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: color var(--duration-slow) var(--ease);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.tab-header button.active {
  color: var(--color-text);
}

.tab-header .slider {
  position: absolute;
  top: var(--space-1);
  left: var(--space-1);
  width: calc(50% - var(--space-1));
  height: calc(100% - var(--space-2));
  background: var(--color-surface);
  border-radius: var(--radius-md);
  transition: transform var(--duration-slow) var(--ease-spring);
  box-shadow: var(--shadow-sm);
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
  margin-bottom: var(--space-6);
}

.input-group label {
  display: block;
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: var(--space-4);
  color: var(--color-text-muted);
  pointer-events: none;
  transition: color var(--duration-normal) var(--ease);
  flex-shrink: 0;
}

.input-wrapper:focus-within .input-icon {
  color: var(--color-primary);
}

.input-wrapper input {
  width: 100%;
  padding: var(--space-4);
  padding-left: calc(var(--space-5) + var(--space-5));
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  color: var(--color-text);
  font-size: var(--text-base);
  font-family: var(--font-sans);
  outline: none;
  transition: border-color var(--duration-normal) var(--ease),
              box-shadow var(--duration-normal) var(--ease);
  box-sizing: border-box;
}

.input-wrapper input::placeholder {
  color: var(--color-text-muted);
}

.input-wrapper input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* 有密码切换按钮时，输入框右侧留空间 */
.input-wrapper.has-toggle input {
  padding-right: calc(var(--space-5) + var(--space-5));
}

/* 密码切换按钮 */
.password-toggle {
  position: absolute;
  right: var(--space-4);
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  transition: color var(--duration-normal) var(--ease);
  flex-shrink: 0;
}

.password-toggle:hover {
  color: var(--color-primary);
}

/* 辅助选项 */
.options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-7);
  font-size: var(--text-sm);
}

.options .remember {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  color: var(--color-text-secondary);
}

.options .remember input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

/* --- 提交按钮 --- */
.submit-btn {
  width: 100%;
  padding: var(--space-4);
  background: var(--gradient-primary);
  border: none;
  border-radius: var(--radius-lg);
  color: var(--color-primary-foreground);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: transform var(--duration-normal) var(--ease),
              box-shadow var(--duration-normal) var(--ease);
  box-shadow: var(--shadow-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.35);
}

.submit-btn:active {
  transform: translateY(0);
  box-shadow: var(--shadow-primary);
}

/* --- 动画定义 --- */
.soft-transition-enter-active,
.soft-transition-leave-active {
  transition: all var(--duration-slow) var(--ease);
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

/* --- 响应式 --- */
@media (max-width: 768px) {
  .glass-card {
    width: calc(100% - var(--space-6));
    max-width: 420px;
    padding: var(--space-5);
  }
}
</style>
