<template>
  <div class="sso-callback-page">
    <div class="sso-container">
      <div class="sso-logo">
        <GraduationCap class="logo-icon" :size="48" />
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
        <CheckCircle class="status-icon" :size="56" />
        <h2>登录成功</h2>
        <p class="user-info">
          欢迎，{{ userInfo?.username }}
          <span v-if="userInfo?.isNewUser" class="new-user-badge">新用户</span>
        </p>
        <p v-if="userInfo?.fanyaId" class="fanya-info">泛雅ID: {{ userInfo.fanyaId }}</p>
        <button class="btn-enter" @click="enterSystem">进入智课系统 <ArrowRight :size="16" /></button>
      </div>

      <div v-else-if="status === 'error'" class="sso-status error">
        <XCircle class="status-icon" :size="56" />
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
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GraduationCap, CheckCircle, XCircle, ArrowRight } from 'lucide-vue-next'
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
let redirectTimer = null

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

    const { token, userInfo: info, redirectUrl } = res

      localStorage.setItem('token', token)
      counter.setAuth({
        token: token,
        userInfo: {
          id: info.fanyaId,
          username: info.username,
        },
        role: info.role,
      })

      userInfo.value = info
      status.value = 'success'

      redirectTimer = setTimeout(() => {
        router.push(redirectUrl || '/')
      }, 1500)
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

onUnmounted(() => {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
  if (redirectTimer) {
    clearTimeout(redirectTimer)
    redirectTimer = null
  }
})
</script>

<style scoped>
.sso-callback-page {
  min-height: calc(100vh - var(--navbar-height));
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-2);
}

.sso-container {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-8);
  text-align: center;
  box-shadow: var(--shadow-xl);
  max-width: 440px;
  width: 90%;
}

.sso-logo {
  margin-bottom: var(--space-6);
}

.logo-icon {
  font-size: var(--space-8);
}

.sso-logo h1 {
  margin-top: var(--space-2);
  font-size: var(--text-2xl);
  color: var(--color-text);
  font-weight: var(--font-bold);
}

.sso-status h2 {
  font-size: var(--text-xl);
  margin-bottom: var(--space-3);
  color: var(--color-text);
}

.sso-hint {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin-bottom: var(--space-6);
}

.progress-bar {
  height: 6px;
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-sm);
  transition: width var(--duration-slow) var(--ease);
}

.spinner-ring {
  width: var(--space-8);
  height: var(--space-8);
  border: 4px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: var(--radius-full);
  animation: spin 0.8s linear infinite;
  margin: 0 auto var(--space-5);
}

.status-icon {
  font-size: var(--space-8);
  margin-bottom: var(--space-4);
}

.user-info {
  font-size: var(--text-lg);
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.new-user-badge {
  display: inline-block;
  background: var(--color-primary);
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-md);
  margin-left: var(--space-2);
  vertical-align: middle;
}

.fanya-info {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  margin-bottom: var(--space-6);
}

.btn-enter {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  padding: var(--space-3) var(--space-8);
  border-radius: var(--radius-lg);
  font-size: var(--text-base);
  cursor: pointer;
  transition: var(--transition-all);
}

.btn-enter:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.error-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: center;
  margin-top: var(--space-5);
}

.btn-retry,
.btn-home {
  padding: var(--space-2) var(--space-6);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}

.btn-retry {
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border: none;
}

.btn-home {
  background: transparent;
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
}
</style>
