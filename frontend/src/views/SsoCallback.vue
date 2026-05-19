<template>
  <div class="sso-callback-page">
    <div class="sso-container">
      <div class="sso-logo">
        <span class="logo-icon">🦀</span>
        <h1>Smartrab 智课</h1>
      </div>

      <div v-if="status === 'loading'" class="sso-status loading">
        <div class="spinner-ring"></div>
        <h2>正在连接泛雅平台...</h2>
        <p class="sso-hint">正在同步您的账号信息，请稍候</p>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
      </div>

      <div v-else-if="status === 'success'" class="sso-status success">
        <div class="status-icon">✅</div>
        <h2>登录成功</h2>
        <p class="user-info">
          欢迎，{{ userInfo?.username }}
          <span v-if="userInfo?.isNewUser" class="new-user-badge">新用户</span>
        </p>
        <p v-if="userInfo?.fanyaId" class="fanya-info">泛雅ID: {{ userInfo.fanyaId }}</p>
        <button class="btn-enter" @click="enterSystem">进入智课系统 →</button>
      </div>

      <div v-else-if="status === 'error'" class="sso-status error">
        <div class="status-icon">❌</div>
        <h2>连接失败</h2>
        <p>{{ errorMessage }}</p>
        <div class="error-actions">
          <button class="btn-retry" @click="retrySSO">重试</button>
          <a href="/" class="btn-home">返回首页</a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ssoCallback } from '@/api/platform.js'
import { useCounterStore } from '@/stores/counter.js'

const route = useRoute()
const router = useRouter()
const counter = useCounterStore()

const status = ref('loading')
const progress = ref(0)
const userInfo = ref(null)
const errorMessage = ref('')

let progressTimer = null

onMounted(() => {
  handleSSO()
})

async function handleSSO() {
  const ticket = route.query.ticket
  if (!ticket) {
    status.value = 'error'
    errorMessage.value = '缺少泛雅授权票据(ticket)，请从泛雅平台重新进入'
    return
  }

  progressTimer = setInterval(() => {
    if (progress.value < 90) {
      progress.value += Math.random() * 15
    }
  }, 300)

  try {
    const res = await ssoCallback(ticket, route.query.redirect_url || '/')
    clearInterval(progressTimer)
    progress.value = 100

    if (res.code === 200 && res.data) {
      const { token, userInfo: info, redirectUrl } = res.data

      localStorage.setItem('token', token)
      counter.setUserInfo({
        userId: info.fanyaId,
        username: info.username,
        role: info.role,
        isLoggedIn: true,
        fanyaVerified: true,
      })

      userInfo.value = info
      status.value = 'success'

      setTimeout(() => {
        router.push(redirectUrl || '/')
      }, 1500)
    } else {
      throw new Error(res.message || 'SSO验证失败')
    }
  } catch (err) {
    clearInterval(progressTimer)
    status.value = 'error'
    errorMessage.value = err.response?.data?.message || err.message || '网络异常，请重试'
  }
}

function enterSystem() {
  router.push('/')
}

function retrySSO() {
  status.value = 'loading'
  progress.value = 0
  handleSSO()
}
</script>

<style scoped>
.sso-callback-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}

.sso-container {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 48px 56px;
  text-align: center;
  box-shadow: 0 25px 80px rgba(0, 0, 0, 0.3);
  max-width: 440px;
  width: 90%;
}

.sso-logo {
  margin-bottom: 32px;
}

.logo-icon {
  font-size: 48px;
}

.sso-logo h1 {
  margin-top: 8px;
  font-size: 24px;
  color: #1a1a2e;
  font-weight: 700;
}

.sso-status h2 {
  font-size: 20px;
  margin-bottom: 12px;
  color: #333;
}

.sso-hint {
  color: #888;
  font-size: 14px;
  margin-bottom: 24px;
}

.progress-bar {
  height: 6px;
  background: #eee;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #667eea, #764ba2);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.spinner-ring {
  width: 48px;
  height: 48px;
  border: 4px solid #e0e0e0;
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.status-icon {
  font-size: 56px;
  margin-bottom: 16px;
}

.user-info {
  font-size: 18px;
  color: #333;
  margin-bottom: 8px;
}

.new-user-badge {
  display: inline-block;
  background: #667eea;
  color: white;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  margin-left: 8px;
  vertical-align: middle;
}

.fanya-info {
  color: #999;
  font-size: 13px;
  margin-bottom: 24px;
}

.btn-enter {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  border: none;
  padding: 14px 36px;
  border-radius: 12px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-enter:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
}

.error-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 20px;
}

.btn-retry,
.btn-home {
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}

.btn-retry {
  background: #667eea;
  color: white;
  border: none;
}

.btn-home {
  background: transparent;
  color: #667eea;
  border: 1px solid #667eea;
}
</style>
